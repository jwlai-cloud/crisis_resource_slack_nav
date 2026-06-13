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
token is applied as a per-call ``Authorization`` header override on the bot-token
``WebClient`` — the exact pattern :mod:`recall.client` uses for the user-scoped
search call — rather than constructing a second client. With no user token the
publish degrades quietly (logs and returns ``None``); it never falls back to the
bot token, which lacks ``canvases:write``.

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

from coordinator.board import BOARD_TITLE, compose_board_markdown
from matching.audit import audit_trail
from matching.index import offer_index

logger = logging.getLogger(__name__)


def _document_content(markdown: str) -> dict[str, str]:
    """The Canvas ``document_content`` payload for a markdown body."""
    return {"type": "markdown", "markdown": markdown}


def _user_auth(user_token: str) -> dict[str, str]:
    """The per-call header that authenticates a canvas write as the acting user.

    Mirrors :mod:`recall.client`: the bot-token ``WebClient`` carries the call, but
    a ``canvases:write`` user scope is required, so we override ``Authorization``
    per call with the user token rather than building a second client.
    """
    return {"Authorization": f"Bearer {user_token}"}


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

    def publish(self, client: WebClient, user_token: str | None) -> str | None:
        """Render the current board state and write it to the Canvas; return its id.

        Composes the board from the live singletons (offer index + audit trail),
        then either creates the canvas (first call) or replaces its whole document
        (later calls), authenticating as the user via ``user_token``. Best-effort:
        a missing token, or any API / client failure, is logged and swallowed —
        this returns ``None`` and never raises, so a caller hooked into a button
        handler is never broken by a Canvas problem.
        """
        if not user_token:
            logger.info("Coordinator board update skipped: no user token (canvases:write needed)")
            return None
        try:
            markdown = compose_board_markdown(offer_index.all_offers(), audit_trail.list_events())
            with self._lock:
                canvas_id = self._canvas_id
                if canvas_id is None:
                    canvas_id = self._create(client, user_token, markdown)
                    self._canvas_id = canvas_id
                else:
                    self._replace(client, user_token, canvas_id, markdown)
            return canvas_id
        except Exception as exc:
            logger.warning("Coordinator board update failed (handler unaffected): %s", exc)
            return None

    def recreate(self, client: WebClient, user_token: str | None) -> str | None:
        """Force-create a fresh board, dropping any stored id; return the new id.

        The on-demand entry point for the demo: a coordinator can always summon a
        clean board even if a prior one exists, without hunting for an old id.
        Best-effort like :meth:`publish`.
        """
        with self._lock:
            self._canvas_id = None
        return self.publish(client, user_token)

    def _create(self, client: WebClient, user_token: str, markdown: str) -> str:
        """Create the standalone canvas with the board markdown; return its id.

        Authored as the acting user via the per-call ``Authorization`` override.
        Raises ``KeyError`` if Slack returns no ``canvas_id`` — caught by
        :meth:`publish` and logged, so the board simply stays uncreated rather than
        crashing the handler.
        """
        response = client.canvases_create(
            title=BOARD_TITLE,
            document_content=_document_content(markdown),
            headers=_user_auth(user_token),
        )
        canvas_id = response["canvas_id"]
        logger.info("Created coordinator board canvas %s", canvas_id)
        return str(canvas_id)

    def _replace(self, client: WebClient, user_token: str, canvas_id: str, markdown: str) -> None:
        """Replace the entire canvas document with the freshly composed board.

        Uses ``canvases.edit`` with a single ``replace`` op and no ``section_id``,
        which overwrites the whole document — matching the full-recompose model.
        """
        client.canvases_edit(
            canvas_id=canvas_id,
            changes=[{"operation": "replace", "document_content": _document_content(markdown)}],
            headers=_user_auth(user_token),
        )
        logger.info("Updated coordinator board canvas %s", canvas_id)


# Module-level singleton: one board per socket-mode process, mirroring the index
# and audit-trail singletons it renders. The button handlers and the demand entry
# point import this instance directly.
coordinator_board = CoordinatorBoard()


def update_board(client: WebClient, user_token: str | None) -> None:
    """Best-effort board refresh, safe to call from a button handler.

    A thin no-return wrapper over :meth:`CoordinatorBoard.publish` for the handler
    hooks: it never raises and ignores the returned id, so a board failure can
    never break Connect / Resolve / Dismiss. ``user_token`` is the user-scope token
    the canvas write needs (``None`` -> the refresh is skipped, logged). The handler
    calls this *after* its own work has completed.
    """
    coordinator_board.publish(client, user_token)
