"""Post the coordinator board's link once, to a designated channel — discoverability.

The board is a standalone Slack Canvas (ADR-0005). A coordinator who is not in the
process that minted it has no way to *find* it. This module closes that gap (task
018): when a board canvas is **created** (not on every edit), its link is posted
once to the channel named by ``COORDINATOR_CHANNEL`` so a coordinator can open it.

``COORDINATOR_CHANNEL`` mirrors ``CRISIS_CHANNEL`` (see
:mod:`listeners.channel_gate`, ADR-0004): a Slack channel id read from the
environment at call time; empty or unset means the feature is **off** and nothing
is posted. One channel only — widening is a future fork with its own ADR, not a
config list.

**Idempotent by construction.** The announce hook fires only on canvas *create*,
so a board's link is posted exactly once per canvas, never re-posted on the
many edits that follow each button action.

**Best-effort, never raises.** A post failure (channel not found, missing bot
membership, API outage) is logged and swallowed — discoverability is a
convenience layered on top of the board, and a failed announce must never break
the create it is hooked into (ADR-0005's degraded-state posture).
"""

import logging
import os

from slack_sdk import WebClient

COORDINATOR_CHANNEL_ENV = "COORDINATOR_CHANNEL"

logger = logging.getLogger(__name__)


def coordinator_channel_id() -> str | None:
    """Return the configured coordinator channel id, or ``None`` when the feature is off.

    Whitespace is trimmed; an empty (or whitespace-only) value reads as off — the
    same contract as :func:`listeners.channel_gate.designated_channel_id`.
    """
    raw = os.environ.get(COORDINATOR_CHANNEL_ENV, "").strip()
    return raw or None


def canvas_link(*, canvas_id: str, team_id: str | None) -> str | None:
    """Construct the standalone-canvas docs URL, or ``None`` when no team id is known.

    Slack renders a standalone canvas at ``https://slack.com/docs/{team}/{canvas}``;
    that needs the team id, which the agent has on the Bolt context but the
    one-shot script may not. Without it we return ``None`` and the caller falls
    back to posting the bare canvas id (still discoverable, just not a deep link).
    """
    if not team_id:
        return None
    return f"https://slack.com/docs/{team_id}/{canvas_id}"


def announce_board(
    client: WebClient, *, canvas_id: str, team_id: str | None, user_token: str | None = None
) -> None:
    """Post the board link once to ``COORDINATOR_CHANNEL``; a no-op when it is off.

    Called only on canvas create (idempotent — one post per canvas). Constructs a
    deep link when the team id is known, otherwise names the canvas id so a
    coordinator can still find the board. Best-effort: any failure is logged and
    swallowed, never raised.

    Posts with the per-call ``user_token`` override when given — the standalone
    ``make board`` process carries no bot token (``slack run`` injects that into the
    agent, not the script), so the announce must authenticate with the same user
    token that minted the canvas. The user has ``chat:write``, so it posts as the
    coordinator. When ``user_token`` is omitted the client's own token is used.
    """
    channel = coordinator_channel_id()
    if channel is None:
        logger.info("Coordinator board announce skipped: %s not set", COORDINATOR_CHANNEL_ENV)
        return

    link = canvas_link(canvas_id=canvas_id, team_id=team_id)
    if link is not None:
        text = (
            ":pushpin: The Community Cases board is open — "
            f"<{link}|open the coordinator board> (canvas {canvas_id}). "
            "It updates as matches are connected, resolved, or dismissed."
        )
    else:
        text = (
            ":pushpin: The Community Cases board is open (canvas "
            f"`{canvas_id}`). Find it in your canvases — it updates as matches "
            "are connected, resolved, or dismissed."
        )

    try:
        kwargs = {"token": user_token} if user_token else {}
        # Suppress both unfurls: the slack.com/docs canvas URL otherwise renders a
        # generic "Slack Login" card (the unfurl crawler is unauthenticated and
        # cannot see the canvas). The deep link still opens for a member who clicks
        # it; we just stop the ugly preview (task 023).
        client.chat_postMessage(
            channel=channel,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
            **kwargs,
        )
        logger.info("Announced coordinator board canvas %s to %s", canvas_id, channel)
    except Exception as exc:
        logger.warning("Coordinator board announce failed (board unaffected): %s", exc)
