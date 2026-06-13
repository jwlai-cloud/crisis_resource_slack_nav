"""The cross-process canvas-id store — a tiny gitignored file two processes share.

The coordinator board (task 017, ADR-0005) is one Slack Canvas. But the
``make board`` script (``scripts/open_board.py``) and the live socket-mode agent
run as **separate processes**, each holding its own
:class:`~coordinator.canvas.CoordinatorBoard` with a process-local ``canvas_id``.
Without a shared handle the script mints a canvas the server never sees, and the
server lazily mints a *second* one on the first button action — a duplicate
nobody has a link to (the gap task 018 closes).

This module is that shared handle: the created ``canvas_id`` is persisted to a
single known file (``.slack/board_canvas_id``) that **both** processes read and
write. The script's create writes it; the server's first publish reads it and
*edits* that canvas instead of creating its own. ``.slack/`` already holds
Slack-CLI app state and is gitignored — the canvas id is sandbox-specific state,
not source, so it belongs there and is gitignored too.

**Best-effort, never raises.** A missing or corrupt file reads as ``None`` (the
caller then mints a fresh canvas — the pre-018 behaviour), and any I/O error on
read or write is logged and swallowed. A file problem must never break a button
handler or the board, exactly like the Canvas API calls themselves (ADR-0005's
degraded-state posture).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# The Slack-CLI app-state directory at the repo root. It already exists for the
# scaffold (config.json, hooks.json) and is gitignored, so the canvas-id file
# rides along as sandbox-specific state rather than committed source.
_STATE_DIR = ".slack"
_ID_FILENAME = "board_canvas_id"


def _id_path() -> Path:
    """Absolute path to the shared canvas-id file under the repo's ``.slack/`` dir.

    Resolved relative to this package's parent (the repo root) so it is stable
    regardless of the process's working directory — the script and the agent are
    launched from the same checkout but not guaranteed the same ``cwd``.
    """
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / _STATE_DIR / _ID_FILENAME


def load_canvas_id() -> str | None:
    """Read the persisted canvas id, or ``None`` when there is nothing usable.

    Returns ``None`` when the file is absent, empty/whitespace-only (corrupt), or
    unreadable — in every case the caller degrades to creating a fresh canvas.
    Never raises: an OS error is logged and swallowed.
    """
    path = _id_path()
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Could not read coordinator board canvas id (will create fresh): %s", exc)
        return None
    return raw or None


def save_canvas_id(canvas_id: str) -> None:
    """Persist the canvas id so the other process reattaches to the same canvas.

    Creates the ``.slack/`` parent if missing (a fresh checkout may not have it
    yet). Best-effort: an OS error is logged and swallowed — a failed persist just
    means the next process mints its own canvas, never a crash.
    """
    path = _id_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{canvas_id}\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist coordinator board canvas id %s: %s", canvas_id, exc)
        return
    logger.info("Persisted coordinator board canvas id %s to %s", canvas_id, path)
