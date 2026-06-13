"""Open (or re-create) the coordinator board on demand — the demo entry point.

The coordinator board is a Slack Canvas a coordinator reads to watch community
cases move open -> connected -> resolved alongside the audit log of every
human-confirmed action (task 017). The button handlers refresh it automatically on
every Connect / Resolve / Dismiss, but a coordinator needs a way to *summon* it —
on first use, or fresh for the demo. This script is that mechanism.

Run it (the agent process need not be running — this is a standalone one-shot):

    uv run python -m scripts.open_board

It creates a brand-new standalone Canvas owned by the acting user, writes the
current board into it, **persists the canvas id** to the shared
``.slack/board_canvas_id`` file, and **announces** the board link once to
``COORDINATOR_CHANNEL`` (when set). By default it REUSES the existing board; pass
which is what you want for a clean demo.

The persisted id is the bridge across processes (task 018): the live agent's first
board refresh reads that same file and *edits* this canvas instead of minting its
own — so ``make board`` is the single "mint + persist + announce" entry, and the
running agent reuses it. The board then auto-updates as Connect / Resolve / Dismiss
buttons are pressed within the agent process.

Requires ``SLACK_USER_TOKEN`` (the user OAuth token with ``canvases:write``) and
``SLACK_BOT_TOKEN`` (carries the WebClient; the user token overrides auth per call)
in ``.env`` or the environment — see ``.env.example``. ``COORDINATOR_CHANNEL`` is
optional (empty/unset = no announce, mirroring ``CRISIS_CHANNEL``).
"""

import argparse
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
    """Open the coordinator board; return an exit code.

    Default: reuse the existing board (reattach to the persisted canvas, or create
    one if none exists) — so repeated ``make board`` does NOT pile up canvases.
    With ``--fresh``: delete the prior board and mint a clean one (for a fresh demo).
    """
    parser = argparse.ArgumentParser(description="Open or refresh the coordinator board.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete the existing board and create a clean one (default: reuse it).",
    )
    args = parser.parse_args()

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

    team_id = _resolve_team_id(client, user_token)

    if args.fresh:
        canvas_id = coordinator_board.recreate(client, user_token, team_id)
    else:
        canvas_id = coordinator_board.publish(client, user_token, team_id)
    if canvas_id is None:
        logger.error("Could not create the coordinator board canvas — see the warning above.")
        return 1

    logger.info("Coordinator board canvas created + persisted: %s", canvas_id)
    logger.info("Open it from Slack: search your canvases or use the announced link.")
    return 0


def _resolve_team_id(client: WebClient, user_token: str) -> str | None:
    """Best-effort team id for the announce deep link; ``None`` if it can't be read.

    The script has no Bolt context and no bot token (``slack run`` injects that into
    the agent, not here), so it asks Slack via ``auth.test`` authenticated with the
    same user token that mints the canvas. A failure (token issue, API down) just
    means the announce posts the bare canvas id instead of a deep link — never a
    reason to abort the board create.
    """
    try:
        return str(client.auth_test(token=user_token)["team_id"])
    except Exception as exc:
        logger.info("Could not resolve team id for the board link (will post bare id): %s", exc)
        return None


if __name__ == "__main__":
    sys.exit(main())
