"""Publish the coordinator board to a Slack Canvas — the *write* step (task 017).

This is the only module that touches the Slack Canvas API. It owns the
find-or-create lifecycle and the best-effort update; :mod:`coordinator.board`
owns the pure markdown composition it renders.

**Canvas API decision** (see the task log + ``docs/adr/0005-canvas-as-durable-board.md``).
A live-updating standalone canvas is supported by the installed ``slack_sdk``:

* ``canvases_create(title=..., document_content={"type":"markdown","markdown":...})``
  mints the board and returns its ``canvas_id``.
* ``canvases_edit(canvas_id=..., changes=[{"operation":"replace",
  "document_content":{...}}])`` with **no** ``section_id`` replaces the *entire*
  document — so we recompose the whole board from current state on every update
  and overwrite, never diffing sections.

**Token.** The canvas is authored as the acting *user* (the coordinator): the
manifest grants ``canvases:read``/``canvases:write`` as user scopes, so the write
uses ``SLACK_USER_TOKEN`` (the same user token RTS search and the MCP toolset use,
resolved via :func:`agent.deps.resolve_user_token`). No bot scope is needed. The
token is applied as slack_sdk's per-call ``token=`` override on the bot-token
``WebClient`` rather than constructing a second client. (A manual
``Authorization`` header override — the ``recall.client`` pattern — does NOT work
for the typed ``canvases_*`` methods: slack_sdk resets Authorization from its own
token after merging custom headers, so it must be the ``token=`` kwarg.) With no
user token the publish degrades quietly (logs and returns ``None``); it never falls
back to the bot token, which lacks ``canvases:write``.

**Durability + restart.** The Canvas is the durable board: Slack persists it, so it
survives an agent restart even though the in-memory index does not (ADR-0003,
ADR-0005). The ``canvas_id`` itself lives in a process-local store here — after a
restart that handle is lost, so the next demand-trigger creates a *fresh* canvas
rather than re-finding the old one. That is the deliberate W4 scope: the board's
*content* is durable in Slack; reattaching to a prior canvas across restarts is the
deferred rehydration question (ADR-0005). For the demo the coordinator (re)opens
the board on demand via the entry point.

**Best-effort, never raises.** Every public call here catches *all* exceptions,
logs them, and returns rather than propagating — a Canvas failure must never break
the button handler it is hooked into (the degraded-state guardrail). The handler's
own work (open the DM, flip the card, post the confirmation) always stands.
"""

import logging
import threading

from slack_sdk import WebClient

from coordinator import canvas_store
from coordinator.announce import announce_board
from coordinator.board import BOARD_TITLE, compose_board_markdown
from coordinator.names import resolve_display_names
from coordinator.situation import SituationSnapshot, read_situation
from entities import Offer
from matching.audit import AuditEvent, audit_trail
from matching.index import offer_index

logger = logging.getLogger(__name__)

# Prefix a button handler writes when an audit target names an offerer by id (see
# ``crisis_buttons._offer_target``); the user id after it is worth resolving too.
_OFFERER_TARGET_PREFIX = "offerer:"


def _document_content(markdown: str) -> dict[str, str]:
    """The Canvas ``document_content`` payload for a markdown body."""
    return {"type": "markdown", "markdown": markdown}


def _person_ids(offers: list[Offer], events: list[AuditEvent]) -> set[str]:
    """Every distinct user id the board renders as a person.

    Spans offerers on every case row, the actor on every audit event, and the
    offerer id carried in an ``offerer:<id>`` audit target — so the name lookup
    covers every id the board would otherwise show raw.
    """
    ids: set[str] = {offer.offerer for offer in offers}
    for event in events:
        ids.add(event.actor_id)
        if event.target.startswith(_OFFERER_TARGET_PREFIX):
            ids.add(event.target[len(_OFFERER_TARGET_PREFIX) :])
    return ids


def _read_situation_best_effort() -> SituationSnapshot | None:
    """Read the official situation for the board, swallowing any failure.

    The impure fetch boundary for the Situation section (mirrors the names
    boundary). :func:`coordinator.situation.read_situation` is itself best-effort
    and already degrades a down feed to an explicit marker, but this wrapper also
    catches an *unexpected* raise so a situation-read problem degrades to *no*
    Situation section rather than breaking the board update — the
    cases + activity log still publish.
    """
    try:
        return read_situation()
    except Exception as exc:
        logger.warning("Situation read failed; board renders without it: %s", exc)
        return None


def _compose_with_names(client: WebClient, user_token: str) -> str:
    """Compose the current board, resolving names and reading the official situation.

    The impure boundary the pure composer relies on: it snapshots the live
    offer-index + audit-trail state, best-effort resolves the people's display
    names via ``users.info`` (a canvas does not resolve ``<@id>`` mention syntax),
    best-effort reads the official situation from the feeds, and threads both the
    resulting ``{id: name}`` map and the :class:`SituationSnapshot` into
    :func:`compose_board_markdown`. Either lookup failing is swallowed — the board
    still composes (bare ids / no Situation section) rather than breaking the
    refresh.
    """
    offers = offer_index.all_offers()
    events = audit_trail.list_events()
    try:
        names = resolve_display_names(client, user_token, _person_ids(offers, events))
    except Exception as exc:
        logger.warning("Display-name resolution failed; rendering bare ids: %s", exc)
        names = {}
    situation = _read_situation_best_effort()
    return compose_board_markdown(offers, events, names, situation)


# The canvas write authenticates as the acting user (a canvases:write USER scope)
# via slack_sdk's first-class per-call ``token=`` override. NOTE: a manual
# ``headers={"Authorization": ...}`` override does NOT work for the typed
# ``canvases_*`` methods — slack_sdk resets Authorization from its own token
# resolution after merging custom headers, so an empty bot token yields
# ``not_authed``. ``token=`` is the override that actually takes effect.


class CoordinatorBoard:
    """Find-or-create + update wrapper around one coordinator Canvas.

    Holds the created canvas's id in a process-local field (mirroring the
    in-memory posture of the index and audit trail it renders). The first publish
    creates the canvas; every later publish edits it via a full ``replace``. A
    :class:`threading.Lock` guards the id read-modify-write because button handlers
    publish from Bolt's thread pool.
    """

    def __init__(self) -> None:
        self._canvas_id: str | None = None
        self._lock = threading.Lock()

    @property
    def canvas_id(self) -> str | None:
        """The current canvas id, or ``None`` before the board has been created."""
        with self._lock:
            return self._canvas_id

    def publish(
        self, client: WebClient, user_token: str | None, team_id: str | None = None
    ) -> str | None:
        """Render the current board state and write it to the Canvas; return its id.

        Composes the board from the live singletons (offer index + audit trail),
        then either creates the canvas (first call) or replaces its whole document
        (later calls), authenticating as the user via ``user_token``.

        **Cross-process reattach (task 018).** Before minting a new canvas, the
        first publish loads the id persisted by the other process
        (:func:`coordinator.canvas_store.load_canvas_id`) — so the ``make board``
        script and the live agent operate on the *same* canvas. Only when no
        persisted id exists does it create one, then persist it (so the other
        process reattaches) and announce its link once (:func:`announce_board`).

        Best-effort: a missing token, or any API / client / file failure, is
        logged and swallowed — this returns ``None`` and never raises, so a caller
        hooked into a button handler is never broken by a Canvas problem.

        ``team_id`` is used only to build a deep link in the create announcement;
        it is optional and the publish works without it.
        """
        if not user_token:
            logger.info("Coordinator board update skipped: no user token (canvases:write needed)")
            return None
        try:
            markdown = _compose_with_names(client, user_token)
            with self._lock:
                canvas_id = self._canvas_id
                if canvas_id is None:
                    # Reattach to the canvas the other process persisted, if any,
                    # before deciding to mint a fresh one.
                    canvas_id = canvas_store.load_canvas_id()
                if canvas_id is None:
                    canvas_id = self._create(client, user_token, markdown, team_id)
                    self._canvas_id = canvas_id
                else:
                    self._replace(client, user_token, canvas_id, markdown)
                    self._canvas_id = canvas_id
            return canvas_id
        except Exception as exc:
            logger.warning("Coordinator board update failed (handler unaffected): %s", exc)
            return None

    def recreate(
        self, client: WebClient, user_token: str | None, team_id: str | None = None
    ) -> str | None:
        """Force-create a fresh board, dropping any stored id; return the new id.

        The on-demand entry point for the demo: a coordinator can always summon a
        clean board even if a prior one exists, without hunting for an old id. The
        in-process id is cleared *and* the persisted id is ignored — the create
        path mints a brand-new canvas, persists it, and announces it. Best-effort
        like :meth:`publish`.
        """
        with self._lock:
            self._canvas_id = None
        # Drop the persisted handle too, so recreate always mints fresh rather
        # than reattaching to a prior canvas via the shared store.
        return self._publish_fresh(client, user_token, team_id)

    def _publish_fresh(
        self, client: WebClient, user_token: str | None, team_id: str | None
    ) -> str | None:
        """Like :meth:`publish` but always creates — bypasses the persisted-id reattach.

        Backs :meth:`recreate`: the demo "summon a clean board" path must not
        reattach to the old canvas the store points at. Best-effort, never raises.
        """
        if not user_token:
            logger.info("Coordinator board update skipped: no user token (canvases:write needed)")
            return None
        try:
            markdown = _compose_with_names(client, user_token)
            with self._lock:
                canvas_id = self._create(client, user_token, markdown, team_id)
                self._canvas_id = canvas_id
            return canvas_id
        except Exception as exc:
            logger.warning("Coordinator board recreate failed: %s", exc)
            return None

    def _create(
        self, client: WebClient, user_token: str, markdown: str, team_id: str | None
    ) -> str:
        """Create the standalone canvas with the board markdown; return its id.

        Authored as the acting user via the per-call ``Authorization`` override.
        Raises ``KeyError`` if Slack returns no ``canvas_id`` — caught by
        :meth:`publish` and logged, so the board simply stays uncreated rather than
        crashing the handler.

        On a successful create the id is persisted to the shared store (so the
        other process reattaches instead of minting a duplicate) and the board
        link is announced once to the coordinator channel. Both are best-effort
        and isolated: a persist or announce failure is logged inside its own
        helper and never undoes the create.
        """
        response = client.canvases_create(
            title=BOARD_TITLE,
            document_content=_document_content(markdown),
            token=user_token,
        )
        canvas_id = str(response["canvas_id"])
        logger.info("Created coordinator board canvas %s", canvas_id)
        canvas_store.save_canvas_id(canvas_id)
        try:
            announce_board(client, canvas_id=canvas_id, team_id=team_id, user_token=user_token)
        except Exception as exc:
            # announce_board is already best-effort, but never let an unexpected
            # error here undo a successful create.
            logger.warning("Coordinator board announce raised unexpectedly: %s", exc)
        return canvas_id

    def _replace(self, client: WebClient, user_token: str, canvas_id: str, markdown: str) -> None:
        """Replace the entire canvas document with the freshly composed board.

        Uses ``canvases.edit`` with a single ``replace`` op and no ``section_id``,
        which overwrites the whole document — matching the full-recompose model.
        """
        client.canvases_edit(
            canvas_id=canvas_id,
            changes=[{"operation": "replace", "document_content": _document_content(markdown)}],
            token=user_token,
        )
        logger.info("Updated coordinator board canvas %s", canvas_id)


# Module-level singleton: one board per socket-mode process, mirroring the index
# and audit-trail singletons it renders. The button handlers and the demand entry
# point import this instance directly.
coordinator_board = CoordinatorBoard()


def update_board(client: WebClient, user_token: str | None, team_id: str | None = None) -> None:
    """Best-effort board refresh, safe to call from a button handler.

    A thin no-return wrapper over :meth:`CoordinatorBoard.publish` for the handler
    hooks: it never raises and ignores the returned id, so a board failure can
    never break Connect / Resolve / Dismiss. ``user_token`` is the user-scope token
    the canvas write needs (``None`` -> the refresh is skipped, logged). ``team_id``
    (from the Bolt context) lets a *first* refresh that has to create the canvas
    build a deep-link announcement; it is optional. The handler calls this *after*
    its own work has completed.
    """
    coordinator_board.publish(client, user_token, team_id)
