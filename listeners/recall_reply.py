"""Wire workspace recall + offer indexing into the message flow.

Shared by the message and app-mention listeners. One parse drives two routes:

* **Offer** -> add it to the in-memory index (``matching.index``) and post a short
  *informational* acknowledgement (sourced + timestamped, no action buttons). The
  offer ack is its own single reply; the caller does not compose a need reply for it.
* **Need** -> consult the index *first*, then the Real-Time Search API, merge both
  hit sets and rank the combined list, then hand the result back to the caller as a
  :class:`NeedRecall`. The caller composes **one** reply: the LLM prose (which is
  given the recall result as context so it reasons over the real data, not invented
  placeholders) with the authoritative, sourced match blocks rendered beneath it —
  one message, one answer. This kills the dual-reply UX from task 003 (a structured
  block reply *and* a separate LLM reply that invented diverging sources).

The recall I/O is async (``recall.client.recall_offers``); listeners are sync Bolt
handlers, so we bridge with ``asyncio.run``. Ranking uses ``now`` from the clock here
(the boundary) — the ranking functions themselves stay pure by taking ``now`` as an
argument.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from slack_bolt import Say
from slack_sdk import WebClient
from slack_sdk.models.blocks import Block

from agent.parsing import parse_message
from entities import Need, Offer
from matching import build_offer_ack_blocks, match_from_offer, offer_index
from recall import RecallError, RecallMatch, build_recall_blocks, rank_matches, recall_offers

logger = logging.getLogger(__name__)

_RECALL_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"


@dataclass(frozen=True)
class NeedRecall:
    """The recall outcome for a parsed Need, handed back to the listener.

    The listener composes a single reply from this: ``llm_context`` is threaded
    into the LLM call so the prose reasons over the real data, and ``blocks`` are
    the authoritative, sourced match blocks rendered beneath that prose. Keeping
    the two together in one return value is what guarantees one answer per need
    instead of the old structured-reply-plus-LLM-reply split.
    """

    need: Need
    result: list[RecallMatch] | RecallError
    blocks: list[Block]
    llm_context: str


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


def serialize_recall_context(result: list[RecallMatch] | RecallError) -> str:
    """Serialise a recall result into a compact block for the LLM prompt.

    The model composes its prose *around* this real data, so we hand it the
    trust-critical fields (author, channel, timestamp, permalink, contact mention)
    plus a short text snippet per match — enough to reason and rank over, but the
    on-screen source display stays the authoritative structured blocks. A
    :class:`RecallError` and the empty case are spelled out so the model says so
    plainly instead of inventing matches.
    """
    if isinstance(result, RecallError):
        return (
            "The workspace search was UNAVAILABLE for this turn (a degraded state). "
            "No prior offers could be retrieved. Say so plainly; do not invent matches."
        )
    if not result:
        return (
            "No prior offers were found in the workspace for this need. "
            "Say so plainly; do not invent matches."
        )

    lines = [f"{len(result)} prior offer(s) found, ranked best-fit first:"]
    for index, match in enumerate(result, start=1):
        contact = f"<@{match.author_id}>" if match.author_id else match.author or "unknown"
        when = match.ts.strftime(_RECALL_TIMESTAMP_FORMAT)
        channel = f"#{match.channel}" if match.channel else "unknown channel"
        snippet = match.text.strip().replace("\n", " ")
        lines.append(
            f"{index}. contact={contact} · channel={channel} · when={when} · text={snippet!r}"
        )
    return "\n".join(lines)


def route_message(
    text: str,
    *,
    author: str,
    event_ts: str,
    thread_ts: str,
    client: WebClient,
    user_token: str | None,
    team_id: str | None = None,
    bot_user_id: str | None = None,
    say: Say,
) -> NeedRecall | None:
    """Route a parsed message: index+ack an Offer, or recall context for a Need.

    * **Offer** -> indexed and acknowledged here (its own single reply); returns
      ``None`` so the caller treats it as fully handled.
    * **Need** -> consults the index + RTS, merges and ranks, and returns a
      :class:`NeedRecall` carrying the ranked result, the composed match
      ``blocks``, and the ``llm_context``. The caller composes the single reply.
    * **Neither** -> returns ``None`` (nothing posted).

    Failures inside recall degrade explicitly to a :class:`RecallError` carried in
    the returned :class:`NeedRecall` (the search-unavailable block + a "say so
    plainly" context), never a raise — the listener's own error handling still
    wraps the LLM reply.
    """
    try:
        parsed = parse_message(text, author, _event_ts_to_utc(event_ts))
    except Exception:
        logger.exception("Parse failed; continuing without recall routing")
        return None

    if isinstance(parsed, Offer):
        _post_offer_ack(parsed, thread_ts=thread_ts, say=say)
        return None

    if not isinstance(parsed, Need):
        return None

    need: Need = parsed
    rts_result = asyncio.run(recall_offers(need, client, user_token, team_id, bot_user_id))
    result = _merge_recall_results(need, rts_result)

    logger.info("Recalled context for need: %s in %s", need.need_type, need.location)
    return NeedRecall(
        need=need,
        result=result,
        blocks=build_recall_blocks(result, need=need),
        llm_context=serialize_recall_context(result),
    )
