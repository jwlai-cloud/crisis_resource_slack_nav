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
from datetime import UTC, datetime, timedelta

from slack_bolt import Say
from slack_sdk import WebClient
from slack_sdk.models.blocks import Block

from agent.parsing import parse_message
from entities import Need, Offer
from matching import build_offer_ack_blocks, match_from_offer, offer_index
from recall import (
    RecallError,
    RecallMatch,
    build_recall_blocks,
    rank_matches,
    recall_offers,
    tokenize,
)
from recall.dismissals import dismissal_store

logger = logging.getLogger(__name__)

_RECALL_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"

# The LLM context mirrors the on-screen blocks: both show the top 5 matches. Sending
# the model the full ranked list with untruncated text (task 012 addendum) wastes
# tokens it never renders, so we cap the serialised context to the same 5.
_CONTEXT_MAX_MATCHES = 5

# Each match's snippet is truncated to roughly this many characters in the LLM
# context — enough to reason and rank over, without paying for a wall of text the
# model only summarises. Truncated snippets get a trailing ellipsis.
_CONTEXT_SNIPPET_MAX = 200

# Jaccard similarity at/above which an index hit and an RTS hit FROM THE SAME
# AUTHOR are treated as cross-source twins (task 016 amendment, the SECONDARY
# rule). This is the *fallback* test, behind the timestamp-identity rule below:
# it catches a re-posted *copy* of the offer (a second message with similar text
# but a fresh ts, where the deterministic timestamp gate can't fire). High on
# purpose, and the same value the echo filter uses (``recall.client``) — it
# targets "same offer rendered twice" without collapsing two genuinely different
# offers that merely share resource words. Reuses ``tokenize`` so "overlap" means
# the same thing here as in ranking, the index, and the echo filter.
_TWIN_JACCARD_THRESHOLD = 0.85

# Sub-second tolerance for the timestamp-identity twin rule (task 016 amendment,
# the PRIMARY rule). An index hit and its RTS twin originate from the SAME Slack
# message, so the offer's ``source_ts`` (set in ``route_message`` via
# ``_event_ts_to_utc`` → ``parse_message`` → ``Offer.source_ts``) and the RTS
# match's ``ts`` (set in ``recall.models.match_from_message``) are both
# ``datetime.fromtimestamp(float(<same message ts>), tz=UTC)``.
#
# Verified empirically (see the task log amendment): at Slack-timestamp magnitude
# (~1.74e9 s) the float64 ULP is ~0.24 µs, and ``fromtimestamp`` rounds to the
# nearest microsecond — so EVERY string spelling of one ``SSSS.NNNNNN`` value
# (canonical, trailing-zeros trimmed, extra trailing zeros) parses to the IDENTICAL
# microsecond. The worst-case delta across all reformattings is 0 µs, so exact
# equality already holds. We still allow a 1 ms window because RTS is an external
# boundary whose exact ts serialisation we don't own — this is defence in depth
# against a future reformatting, NOT a correctness crutch (the measured need is 0).
_TWIN_TS_TOLERANCE = timedelta(milliseconds=1)


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
    requester_id: str,
) -> list[RecallMatch] | RecallError:
    """Merge index hits with the RTS result into one ranked list (or a RecallError).

    Index hits (converted to :class:`RecallMatch` so both sources share one shape)
    are *always* available — the index is local. The RTS result may be a degraded
    :class:`RecallError`; when it is, we still surface the index hits if there are
    any (a partial, honestly-sourced answer beats going silent), and only fall
    through to the degraded reply when the index is empty too. When RTS succeeds,
    both sets are concatenated and ranked together so they share one ordering and
    relevance gate.

    Before ranking, matches this ``requester_id`` previously dismissed via "Not
    relevant" are filtered out (task 015): a dismissal is a per-user "not this one"
    signal, so a fresh need never resurfaces a match the same requester already
    waved off. The filter is per-user — another requester still sees it.

    When RTS succeeds, the concatenated list is also de-twinned (task 016): a
    freshly indexed offer can surface both from the local index (carrying the
    offer_id the buttons need) and from RTS (the original channel message), and
    rendering it twice is confusing. ``_collapse_cross_source_twins`` folds each
    such pair into one match before the dismissal filter and ranking run.
    """
    index_matches = [match_from_offer(offer) for offer in offer_index.keyword_lookup(need)]

    if isinstance(rts_result, RecallError):
        if index_matches:
            kept = dismissal_store.filter_dismissed(requester_id, index_matches)
            return rank_matches(need, kept, datetime.now(UTC))
        return rts_result

    deduped = _collapse_cross_source_twins(index_matches, rts_result)
    combined = dismissal_store.filter_dismissed(requester_id, deduped)
    return rank_matches(need, combined, datetime.now(UTC))


def _is_cross_source_twin(index_match: RecallMatch, rts_match: RecallMatch) -> bool:
    """True if these two matches are the same underlying offer from two sources.

    Same author is a hard gate either way: two near-identical posts from two
    *different* people are two genuine offers, never a twin. Past the gate, the
    task 016 amendment orders two tests deterministic-first (the PM spec change
    replacing the original Jaccard-only rule):

    1. **Timestamp identity (PRIMARY, deterministic).** An index hit and its RTS
       twin come from the SAME Slack message, so the offer's ``source_ts`` and the
       RTS match's ``ts`` are the same instant parsed through the same
       ``fromtimestamp(float(...), tz=UTC)`` path. Identical (aware-UTC)
       timestamps from the same author ⟹ twin — regardless of how the index
       recomposes the offer's wording. This collapses the "live cooker" case where
       the structured index text and the loose original message diverge too far for
       Jaccard. The comparison allows :data:`_TWIN_TS_TOLERANCE`; the measured need
       is 0 (see the constant's note) — it is defence in depth at the RTS boundary.
    2. **Jaccard similarity (SECONDARY, fallback).** When the timestamps differ
       (e.g. a re-posted *copy* of the offer carries a fresh message ts), text
       overlap at/above :data:`_TWIN_JACCARD_THRESHOLD` still collapses the pair.
       Reuses the shared ``tokenize`` (the same overlap notion as ranking, the
       index, and the echo filter).
    """
    if not index_match.author_id or index_match.author_id != rts_match.author_id:
        return False
    if abs(index_match.ts - rts_match.ts) <= _TWIN_TS_TOLERANCE:
        return True
    index_tokens = tokenize(index_match.text)
    rts_tokens = tokenize(rts_match.text)
    union = index_tokens | rts_tokens
    if not union:
        return False
    jaccard = len(index_tokens & rts_tokens) / len(union)
    return jaccard >= _TWIN_JACCARD_THRESHOLD


def _merge_twin(index_match: RecallMatch, rts_match: RecallMatch) -> RecallMatch:
    """Fold a twin pair into ONE match: keep the index hit, adopt RTS display fields.

    The index hit is kept because it carries the ``offer_id`` the action buttons
    need for status transitions. The RTS twin contributes the display fields the
    index copy lacks — its ``permalink`` (an index hit links to no single message)
    and its real ``channel`` (the index copy carries the "workspace memory"
    provenance label, not a Slack channel). Fields the index copy already has are
    left untouched — we only fill the gaps. ``RecallMatch`` is a Pydantic model, so
    we build the merged value with ``model_copy`` rather than mutating in place.
    """
    update: dict[str, str] = {}
    if not index_match.permalink and rts_match.permalink:
        update["permalink"] = rts_match.permalink
        update["channel"] = rts_match.channel
        update["channel_id"] = rts_match.channel_id
    if not update:
        return index_match
    return index_match.model_copy(update=update)


def _collapse_cross_source_twins(
    index_matches: list[RecallMatch], rts_matches: list[RecallMatch]
) -> list[RecallMatch]:
    """Concatenate both sources, collapsing each index/RTS twin pair to one match.

    Order is preserved (index hits first, then the RTS hits that were not twinned),
    so the downstream ranking — not this step — owns the final ordering. Each RTS
    hit collapses against at most one index hit (the first match), and each index
    hit absorbs at most one RTS twin, so two distinct RTS hits never both fold into
    the same index hit.
    """
    merged: list[RecallMatch] = []
    consumed_rts: set[int] = set()
    for index_match in index_matches:
        twin_pos = next(
            (
                pos
                for pos, rts_match in enumerate(rts_matches)
                if pos not in consumed_rts and _is_cross_source_twin(index_match, rts_match)
            ),
            None,
        )
        if twin_pos is None:
            merged.append(index_match)
        else:
            consumed_rts.add(twin_pos)
            merged.append(_merge_twin(index_match, rts_matches[twin_pos]))
    merged.extend(rts_match for pos, rts_match in enumerate(rts_matches) if pos not in consumed_rts)
    return merged


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

    # Cap at the same top-N the blocks render (task 012 addendum): the model never
    # surfaces matches beyond what is on screen, so sending them only burns tokens.
    shown = result[:_CONTEXT_MAX_MATCHES]
    lines = [f"{len(shown)} prior offer(s) shown, ranked best-fit first:"]
    for index, match in enumerate(shown, start=1):
        contact = f"<@{match.author_id}>" if match.author_id else match.author or "unknown"
        when = match.ts.strftime(_RECALL_TIMESTAMP_FORMAT)
        channel = f"#{match.channel}" if match.channel else "unknown channel"
        snippet = _truncate_snippet(match.text.strip().replace("\n", " "))
        lines.append(
            f"{index}. contact={contact} · channel={channel} · when={when} · text={snippet!r}"
        )
    extra = len(result) - len(shown)
    if extra > 0:
        lines.append(f"(+{extra} more found)")
    return "\n".join(lines)


def _truncate_snippet(text: str) -> str:
    """Trim a match snippet to ``_CONTEXT_SNIPPET_MAX`` chars, marking truncation.

    Keeps the LLM context cheap (task 012 addendum) without dropping the snippet
    entirely: a truncated snippet ends with an ellipsis so the model knows it is a
    head, not the full text. Short snippets pass through unchanged.
    """
    if len(text) <= _CONTEXT_SNIPPET_MAX:
        return text
    return text[:_CONTEXT_SNIPPET_MAX].rstrip() + "…"


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
    rts_result = asyncio.run(
        recall_offers(need, client, user_token, team_id, bot_user_id, request_text=text)
    )
    result = _merge_recall_results(need, rts_result, requester_id=author)

    logger.info("Recalled context for need: %s in %s", need.need_type, need.location)
    return NeedRecall(
        need=need,
        result=result,
        blocks=build_recall_blocks(result, need=need),
        llm_context=serialize_recall_context(result),
    )
