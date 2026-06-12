"""Wire workspace recall + offer indexing into the message flow.

Shared by the message and app-mention listeners. One parse drives two routes:

* **Offer** -> add it to the in-memory index (``matching.index``) and post a short
  *informational* acknowledgement (sourced + timestamped, no action buttons).
* **Need** -> consult the index *first*, then the Real-Time Search API, merge both
  hit sets, rank the combined list, and post a sourced Block Kit reply (prior
  offers, or an explicit degraded/empty state) into the thread *before* the LLM
  reply streams.

This keeps the listener changes small: each listener calls
:func:`maybe_post_recall` once and is otherwise unchanged. The recall I/O is async
(``recall.client.recall_offers``); listeners are sync Bolt handlers, so we bridge
with ``asyncio.run``. Ranking uses ``now`` from the clock here (the boundary) —
the ranking functions themselves stay pure by taking ``now`` as an argument.
"""

import asyncio
import logging
from datetime import UTC, datetime

from slack_bolt import Say
from slack_sdk import WebClient

from agent.parsing import parse_message
from entities import Need, Offer
from matching import build_offer_ack_blocks, match_from_offer, offer_index
from recall import RecallError, RecallMatch, build_recall_blocks, rank_matches, recall_offers

logger = logging.getLogger(__name__)


def _event_ts_to_utc(ts: str) -> datetime:
    """Convert a Slack event ``ts`` (string Unix seconds) to an aware-UTC datetime."""
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _post_offer_ack(offer: Offer, *, thread_ts: str, say: Say) -> None:
    """Index a parsed offer and post its informational, sourced acknowledgement."""
    offer_index.add(offer)
    blocks = build_offer_ack_blocks(offer)
    say(blocks=blocks, text="Logged your offer", thread_ts=thread_ts)
    logger.info("Acknowledged offer: %s in %s", offer.resource_type, offer.location)


def _merge_recall_results(
    need: Need,
    rts_result: list[RecallMatch] | RecallError,
) -> list[RecallMatch] | RecallError:
    """Merge index hits with the RTS result into one ranked list (or a RecallError).

    Index hits (converted to :class:`RecallMatch` so both sources share one shape)
    are *always* available — the index is local. The RTS result may be a degraded
    :class:`RecallError`; when it is, we still surface the index hits if there are
    any (a partial, honestly-sourced answer beats going silent), and only fall
    through to the degraded reply when the index is empty too. When RTS succeeds,
    both sets are concatenated and ranked together so they share one ordering and
    relevance gate.
    """
    index_matches = [match_from_offer(offer) for offer in offer_index.keyword_lookup(need)]

    if isinstance(rts_result, RecallError):
        if index_matches:
            return rank_matches(need, index_matches, datetime.now(UTC))
        return rts_result

    combined = index_matches + rts_result
    return rank_matches(need, combined, datetime.now(UTC))


def maybe_post_recall(
    text: str,
    *,
    author: str,
    event_ts: str,
    thread_ts: str,
    client: WebClient,
    user_token: str | None,
    team_id: str | None = None,
    say: Say,
) -> bool:
    """Route a parsed message: index+ack an Offer, or post recall for a Need.

    Returns ``True`` when the message was recognised as an Offer or a Need and a
    reply was posted (so callers can log it / decide how the LLM reply should
    follow), ``False`` when the message was neither. Failures inside recall
    degrade explicitly to a composed "search unavailable" block rather than
    raising — the listener's own error handling still wraps the LLM reply.
    """
    parsed = parse_message(text, author, _event_ts_to_utc(event_ts))

    if isinstance(parsed, Offer):
        _post_offer_ack(parsed, thread_ts=thread_ts, say=say)
        return True

    if not isinstance(parsed, Need):
        return False

    need: Need = parsed
    rts_result = asyncio.run(recall_offers(need, client, user_token, team_id))
    result = _merge_recall_results(need, rts_result)

    blocks = build_recall_blocks(result)
    say(blocks=blocks, text="Prior offers from this workspace", thread_ts=thread_ts)
    logger.info("Posted recall reply for need: %s in %s", need.need_type, need.location)
    return True
