"""Coordinator board: a live Slack Canvas of community cases + the audit log.

The W4 oversight surface (task 017; design doc §5 "Coordinator oversight"). A
coordinator reads a Slack Canvas that shows every community case grouped by
lifecycle status plus the dated activity log of every human-confirmed action.

Two layers:

* :mod:`coordinator.board` — pure ``state -> markdown`` composition (Slack-free,
  unit-testable). Renders the matching index + audit trail into the Canvas's
  ``document_content``.
* :mod:`coordinator.canvas` — the publisher: find-or-create + best-effort
  ``replace`` update against the Slack Canvas API, using the user token. Hooked
  into the action-button handlers *after* their work, isolated so a Canvas failure
  never breaks a click.

The Canvas is the durable board (it survives a restart the in-memory index does
not — ADR-0005); the index stays the fast path (ADR-0003).
"""

from coordinator.board import BOARD_TITLE, compose_board_markdown
from coordinator.canvas import CoordinatorBoard, coordinator_board, update_board

__all__ = [
    "BOARD_TITLE",
    "CoordinatorBoard",
    "compose_board_markdown",
    "coordinator_board",
    "update_board",
]
