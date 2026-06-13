"""Open (or re-create) the coordinator board on demand — the demo entry point.

The coordinator board is a Slack Canvas a coordinator reads to watch community
cases move open -> connected -> resolved alongside the audit log of every
human-confirmed action (task 017). The button handlers refresh it automatically on
every Connect / Resolve / Dismiss, but a coordinator needs a way to *summon* it —
on first use, or fresh for the demo. This script is that mechanism.

Run it (the agent process need not be running — this is a standalone one-shot):

    uv run python -m scripts.open_board

It creates a brand-new standalone Canvas owned by the acting user and writes the
current board into it, printing the canvas id and a tip to open it. Re-running
makes a fresh canvas (``recreate``), which is what you want for a clean demo. The
board then auto-updates as buttons are pressed *within the same agent process* —
note that this one-shot script and the agent are separate processes, so for the
live demo the coordinator opens the board from the agent process's own trigger
(see the task log / README); this CLI is the standalone "mint a board now" path and
a smoke test that the Canvas credentials work.

Requires ``SLACK_USER_TOKEN`` (the user OAuth token with ``canvases:write``) and
``SLACK_BOT_TOKEN`` (carries the WebClient; the user token overrides auth per call)
in ``.env`` or the environment — see ``.env.example``.
"""

import logging
import os
import sys

# Bootstrap logging at module level, before any project import (CLAUDE.md
# "Entry-point scripts call the logging bootstrap at module level").
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv  # noqa: E402
from slack_sdk import WebClient  # noqa: E402

from agent.deps import resolve_user_token  # noqa: E402
from coordinator import coordinator_board  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    """Create a fresh coordinator board canvas and print its id; return an exit code."""
    load_dotenv(dotenv_path=".env", override=False)

    user_token = resolve_user_token(None)
    if not user_token:
        logger.error(
            "SLACK_USER_TOKEN is not set — the coordinator board needs a user token "
            "with canvases:write. Add it to .env (see .env.example) and retry."
        )
        return 1

    client = WebClient(
        base_url=os.environ.get("SLACK_API_URL", "https://slack.com/api"),
        token=os.environ.get("SLACK_BOT_TOKEN"),
    )

    canvas_id = coordinator_board.recreate(client, user_token)
    if canvas_id is None:
        logger.error("Could not create the coordinator board canvas — see the warning above.")
        return 1

    logger.info("Coordinator board canvas created: %s", canvas_id)
    logger.info("Open it from Slack: search your canvases or use the link in the API response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
