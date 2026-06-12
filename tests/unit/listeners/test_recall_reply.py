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

from datetime import UTC, datetime

from pytest_mock import MockerFixture

from entities import Need, Offer, Urgency, deterministic_id
from listeners import recall_reply
from listeners.recall_reply import NeedRecall
from matching.index import OfferIndex
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
    text = outcome.blocks[0].to_dict()["text"]["text"].lower()
    assert "couldn't search the workspace" in text
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
        block.to_dict()["text"]["text"]
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
        block.to_dict()["text"]["text"]
        for block in outcome.blocks
        if block.to_dict()["type"] == "section"
    )
    assert "collect any time today" in section_texts


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
