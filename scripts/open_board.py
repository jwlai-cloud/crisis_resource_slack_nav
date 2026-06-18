"""Open (or re-create) the coordinator board on demand — the demo entry point.

The coordinator board is a Slack Canvas a coordinator reads to watch community
cases move open -> connected -> resolved alongside the audit log of every
human-confirmed action (task 017). The button handlers refresh it automatically on
every Connect / Resolve / Dismiss, but a coordinator needs a way to *summon* it —
on first use, or fresh for the demo. This script is that mechanism.

Run it (the agent process need not be running — this is a standalone one-shot):

    uv run python -m scripts.open_board

It find-or-creates the **channel canvas** of ``CRISIS_CHANNEL`` (a permanent,
*titled* "Community Cases" top-bar tab — task 025/027, ADR-0005) owned by the acting
user, writes the current board into it, and **persists the canvas id** to the shared
``.slack/board_canvas_id`` file. **Reuse, never delete** (task 027): both the default
and ``--fresh`` reattach to the existing tab (persisted id, else the channel's
existing canvas tab, else create titled) and full-replace its content — neither ever
deletes a canvas, because a delete leaves an un-removable tombstone tab. With an
empty index that full-replace already renders the clean empty board, so ``--fresh``
is just a "force a clean re-render" alias; it adds no new tab. The board does NOT
announce on create any more — the titled tab IS the discovery mechanism, so
``COORDINATOR_CHANNEL`` is no longer used by the board.

The persisted id is the bridge across processes: the live agent's first board
refresh reads that same file and *edits* this canvas instead of minting its own — so
``make board`` is the single "create-or-reuse + persist" entry, and the running
agent reuses it. The board then auto-updates as Connect / Resolve / Dismiss buttons
are pressed within the agent process.

Requires ``SLACK_USER_TOKEN`` (the user OAuth token with ``canvases:write``) and
``SLACK_BOT_TOKEN`` (carries the WebClient; the user token overrides auth per call)
in ``.env`` or the environment — see ``.env.example``.
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

    Both modes REUSE the channel's one titled "Community Cases" tab and full-replace
    its content — neither deletes a canvas (task 027: a delete leaves an un-removable
    tombstone tab). Default reattaches (persisted id, else the channel's canvas tab,
    else create titled). ``--fresh`` is a "force a clean re-render" alias: with an
    empty index the full-replace already renders the empty board, so a fresh demo
    start needs no new tab.
    """
    parser = argparse.ArgumentParser(description="Open or refresh the coordinator board.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Force a clean re-render of the existing board (reuse-not-delete; no new tab).",
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

    team_id, team_url = _resolve_team(client, user_token)

    if args.fresh:
        canvas_id = coordinator_board.recreate(client, user_token, team_id, team_url)
    else:
        canvas_id = coordinator_board.publish(client, user_token, team_id, team_url)
    if canvas_id is None:
        logger.error("Could not create the coordinator board canvas — see the warning above.")
        return 1

    logger.info(
        "Coordinator board channel canvas ready (reused-or-created) + persisted: %s", canvas_id
    )
    logger.info("Open it from Slack: the Community Cases tab in the top bar of CRISIS_CHANNEL.")
    return 0


def _resolve_team(client: WebClient, user_token: str) -> tuple[str | None, str | None]:
    """Best-effort (team id, workspace url) for the board link; ``(None, None)`` on failure.

    The script has no Bolt context and no bot token (``slack run`` injects that into
    the agent, not here), so it asks Slack via ``auth.test`` authenticated with the
    same user token that mints the canvas. The ``url`` field is the workspace domain
    (e.g. ``https://acme.enterprise.slack.com/``); paired with the team id it builds
    the in-app canvas link (opens the canvas inside Slack rather than a browser tab).
    A failure (token issue, API down) just means the link falls back to the
    slack.com form / bare id — never a reason to abort the board open.
    """
    try:
        resp = client.auth_test(token=user_token)
        return str(resp["team_id"]), (resp.get("url") or None)
    except Exception as exc:
        logger.info("Could not resolve team for the board link (will use fallback): %s", exc)
        return None, None


if __name__ == "__main__":
    sys.exit(main())
