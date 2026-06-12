"""Wire workspace recall into the message flow — parse -> recall -> rank -> compose.

Shared by the message and app-mention listeners. When an incoming message parses
to a :class:`~entities.Need`, this runs the RTS recall step and posts a sourced,
ranked Block Kit reply (prior offers, or an explicit degraded/empty state) into
the thread *before* the normal LLM reply streams. This keeps the listener changes
small: each listener calls :func:`maybe_post_recall` once and is otherwise
unchanged.

The recall I/O is async (``recall.client.recall_offers``); listeners are sync
Bolt handlers, so we bridge with ``asyncio.run``. Ranking uses ``now`` from the
clock here (the boundary) — the ranking functions themselves stay pure by taking
``now`` as an argument.
"""

import asyncio
import logging
from datetime import UTC, datetime

from slack_bolt import Say
from slack_sdk import WebClient

from agent.parsing import parse_message
from entities import Need
from recall import build_recall_blocks, rank_matches, recall_offers

logger = logging.getLogger(__name__)


def _event_ts_to_utc(ts: str) -> datetime:
    """Convert a Slack event ``ts`` (string Unix seconds) to an aware-UTC datetime."""
    return datetime.fromtimestamp(float(ts), tz=UTC)


def maybe_post_recall(
    text: str,
    *,
    author: str,
    event_ts: str,
    thread_ts: str,
    client: WebClient,
    user_token: str | None,
    say: Say,
) -> bool:
    """If ``text`` is a Need, post the ranked, sourced recall reply; return whether posted.

    Returns ``True`` when a Need was recognised and a recall reply was posted (so
    callers can log it / decide how the LLM reply should follow), ``False`` when
    the message was not a Need. Failures inside recall degrade explicitly to a
    composed "search unavailable" block rather than raising — the listener's own
    error handling still wraps the LLM reply.
    """
    parsed = parse_message(text, author, _event_ts_to_utc(event_ts))
    if not isinstance(parsed, Need):
        return False

    need: Need = parsed
    result = asyncio.run(recall_offers(need, client, user_token))
    if isinstance(result, list):
        result = rank_matches(need, result, datetime.now(UTC))

    blocks = build_recall_blocks(result)
    say(blocks=blocks, text="Prior offers from this workspace", thread_ts=thread_ts)
    logger.info("Posted recall reply for need: %s in %s", need.need_type, need.location)
    return True
