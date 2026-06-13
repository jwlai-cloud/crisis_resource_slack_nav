"""Publish the coordinator board to a Slack Canvas — the *write* step (task 017).

This is the only module that touches the Slack Canvas API. It owns the
find-or-create lifecycle and the best-effort update; :mod:`coordinator.board`
owns the pure markdown composition it renders.

**Canvas API decision** (see the task log + ``docs/adr/0005-canvas-as-durable-board.md``).
The board is the **channel canvas** of ``CRISIS_CHANNEL`` (task 025): a permanent
top-bar tab, not a standalone canvas a coordinator has to hunt for under Files or
reach through a bookmark. Access is tied to channel access — anyone in the channel
sees the tab. The installed ``slack_sdk`` supports the full lifecycle:

* ``conversations_canvases_create(channel_id=..., document_content={"type":
  "markdown","markdown":...})`` mints the channel's canvas (flipping on the tab)
  and returns its ``canvas_id``. A channel has exactly ONE canvas: calling create a
  second time returns ``channel_canvas_already_exists`` — so this is a *find-or-
  create*, never a blind create (see :meth:`CoordinatorBoard._create_channel_canvas`).
* ``conversations_info(channel=...)`` exposes an already-attached channel canvas at
  ``channel.properties.canvas.file_id`` — the discovery fallback when the persisted
  id is gone (e.g. after a restart) so we reattach rather than erroring on a second
  create.
* ``canvases_edit(canvas_id=..., changes=[{"operation":"replace",
  "document_content":{...}}])`` with **no** ``section_id`` replaces the *entire*
  document — unchanged from the standalone era: there is no separate
  ``conversations_canvases_edit``, a channel canvas is edited by the same call, so
  the whole-document recompose-and-overwrite model is untouched.

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
ADR-0005). The ``canvas_id`` lives in a process-local field, bridged across the
``make board`` script and the agent by the persisted store
(:mod:`coordinator.canvas_store`). As a channel canvas it is now also *re-findable*
from Slack itself: if the persisted id is gone, the create path discovers the
channel's existing canvas via ``conversations.info`` and reattaches to it, so a
restart no longer orphans the board behind a second-create error.

**Best-effort, never raises.** Every public call here catches *all* exceptions,
logs them, and returns rather than propagating — a Canvas failure must never break
the button handler it is hooked into (the degraded-state guardrail). The handler's
own work (open the DM, flip the card, post the confirmation) always stands.
"""

import logging
import threading

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from coordinator import canvas_store
from coordinator.announce import announce_board
from coordinator.board import compose_board_markdown
from coordinator.names import resolve_display_names
from coordinator.situation import SituationSnapshot, read_situation
from entities import Offer
from matching.audit import AuditEvent, audit_trail
from matching.index import offer_index

logger = logging.getLogger(__name__)


def designated_channel_id() -> str | None:
    """The CRISIS_CHANNEL id the board's canvas attaches to, or ``None`` when off.

    Delegates to :func:`listeners.channel_gate.designated_channel_id` — the single
    source of the ``CRISIS_CHANNEL`` env read (ADR-0004), not duplicated here. The
    import is deferred to call time to avoid an import cycle: ``listeners/__init__``
    eagerly pulls the action handlers, which import this very module. Tests patch
    this name to pin the channel without touching the environment.
    """
    from listeners.channel_gate import designated_channel_id as _designated_channel_id

    return _designated_channel_id()


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
# ``canvases_*`` / ``conversations_canvases_*`` methods — slack_sdk resets
# Authorization from its own token resolution after merging custom headers, so an
# empty bot token yields ``not_authed``. ``token=`` is the override that takes
# effect. ``conversations.canvases.create`` needs the same ``canvases:write``
# scope as the standalone create did — no NEW scope — plus channel membership
# (public channel, or the user invited to a private one); access to the canvas is
# then tied to channel access (task 025).


class CoordinatorBoard:
    """Find-or-create + update wrapper around the CRISIS_CHANNEL channel canvas.

    Holds the canvas's id in a process-local field (mirroring the in-memory posture
    of the index and audit trail it renders, bridged across processes by
    :mod:`coordinator.canvas_store`). The first publish find-or-creates the channel
    canvas — reattaching to a persisted id, else a canvas discovered on the channel
    via ``conversations.info``, else a fresh ``conversations.canvases.create`` that
    flips on the permanent top-bar tab; every later publish edits it via a full
    ``replace``. A :class:`threading.Lock` guards the id read-modify-write because
    button handlers publish from Bolt's thread pool.
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
        self,
        client: WebClient,
        user_token: str | None,
        team_id: str | None = None,
        team_url: str | None = None,
    ) -> str | None:
        """Render the current board state and write it to the channel canvas; return its id.

        Composes the board from the live singletons (offer index + audit trail),
        then either find-or-creates the channel canvas (first call) or replaces its
        whole document (later calls), authenticating as the user via ``user_token``.

        **Find-or-create.** Before minting, the first publish loads the id persisted
        by the other process (:func:`coordinator.canvas_store.load_canvas_id`) — so
        the ``make board`` script and the live agent operate on the *same* canvas.
        Only when no persisted id exists does it call
        :meth:`_create_channel_canvas`, which itself discovers the channel's existing
        canvas (``conversations.info``) before creating, so a restart with a lost id
        file reattaches rather than erroring on a second create.

        Best-effort: a missing token, an unset ``CRISIS_CHANNEL``, or any API /
        client / file failure, is logged and swallowed — this returns ``None`` and
        never raises, so a caller hooked into a button handler is never broken by a
        Canvas problem.

        ``team_id`` / ``team_url`` are used only to build a deep link in the create
        announcement; they are optional and the publish works without them.
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
                    canvas_id = self._create_channel_canvas(
                        client, user_token, markdown, team_id, team_url
                    )
                    self._canvas_id = canvas_id
                else:
                    self._replace(client, user_token, canvas_id, markdown)
                    self._canvas_id = canvas_id
            return canvas_id
        except Exception as exc:
            logger.warning("Coordinator board update failed (handler unaffected): %s", exc)
            return None

    def recreate(
        self,
        client: WebClient,
        user_token: str | None,
        team_id: str | None = None,
        team_url: str | None = None,
    ) -> str | None:
        """Force-create a fresh board, dropping any stored id; return the new id.

        The on-demand entry point for the demo: a coordinator can always summon a
        clean board even if a prior one exists, without hunting for an old id. The
        prior canvas (from the in-process field or the persisted store) is DELETED
        before minting fresh, so repeated recreates never orphan a pile of stale
        "Community Cases" canvases. Best-effort like :meth:`publish` — a failed
        delete is logged and never blocks the new board.
        """
        with self._lock:
            old_id = self._canvas_id or canvas_store.load_canvas_id()
            self._canvas_id = None
        if old_id and user_token:
            try:
                client.canvases_delete(canvas_id=old_id, token=user_token)
                logger.info("Deleted prior coordinator board canvas %s", old_id)
            except Exception as exc:
                logger.warning("Could not delete prior board canvas %s: %s", old_id, exc)
        return self._publish_fresh(client, user_token, team_id, team_url)

    def _publish_fresh(
        self,
        client: WebClient,
        user_token: str | None,
        team_id: str | None,
        team_url: str | None = None,
    ) -> str | None:
        """Like :meth:`publish` but always creates — bypasses the find-or-create reattach.

        Backs :meth:`recreate`: the demo "summon a clean board" path deletes the
        prior canvas, then mints a fresh channel canvas via
        :meth:`_mint_channel_canvas` (no persisted-id load, no ``conversations.info``
        discovery — both would reattach to a canvas the recreate just dropped).
        Best-effort, never raises.
        """
        if not user_token:
            logger.info("Coordinator board update skipped: no user token (canvases:write needed)")
            return None
        try:
            markdown = _compose_with_names(client, user_token)
            with self._lock:
                canvas_id = self._mint_channel_canvas(
                    client, user_token, markdown, team_id, team_url
                )
                self._canvas_id = canvas_id
            return canvas_id
        except Exception as exc:
            logger.warning("Coordinator board recreate failed: %s", exc)
            return None

    def _create_channel_canvas(
        self,
        client: WebClient,
        user_token: str,
        markdown: str,
        team_id: str | None,
        team_url: str | None = None,
    ) -> str:
        """Find-or-create the channel canvas for ``CRISIS_CHANNEL``; return its id.

        The board is the channel's one canvas (task 025), so this is a *find-or-
        create*, not a blind create:

        1. **Discover** an already-attached channel canvas via ``conversations.info``
           (``channel.properties.canvas.file_id``). If found, persist + reattach
           (edit) it — no announce, it is not a fresh board. This is the restart
           reattach path the persisted store cannot cover (a deleted id file).
        2. Else **create** the channel canvas with
           ``conversations.canvases.create``, which flips on the permanent top-bar
           tab. A race that yields ``channel_canvas_already_exists`` re-discovers
           the canvas the other writer created rather than crashing.

        Raises ``RuntimeError`` if no channel is configured (``CRISIS_CHANNEL``
        unset) or ``KeyError`` if Slack returns no ``canvas_id`` — both caught by
        :meth:`publish` and logged, so the board stays uncreated rather than
        crashing the handler.
        """
        channel = designated_channel_id()
        if channel is None:
            raise RuntimeError(
                "No CRISIS_CHANNEL configured — the board has no channel to attach its canvas to"
            )

        discovered = self._discover_channel_canvas_id(client, user_token, channel)
        if discovered is not None:
            logger.info("Reattaching to existing channel canvas %s in %s", discovered, channel)
            canvas_store.save_canvas_id(discovered)
            self._replace(client, user_token, discovered, markdown)
            return discovered

        try:
            response = client.conversations_canvases_create(
                channel_id=channel,
                document_content=_document_content(markdown),
                token=user_token,
            )
        except SlackApiError as exc:
            if (exc.response or {}).get("error") == "channel_canvas_already_exists":
                # Lost a create race: another writer attached the channel canvas
                # between our discovery and our create. Re-discover and reattach.
                raced = self._discover_channel_canvas_id(client, user_token, channel)
                if raced is None:
                    raise
                logger.info("Channel canvas already existed (race) — reattaching to %s", raced)
                canvas_store.save_canvas_id(raced)
                self._replace(client, user_token, raced, markdown)
                return raced
            raise

        canvas_id = str(response["canvas_id"])
        logger.info("Created coordinator board channel canvas %s in %s", canvas_id, channel)
        self._after_create(client, canvas_id, team_id, team_url, user_token)
        return canvas_id

    def _mint_channel_canvas(
        self,
        client: WebClient,
        user_token: str,
        markdown: str,
        team_id: str | None,
        team_url: str | None = None,
    ) -> str:
        """Create the channel canvas unconditionally — backs :meth:`recreate`.

        The demo "summon a clean board" path deletes the prior canvas first, so the
        channel has none; this mints a fresh one without the discovery/reattach the
        normal create runs (a recreate must never reattach to the canvas the store
        pointed at). Persists + announces exactly like a first create.
        """
        channel = designated_channel_id()
        if channel is None:
            raise RuntimeError(
                "No CRISIS_CHANNEL configured — the board has no channel to attach its canvas to"
            )
        response = client.conversations_canvases_create(
            channel_id=channel,
            document_content=_document_content(markdown),
            token=user_token,
        )
        canvas_id = str(response["canvas_id"])
        logger.info("Created coordinator board channel canvas %s in %s", canvas_id, channel)
        self._after_create(client, canvas_id, team_id, team_url, user_token)
        return canvas_id

    @staticmethod
    def _discover_channel_canvas_id(client: WebClient, user_token: str, channel: str) -> str | None:
        """The channel's existing canvas id from ``conversations.info``, or ``None``.

        Reads ``channel.properties.canvas`` — the documented location of an
        already-attached channel canvas (``conversations.canvases.create`` ref). The
        id key is ``file_id`` per Slack's shape; ``id``/``canvas_id`` are accepted as
        defensive fallbacks. Best-effort: any failure (info down, missing membership,
        no canvas yet) returns ``None`` so the caller degrades to creating one.
        """
        try:
            response = client.conversations_info(channel=channel, token=user_token)
        except Exception as exc:
            logger.info("conversations.info lookup failed (will create canvas): %s", exc)
            return None
        canvas = ((response.get("channel") or {}).get("properties") or {}).get("canvas") or {}
        file_id = canvas.get("file_id") or canvas.get("id") or canvas.get("canvas_id")
        return str(file_id) if file_id else None

    def _after_create(
        self,
        client: WebClient,
        canvas_id: str,
        team_id: str | None,
        team_url: str | None,
        user_token: str,
    ) -> None:
        """Persist the new canvas id and announce its link once — both best-effort.

        Runs only on a *real* create (not a reattach): persists to the shared store
        so the other process reattaches instead of minting a duplicate, then posts
        the one-time "the Community Cases board tab is live" announce. The tab itself
        is now the primary discovery (task 025) — the announce is a minimal courtesy
        note, kept because it costs nothing and helps a coordinator who is not yet
        looking at the channel. The bookmark (task 023) is gone: the permanent tab
        supersedes it. An announce failure is logged and never undoes the create.
        """
        canvas_store.save_canvas_id(canvas_id)
        try:
            announce_board(
                client,
                canvas_id=canvas_id,
                team_id=team_id,
                team_url=team_url,
                user_token=user_token,
            )
        except Exception as exc:
            # announce_board is already best-effort, but never let an unexpected
            # error here undo a successful create.
            logger.warning("Coordinator board announce raised unexpectedly: %s", exc)

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


def update_board(
    client: WebClient,
    user_token: str | None,
    team_id: str | None = None,
    team_url: str | None = None,
) -> None:
    """Best-effort board refresh, safe to call from a button handler.

    A thin no-return wrapper over :meth:`CoordinatorBoard.publish` for the handler
    hooks: it never raises and ignores the returned id, so a board failure can
    never break Connect / Resolve / Dismiss. ``user_token`` is the user-scope token
    the canvas write needs (``None`` -> the refresh is skipped, logged). ``team_id``
    (from the Bolt context) lets a *first* refresh that has to create the canvas
    build a deep-link announcement; it is optional. The handler calls this *after*
    its own work has completed.
    """
    coordinator_board.publish(client, user_token, team_id, team_url)
