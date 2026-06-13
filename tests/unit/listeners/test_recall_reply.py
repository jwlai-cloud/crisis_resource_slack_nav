"""Unit tests for listeners.recall_reply — the parse -> route -> recall wiring.

The recall I/O and the LLM parse are mocked (pytest-mock). We verify the routing
contract that powers the single-reply UX (task 005):

* An **offer** is indexed and acked here (its own single ``say``) and routing
  returns ``None`` so the caller treats it as fully handled.
* A **need** posts *nothing* here — it returns a :class:`NeedRecall` carrying the
  ranked result, the composed match blocks, and the LLM context, so the caller
  composes one reply (prose + sourced blocks). This is what kills the old
  structured-reply-plus-separate-LLM-reply split.
* A degraded recall still yields an explicit context + "search unavailable" block.
"""

import re
from datetime import UTC, datetime, timedelta

from pytest_mock import MockerFixture

from entities import Need, Offer, Urgency, deterministic_id
from listeners import recall_reply
from listeners.recall_reply import NeedRecall
from matching.index import OfferIndex
from recall.dismissals import DismissalStore, identity_of
from recall.models import RecallError, RecallMatch

NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)
OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)
EVENT_TS = "1742550600.000200"


def _need() -> Need:
    return Need(
        id=deterministic_id("U_REQ", NEED_TS),
        requester="U_REQ",
        need_type="generator",
        location="Exmouth",
        urgency=Urgency.HIGH,
        household_size=4,
        source_ts=NEED_TS,
    )


def _info_need() -> Need:
    """An information need (road safety): answerable only by official sources (030).

    need_type names the info sought without the place embedded (AC4); the place
    stays in location. ``is_information=True`` is what routes it official-only.
    """
    return Need(
        id=deterministic_id("U_REQ", NEED_TS),
        requester="U_REQ",
        need_type="road safety",
        location="Learmonth",
        urgency=Urgency.MEDIUM,
        household_size=1,
        is_information=True,
        source_ts=NEED_TS,
    )


def _offer() -> Offer:
    return Offer(
        id=deterministic_id("U_OFFERER", OFFER_TS),
        offerer="U_OFFERER",
        resource_type="generator",
        location="Exmouth",
        availability="collect any time today",
        source_ts=OFFER_TS,
    )


def _match() -> RecallMatch:
    return RecallMatch(
        text="spare generator in Exmouth",
        author="Jordan",
        author_id="U1",
        channel="offers",
        channel_id="C1",
        ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
        permalink="https://x/p1",
    )


def _route(say, **overrides):
    """Call route_message with sensible defaults; tests override what they care about."""
    kwargs = {
        "author": "U_REQ",
        "event_ts": EVENT_TS,
        "thread_ts": "1742550600.000100",
        "client": overrides.pop("client", None),
        "user_token": "xoxp-x",
        "say": say,
    }
    kwargs.update(overrides)
    text = kwargs.pop("text")
    return recall_reply.route_message(text, **kwargs)


def test_event_ts_to_utc_parses_string_unix_ts() -> None:
    """A Slack string ts becomes an aware-UTC datetime (sourcing guardrail)."""
    result = recall_reply._event_ts_to_utc(EVENT_TS)

    assert result == datetime.fromtimestamp(1742550600.0002, tz=UTC)
    assert result.tzinfo == UTC


def test_non_need_routes_to_none_and_posts_nothing(mocker: MockerFixture) -> None:
    """A message that's neither offer nor need returns None and posts nothing."""
    mocker.patch.object(recall_reply, "parse_message", return_value="not a need")
    say = mocker.Mock()

    outcome = _route(say, text="thanks!", client=mocker.Mock())

    assert outcome is None
    say.assert_not_called()


def test_need_returns_recall_without_posting(mocker: MockerFixture) -> None:
    """A Need posts NOTHING here — it returns a NeedRecall for the caller to compose.

    This is the heart of the single-reply fix: routing no longer fires its own
    ``say`` for a need, so there is exactly one reply (the caller's prose + blocks).
    """
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    say = mocker.Mock()

    outcome = _route(
        say,
        text="Family of 4 in Exmouth, no power — need a generator",
        client=mocker.Mock(),
    )

    say.assert_not_called()  # no competing structured reply
    assert isinstance(outcome, NeedRecall)
    assert outcome.result == [_match()]
    # The composed blocks are present for the caller to render beneath the prose.
    block_types = [b.to_dict()["type"] for b in outcome.blocks]
    assert "header" in block_types
    assert "context" in block_types  # sourcing line present
    # The LLM context carries the real data (contact, timestamp) for the prose.
    assert "<@U1>" in outcome.llm_context
    assert "spare generator in Exmouth" in outcome.llm_context


# --- Information needs route official-only: no offer-recall, no Connect (task 030) --
#
# An information need ("is the road to X safe?", "where do we evacuate?") is
# answerable ONLY by official sources, so route_message must NOT call recall_offers
# or the offer index, must produce NO recall match blocks, and must yield an
# official-only llm_context. The resource-need path (above + below) is unchanged.


def test_information_need_does_not_recall_offers_or_index(mocker: MockerFixture) -> None:
    """An information need runs NO offer-recall: recall_offers and the index untouched (AC2)."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_info_need())
    recall_spy = mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    index = OfferIndex()
    keyword_spy = mocker.patch.object(index, "keyword_lookup", wraps=index.keyword_lookup)
    mocker.patch.object(recall_reply, "offer_index", index)
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe to drive?", client=mocker.Mock())

    recall_spy.assert_not_called()  # no RTS call
    keyword_spy.assert_not_called()  # no offer-index lookup
    assert isinstance(outcome, NeedRecall)
    assert outcome.result == []  # carries no offer matches


def test_information_need_produces_no_connect_blocks(mocker: MockerFixture) -> None:
    """An information need yields NO match/Connect/Not-relevant action blocks (AC2).

    Task 028 amendment: an info need now renders the relevant OFFICIAL feed items as
    sourced cards (its structured content). Those cards carry NO action buttons — you
    do not "Connect" to a road closure — so the no-Connect guarantee is intact: there
    is still no ``actions`` block. We mock the situation read so the official content
    is deterministic and no real feed/file is touched.
    """
    mocker.patch.object(recall_reply, "parse_message", return_value=_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe to drive?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    # No action buttons anywhere — the official cards are informational only.
    assert all(b.to_dict()["type"] != "actions" for b in outcome.blocks)
    say.assert_not_called()


def test_information_need_context_is_official_only(mocker: MockerFixture) -> None:
    """The info need's llm_context steers the model to official sources, no offers (AC2)."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe to drive?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    context = outcome.llm_context.lower()
    assert "official" in context  # answer from official sources
    assert "do not" in context and "offer" in context  # do not invent workspace offers


def test_resource_need_still_recalls_and_renders_connect(mocker: MockerFixture) -> None:
    """REGRESSION (AC3): a resource need still recalls offers and renders Connect buttons.

    The default _need() is a resource need (is_information False), so the unchanged
    path runs: recall_offers is called and the rendered blocks carry the Connect
    action row.
    """
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    recall_spy = mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    say = mocker.Mock()

    outcome = _route(
        say,
        text="Family of 4 in Exmouth, no power — need a generator",
        client=mocker.Mock(),
    )

    recall_spy.assert_called_once()  # offer-recall ran for the resource need
    assert isinstance(outcome, NeedRecall)
    assert outcome.result == [_match()]
    block_types = [b.to_dict()["type"] for b in outcome.blocks]
    assert "actions" in block_types  # Connect / Not-relevant row rendered


def test_need_with_degraded_recall_returns_unavailable(mocker: MockerFixture) -> None:
    """A RecallError yields an explicit 'search unavailable' block + context — never silent."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=RecallError(reason="no_user_token")),
    )
    say = mocker.Mock()

    outcome = _route(say, text="need a generator in Exmouth", client=mocker.Mock(), user_token=None)

    say.assert_not_called()
    assert isinstance(outcome, NeedRecall)
    assert isinstance(outcome.result, RecallError)
    # The parse summary leads; the degraded 'search unavailable' block follows it.
    section_texts = " ".join(
        block.to_dict().get("text", {}).get("text", "").lower()
        for block in outcome.blocks
        if block.to_dict()["type"] == "section"
    )
    assert "couldn't search the workspace" in section_texts
    assert "unavailable" in outcome.llm_context.lower()


def test_offer_is_indexed_and_acknowledged(mocker: MockerFixture) -> None:
    """An Offer is indexed and acked here (its own single reply); routing returns None."""
    offer = _offer()
    mocker.patch.object(recall_reply, "parse_message", return_value=offer)
    fresh_index = OfferIndex()
    mocker.patch.object(recall_reply, "offer_index", fresh_index)
    recall_spy = mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    say = mocker.Mock()

    outcome = _route(
        say,
        text="I have a spare generator in Exmouth, collect any time today",
        author="U_OFFERER",
        client=mocker.Mock(),
    )

    assert outcome is None  # offer is fully handled here
    recall_spy.assert_not_called()
    assert fresh_index.lookup(offer.id) == offer
    say.assert_called_once()
    blocks = say.call_args.kwargs["blocks"]
    block_types = [b.to_dict()["type"] for b in blocks]
    assert "actions" not in block_types  # acknowledgement is informational only
    assert "context" in block_types  # sourcing line present


def test_need_merges_index_and_rts_hits(mocker: MockerFixture) -> None:
    """A Need consults the index first, then RTS, and both surface in the ranked result."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    fresh_index = OfferIndex()
    fresh_index.add(_offer())
    mocker.patch.object(recall_reply, "offer_index", fresh_index)
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    say = mocker.Mock()

    outcome = _route(
        say,
        text="Family of 4 in Exmouth, no power — need a generator",
        client=mocker.Mock(),
    )

    assert isinstance(outcome, NeedRecall)
    section_texts = " ".join(
        block.to_dict().get("text", {}).get("text", "")
        for block in outcome.blocks
        if block.to_dict()["type"] == "section"
    )
    # The RTS hit snippet and the converted index-hit snippet both appear.
    assert "spare generator in Exmouth" in section_texts  # RTS hit
    assert "collect any time today" in section_texts  # index hit (recomposed)


def test_need_surfaces_index_hits_when_rts_degraded(mocker: MockerFixture) -> None:
    """If RTS is degraded but the index has hits, surface the index hits — not silence."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    fresh_index = OfferIndex()
    fresh_index.add(_offer())
    mocker.patch.object(recall_reply, "offer_index", fresh_index)
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=RecallError(reason="ratelimited")),
    )
    say = mocker.Mock()

    outcome = _route(say, text="need a generator in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    block_types = [b.to_dict()["type"] for b in outcome.blocks]
    assert "header" in block_types  # ranked results, not the degraded block
    section_texts = " ".join(
        block.to_dict().get("text", {}).get("text", "")
        for block in outcome.blocks
        if block.to_dict()["type"] == "section"
    )
    assert "collect any time today" in section_texts


def test_need_filters_out_a_match_this_requester_dismissed(mocker: MockerFixture) -> None:
    """A match the requester previously dismissed is gone from their fresh recall (015)."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    store = DismissalStore()
    store.dismiss("U_REQ", identity_of(_match()))  # U_REQ waved this match off earlier
    mocker.patch.object(recall_reply, "dismissal_store", store)
    say = mocker.Mock()

    outcome = _route(say, text="need a generator in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    assert outcome.result == []  # the dismissed match is filtered before ranking


def test_dismissal_is_per_user_other_requester_still_sees_match(mocker: MockerFixture) -> None:
    """U_A's dismissal does not hide the match from U_B (per-user isolation, 015)."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    store = DismissalStore()
    store.dismiss("U_A", identity_of(_match()))
    mocker.patch.object(recall_reply, "dismissal_store", store)
    say = mocker.Mock()

    outcome = _route(say, text="need a generator in Exmouth", author="U_B", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    assert outcome.result == [_match()]  # U_B never dismissed it -> still surfaced


def test_serialize_recall_context_matches_lists_contact_and_timestamp() -> None:
    """The LLM context lists each match with a tappable contact mention and timestamp."""
    context = recall_reply.serialize_recall_context([_match()])

    assert "<@U1>" in context  # tappable contact for the model to reference
    assert "2026-03-21 09:30 UTC" in context  # real timestamp, not a placeholder
    assert "#offers" in context


def test_serialize_recall_context_error_says_unavailable() -> None:
    """A degraded result serialises to an explicit 'unavailable, do not invent' note."""
    context = recall_reply.serialize_recall_context(RecallError(reason="ratelimited"))

    assert "unavailable" in context.lower()
    assert "do not invent" in context.lower()


def test_serialize_recall_context_empty_says_none_found() -> None:
    """Zero matches serialise to an explicit 'no prior offers found' note."""
    context = recall_reply.serialize_recall_context([])

    assert "no prior offers" in context.lower()
    assert "do not invent" in context.lower()


def _many_matches(count: int, *, text: str = "spare generator in Exmouth") -> list[RecallMatch]:
    """A list of ``count`` distinct RecallMatches (distinct permalinks/text)."""
    return [
        RecallMatch(
            text=f"{text} #{i}",
            author="Jordan",
            author_id="U1",
            channel="offers",
            channel_id="C1",
            ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
            permalink=f"https://x/p{i}",
        )
        for i in range(count)
    ]


def test_serialize_recall_context_caps_at_five_matches() -> None:
    """The LLM context lists at most 5 matches — the same top-N the blocks render (012)."""
    context = recall_reply.serialize_recall_context(_many_matches(8))

    numbered = [line for line in context.splitlines() if re.match(r"^\d+\. contact=", line)]
    assert len(numbered) == 5  # capped, not all 8


def test_serialize_recall_context_appends_plus_n_more_when_truncated() -> None:
    """When matches exceed the cap, a '(+N more found)' line is appended (012)."""
    context = recall_reply.serialize_recall_context(_many_matches(8))

    assert "(+3 more found)" in context  # 8 found - 5 shown = 3


def test_serialize_recall_context_no_plus_n_line_when_within_cap() -> None:
    """At or below the cap there is no '(+N more found)' line."""
    context = recall_reply.serialize_recall_context(_many_matches(3))

    assert "more found" not in context


def test_serialize_recall_context_truncates_long_snippets() -> None:
    """A long match snippet is truncated to ~200 chars with a trailing ellipsis (012)."""
    long_text = "water " * 200  # ~1200 chars, well over the snippet cap
    match = RecallMatch(
        text=long_text,
        author="Jordan",
        author_id="U1",
        channel="offers",
        channel_id="C1",
        ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
        permalink="https://x/p1",
    )

    context = recall_reply.serialize_recall_context([match])

    assert "…" in context  # truncation marker present
    # The rendered snippet is bounded (cap + ellipsis), far short of the raw text.
    assert len(context) < len(long_text)


def test_serialize_recall_context_keeps_short_snippets_intact() -> None:
    """A short snippet is rendered in full, with no ellipsis."""
    context = recall_reply.serialize_recall_context([_match()])

    assert "spare generator in Exmouth" in context
    assert "…" not in context


# --- Cross-source twin collapse (task 016) -----------------------------------
#
# A freshly indexed offer can surface twice in one reply: once from RTS (the
# original channel message) and once from the in-memory index (the same content,
# carrying the offer_id the buttons need). They collapse to ONE match — keep the
# index hit (for its offer_id) but adopt the RTS twin's permalink/channel for
# display. We exercise the collapse through ``_merge_recall_results`` so the
# post-merge wiring is covered too.

INDEX_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)


# The twin texts below sit at/above the 0.85 Jaccard bar on purpose (the index
# recomposition keeps most of the offer's words, so a tightly-phrased offer and its
# recomposed card are genuine near-duplicates): index tokens {generator, collect,
# any, time, today, exmouth} vs RTS tokens {spare, generator, collect, any, time,
# today, exmouth} -> 6/7 ≈ 0.857.
def _index_match(
    *,
    text: str = "generator collect any time today Exmouth",
    author_id: str = "U_OFFERER",
    offer_id: str = "offer-1",
    channel: str = "workspace memory",
    permalink: str = "",
) -> RecallMatch:
    """An index-sourced match: carries an offer_id, no permalink, memory channel."""
    return RecallMatch(
        text=text,
        author=f"<@{author_id}>",
        author_id=author_id,
        channel=channel,
        channel_id="",
        ts=INDEX_TS,
        permalink=permalink,
        offer_id=offer_id,
    )


def _rts_match(
    *,
    text: str = "spare generator collect any time today Exmouth",
    author_id: str = "U_OFFERER",
    channel: str = "offers",
    permalink: str = "https://x/p_twin",
) -> RecallMatch:
    """An RTS-sourced match: human channel + a real permalink, no offer_id."""
    return RecallMatch(
        text=text,
        author="Jordan",
        author_id=author_id,
        channel=channel,
        channel_id="C1",
        ts=INDEX_TS,
        permalink=permalink,
    )


def _seed_index(mocker: MockerFixture, *matches: RecallMatch) -> None:
    """Make ``_merge_recall_results`` see exactly ``matches`` as the index hits."""
    mocker.patch.object(recall_reply, "match_from_offer", side_effect=lambda offer: offer)
    mocker.patch.object(recall_reply.offer_index, "keyword_lookup", return_value=list(matches))


def test_merge_collapses_index_and_rts_twins_into_one(mocker: MockerFixture) -> None:
    """An index hit + a near-duplicate RTS hit from the same author -> one match."""
    index_hit = _index_match()
    rts_hit = _rts_match()
    _seed_index(mocker, index_hit)

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert len(merged) == 1  # the twins collapsed, not rendered twice


def test_merge_twin_keeps_index_offer_id(mocker: MockerFixture) -> None:
    """The surviving match keeps the index hit's offer_id (buttons need it)."""
    _seed_index(mocker, _index_match(offer_id="offer-42"))

    merged = recall_reply._merge_recall_results(_need(), [_rts_match()], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert merged[0].offer_id == "offer-42"


def test_merge_twin_adopts_rts_permalink_and_channel(mocker: MockerFixture) -> None:
    """The index copy lacked a permalink/channel; it adopts the RTS twin's for display."""
    _seed_index(mocker, _index_match(permalink="", channel="workspace memory"))
    rts_hit = _rts_match(permalink="https://x/p_real", channel="offers")

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert merged[0].permalink == "https://x/p_real"  # adopted from the RTS twin
    assert merged[0].channel == "offers"  # adopted from the RTS twin


def test_merge_twin_keeps_index_permalink_when_already_present(
    mocker: MockerFixture,
) -> None:
    """If the index copy already has a permalink/channel, it is not overwritten."""
    _seed_index(mocker, _index_match(permalink="https://x/p_index", channel="own-channel"))
    rts_hit = _rts_match(permalink="https://x/p_twin", channel="offers")

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert merged[0].permalink == "https://x/p_index"  # the index copy's own link wins
    assert merged[0].channel == "own-channel"


def test_merge_keeps_two_different_offers_from_same_author(
    mocker: MockerFixture,
) -> None:
    """Two genuinely DIFFERENT offers from one author both survive (not collapsed).

    These are two distinct posts, so they carry distinct message timestamps — the
    timestamp-identity rule can't fire — and their texts (water vs generator) are
    far below the Jaccard bar, so neither twin rule collapses them.
    """
    index_water = _index_match(text="water — 200 litres in Exmouth", offer_id="offer-water")
    rts_generator = _rts_match(text="I have a spare generator in Exmouth")
    # Distinct messages -> distinct timestamps (not the shared default INDEX_TS).
    rts_generator = rts_generator.model_copy(update={"ts": INDEX_TS + timedelta(hours=2)})
    _seed_index(mocker, index_water)

    # The need keys on 'generator'; widen it so both survive the relevance gate.
    need = _need()
    merged = recall_reply._merge_recall_results(
        Need(
            id=need.id,
            requester=need.requester,
            need_type="generator water",
            location=need.location,
            urgency=need.urgency,
            household_size=need.household_size,
            source_ts=need.source_ts,
        ),
        [rts_generator],
        requester_id="U_REQ",
    )

    assert isinstance(merged, list)
    assert len(merged) == 2  # different resources -> two distinct matches


def test_merge_does_not_collapse_twins_with_different_authors(
    mocker: MockerFixture,
) -> None:
    """Near-identical text from DIFFERENT authors are two offers, not a twin pair."""
    _seed_index(mocker, _index_match(author_id="U_ALICE"))
    rts_hit = _rts_match(author_id="U_BOB")  # same text, different person

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert len(merged) == 2  # two separate people both offered -> both surface


# --- Twin rule ordering: ts-identity PRIMARY, Jaccard SECONDARY (016 amendment) -
#
# The PM amended AC1: an index hit and its RTS twin originate from the SAME Slack
# message, so the offer's source_ts and the RTS match's ts are the same instant.
# Twin ⟺ same author_id AND identical timestamp (PRIMARY); the Jaccard >= 0.85
# same-author check is the SECONDARY fallback (catches a re-posted copy with a
# fresh ts). These tests pin that ordering: the cooker case collapses on ts even
# though its text Jaccard (~0.64) is below the bar, and a fresh-ts pair still
# collapses via Jaccard.

# The live "cooker" case: the structured index recomposition and the loose
# original channel message share the same author + ts but diverge in wording —
# index {gas, cooker, can, drop, off, exmouth, town} vs RTS adds {offering,
# portable, 10kg, rice} → Jaccard ≈ 0.64, BELOW _TWIN_JACCARD_THRESHOLD. Only the
# timestamp-identity rule collapses this pair.
_COOKER_TS = datetime(2026, 3, 21, 14, 5, tzinfo=UTC)
_COOKER_INDEX_TEXT = "gas cooker — can drop off (Exmouth town)"
_COOKER_RTS_TEXT = "Offering: portable gas cooker and 10kg of rice, Exmouth town, can drop off"


def test_twin_collapses_on_ts_identity_even_with_loose_text(mocker: MockerFixture) -> None:
    """Same author + same ts collapse the cooker pair though its Jaccard is < 0.85.

    The structured index card and the loosely-phrased original message are the same
    underlying offer (same Slack message → same author + ts), so they collapse on
    the PRIMARY timestamp-identity rule — even though their text overlap (~0.64) is
    too low for the SECONDARY Jaccard fallback to fire.
    """
    index_hit = _index_match(text=_COOKER_INDEX_TEXT, author_id="U_COOK")
    rts_hit = _rts_match(text=_COOKER_RTS_TEXT, author_id="U_COOK")
    # Both timestamps come from the one message; set them identical.
    index_hit = index_hit.model_copy(update={"ts": _COOKER_TS})
    rts_hit = rts_hit.model_copy(update={"ts": _COOKER_TS})
    _seed_index(mocker, index_hit)

    # Key the need on "cooker" so the collapsed match survives the relevance gate
    # in rank_matches (the default _need() keys on "generator", which the cooker
    # text doesn't mention).
    need = _need()
    cooker_need = need.model_copy(update={"need_type": "gas cooker"})
    merged = recall_reply._merge_recall_results(cooker_need, [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert len(merged) == 1  # collapsed on ts identity, not on text


def test_twin_text_jaccard_below_bar_is_proven_for_cooker_case() -> None:
    """Guard: the cooker pair's text Jaccard really is < 0.85 (so ts did the work)."""
    index_tokens = recall_reply.tokenize(_COOKER_INDEX_TEXT)
    rts_tokens = recall_reply.tokenize(_COOKER_RTS_TEXT)
    jaccard = len(index_tokens & rts_tokens) / len(index_tokens | rts_tokens)

    assert jaccard < recall_reply._TWIN_JACCARD_THRESHOLD


def test_twin_collapses_via_jaccard_fallback_when_ts_differs(mocker: MockerFixture) -> None:
    """Different ts + same author + similar text still collapse via the Jaccard rule.

    A re-posted copy of an offer carries a *fresh* message ts, so the
    timestamp-identity rule can't fire; the SECONDARY Jaccard fallback (>= 0.85
    same-author) still recognises it as a twin and collapses the pair.
    """
    index_hit = _index_match()  # default text, INDEX_TS
    rts_hit = _rts_match()  # near-duplicate text (Jaccard ≈ 0.857), same author
    # Re-posted copy: the RTS twin's ts is a different instant from the index hit.
    rts_hit = rts_hit.model_copy(update={"ts": INDEX_TS + timedelta(hours=3)})
    _seed_index(mocker, index_hit)

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert len(merged) == 1  # collapsed via the Jaccard fallback despite differing ts


def test_no_collapse_for_different_author_even_with_identical_ts(mocker: MockerFixture) -> None:
    """Identical ts + identical text from DIFFERENT authors never collapse.

    Same-author is a hard gate ahead of BOTH twin rules: two people posting the
    exact same thing at the exact same instant are two genuine offers, not a twin.
    """
    index_hit = _index_match(author_id="U_ALICE")
    rts_hit = _rts_match(text=index_hit.text, author_id="U_BOB")  # same text + same INDEX_TS
    _seed_index(mocker, index_hit)

    merged = recall_reply._merge_recall_results(_need(), [rts_hit], requester_id="U_REQ")

    assert isinstance(merged, list)
    assert len(merged) == 2  # different authors -> two distinct offers


def test_serialize_context_reflects_the_deduped_merged_list(
    mocker: MockerFixture,
) -> None:
    """The LLM context (post-merge) lists the collapsed twin exactly once (AC3)."""
    _seed_index(mocker, _index_match())
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_rts_match()])
    )
    say = mocker.Mock()

    outcome = _route(
        say,
        text="Family of 4 in Exmouth, no power — need a generator",
        client=mocker.Mock(),
    )

    assert isinstance(outcome, NeedRecall)
    # One match in the result -> one numbered line in the serialised context.
    numbered = [
        line for line in outcome.llm_context.splitlines() if re.match(r"^\d+\. contact=", line)
    ]
    assert len(numbered) == 1


def test_offer_indexing_refreshes_the_board(mocker: MockerFixture) -> None:
    """Indexing an offer refreshes the coordinator board (it appears under Open)."""
    offer = _offer()
    mocker.patch.object(recall_reply, "parse_message", return_value=offer)
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    update_board = mocker.patch.object(recall_reply, "update_board")
    say = mocker.Mock()

    _route(
        say,
        text="I have a spare generator in Exmouth, collect any time today",
        author="U_OFFERER",
        client=mocker.Mock(),
    )

    update_board.assert_called_once()


# --- Official MCP cards wired into BOTH route branches (task 028) -------------
#
# A need reply now surfaces relevant OFFICIAL feed items as sourced cards beneath
# the workspace matches (resource need) or AS the structured content (info need),
# read best-effort from coordinator.situation.read_situation. We mock the situation
# read where recall_reply imports it so no real feed/file is touched.

from coordinator.situation import SituationFeed, SituationSnapshot  # noqa: E402
from mocks.server import EvacCentre, RoadClosure  # noqa: E402

_OFFICIAL_FETCHED_AT = datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
_OFFICIAL_UPDATED_AT = datetime(2026, 3, 15, 5, 30, tzinfo=UTC)


def _road_feed(*, available: bool = True, detail: str = "") -> SituationFeed:
    if not available:
        return SituationFeed(feed="road_closures", available=False, detail=detail)
    return SituationFeed(
        feed="road_closures",
        available=True,
        fetched_at=_OFFICIAL_FETCHED_AT,
        records=(
            RoadClosure(
                road="Minilya-Exmouth Road",
                segment="Yannarie River crossing",
                status="CLOSED",
                reason="Floodwater over road.",
                detour="No detour available.",
                updated_at=_OFFICIAL_UPDATED_AT,
            ),
        ),
    )


def _evac_feed() -> SituationFeed:
    return SituationFeed(
        feed="evac_centres",
        available=True,
        fetched_at=_OFFICIAL_FETCHED_AT,
        records=(
            EvacCentre(
                name="Exmouth Recreation Centre",
                address="Murat Road, Exmouth WA 6707",
                status="OPEN",
                capacity=250,
                occupancy=168,
                services=["Emergency water point", "Bedding and shelter"],
                updated_at=_OFFICIAL_UPDATED_AT,
            ),
        ),
    )


def _empty_advice() -> SituationFeed:
    return SituationFeed(
        feed="official_advice", available=True, fetched_at=_OFFICIAL_FETCHED_AT, records=()
    )


def _situation(road: SituationFeed, evac: SituationFeed) -> SituationSnapshot:
    return SituationSnapshot(road_closures=road, evac_centres=evac, official_advice=_empty_advice())


def _block_text(blocks: list[object]) -> str:
    """Flatten all visible block text (section/header text + context elements)."""
    parts: list[str] = []
    for block in blocks:
        d = block.to_dict()
        text = d.get("text")
        if isinstance(text, dict) and isinstance(text.get("text"), str):
            parts.append(text["text"])
        for element in d.get("elements", []):
            inner = element.get("text") if isinstance(element, dict) else None
            if isinstance(inner, str):
                parts.append(inner)
    return "\n".join(parts)


def _water_need() -> Need:
    return Need(
        id=deterministic_id("U_REQ", NEED_TS),
        requester="U_REQ",
        need_type="drinking water",
        location="Exmouth",
        urgency=Urgency.HIGH,
        household_size=4,
        source_ts=NEED_TS,
    )


def _water_match() -> RecallMatch:
    """A workspace match that shares a resource word with a water need (survives ranking)."""
    return RecallMatch(
        text="spare drinking water in Exmouth",
        author="Jordan",
        author_id="U1",
        channel="offers",
        channel_id="C1",
        ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
        permalink="https://x/pw",
    )


def _road_info_need() -> Need:
    return Need(
        id=deterministic_id("U_REQ", NEED_TS),
        requester="U_REQ",
        need_type="road safety",
        location="Learmonth",
        urgency=Urgency.MEDIUM,
        household_size=1,
        is_information=True,
        source_ts=NEED_TS,
    )


def test_info_need_renders_official_cards_as_its_content(mocker: MockerFixture) -> None:
    """AC1/AC2: an info need (no workspace matches) gets official cards as its blocks."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_road_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    text = _block_text(outcome.blocks)
    assert "Official information" in text  # the official section header
    assert "Minilya-Exmouth Road" in text  # the relevant closure card
    assert "CLOSED" in text  # the feed's own status, verbatim
    assert "fetched 2026-03-15 06:30 UTC" in text  # absolute-UTC stamp
    # Still official-only: no Connect / Not-relevant action buttons.
    assert all(b.to_dict()["type"] != "actions" for b in outcome.blocks)


def test_info_need_context_notes_official_items_are_cards(mocker: MockerFixture) -> None:
    """AC1: the info-need llm_context tells the model official items are shown as cards."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_road_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    context = outcome.llm_context.lower()
    assert "card" in context  # the model is told official items render as cards below


def test_resource_need_appends_official_cards_beneath_matches(mocker: MockerFixture) -> None:
    """AC1: a resource need keeps its workspace matches AND appends official cards."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_water_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=[_water_match()]),
    )
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Need drinking water in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    block_types = [b.to_dict()["type"] for b in outcome.blocks]
    assert "actions" in block_types  # the workspace match's Connect row is still there
    text = _block_text(outcome.blocks)
    assert "Prior offers from this workspace" in text  # workspace header above
    assert "Official information" in text  # official section beneath
    assert "Exmouth Recreation Centre" in text  # the relevant water-point card


def test_resource_need_official_cards_sit_below_workspace_matches(mocker: MockerFixture) -> None:
    """AC1: the Official information header renders AFTER the workspace matches header."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_water_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=[_water_match()]),
    )
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Need drinking water in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    headers = [
        b.to_dict()["text"]["text"] for b in outcome.blocks if b.to_dict()["type"] == "header"
    ]
    assert "Prior offers from this workspace" in headers
    assert "Official information" in headers
    assert headers.index("Prior offers from this workspace") < headers.index("Official information")


def test_resource_need_with_no_relevant_feed_has_no_official_section(
    mocker: MockerFixture,
) -> None:
    """AC2: a resource need with no relevant feed appends NO official section (no dump)."""
    formula_need = _need().model_copy(update={"need_type": "baby formula"})
    formula_match = _match().model_copy(update={"text": "spare baby formula in Exmouth"})
    mocker.patch.object(recall_reply, "parse_message", return_value=formula_need)
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=[formula_match]),
    )
    mocker.patch.object(
        recall_reply, "read_situation", return_value=_situation(_road_feed(), _evac_feed())
    )
    say = mocker.Mock()

    outcome = _route(say, text="Need baby formula in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    text = _block_text(outcome.blocks)
    assert "Official information" not in text  # no relevant feed -> no section
    assert "Prior offers from this workspace" in text  # the workspace matches still render


def test_info_need_degraded_relevant_feed_renders_unavailable_card(
    mocker: MockerFixture,
) -> None:
    """AC3: a relevant-but-down feed renders an explicit unavailable card, never silent."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_road_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    down = _situation(_road_feed(available=False, detail="Simulated outage."), _evac_feed())
    mocker.patch.object(recall_reply, "read_situation", return_value=down)
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    text = _block_text(outcome.blocks).lower()
    assert "road_closures" in text
    assert "unavailable" in text
    assert "simulated outage" in text


def test_situation_read_failure_does_not_break_the_need_reply(mocker: MockerFixture) -> None:
    """AC6: an unexpected situation-read raise degrades to NO official section, never breaks."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_water_need())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=[_water_match()]),
    )
    mocker.patch.object(recall_reply, "read_situation", side_effect=RuntimeError("feeds exploded"))
    say = mocker.Mock()

    outcome = _route(say, text="Need drinking water in Exmouth", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    text = _block_text(outcome.blocks)
    # The workspace matches still stand; no official section was appended.
    assert "Prior offers from this workspace" in text
    assert "Official information" not in text


def test_info_need_situation_read_failure_yields_no_blocks(mocker: MockerFixture) -> None:
    """AC6: an info need whose situation read fails degrades to empty blocks (prose still leads)."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_road_info_need())
    mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    mocker.patch.object(recall_reply, "offer_index", OfferIndex())
    mocker.patch.object(recall_reply, "read_situation", side_effect=RuntimeError("feeds exploded"))
    say = mocker.Mock()

    outcome = _route(say, text="Is the road to Learmonth safe?", client=mocker.Mock())

    assert isinstance(outcome, NeedRecall)
    assert outcome.blocks == []  # no official cards; the LLM prose still answers
    say.assert_not_called()
