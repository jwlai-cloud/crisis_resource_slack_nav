"""Unit tests for listeners.recall_reply — the parse -> recall -> compose wiring.

The recall I/O and the LLM parse are mocked (pytest-mock): we verify that a Need
triggers a sourced Block Kit ``say(...)`` into the thread, that a non-Need posts
nothing, and that a degraded recall result still posts an explicit reply.
"""

from datetime import UTC, datetime

from pytest_mock import MockerFixture

from entities import Need, Offer, Urgency, deterministic_id
from listeners import recall_reply
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


def test_event_ts_to_utc_parses_string_unix_ts() -> None:
    """A Slack string ts becomes an aware-UTC datetime (sourcing guardrail)."""
    result = recall_reply._event_ts_to_utc(EVENT_TS)

    assert result == datetime.fromtimestamp(1742550600.0002, tz=UTC)
    assert result.tzinfo == UTC


def test_non_need_posts_nothing(mocker: MockerFixture) -> None:
    """A message that doesn't parse to a Need posts no recall reply."""
    mocker.patch.object(recall_reply, "parse_message", return_value="not a need")
    say = mocker.Mock()

    posted = recall_reply.maybe_post_recall(
        "thanks!",
        author="U_REQ",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token="xoxp-x",
        say=say,
    )

    assert posted is False
    say.assert_not_called()


def test_need_posts_ranked_sourced_blocks(mocker: MockerFixture) -> None:
    """A Need runs recall + ranking and posts Block Kit into the thread."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    say = mocker.Mock()

    posted = recall_reply.maybe_post_recall(
        "Family of 4 in Exmouth, no power — need a generator",
        author="U_REQ",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token="xoxp-x",
        say=say,
    )

    assert posted is True
    say.assert_called_once()
    kwargs = say.call_args.kwargs
    assert kwargs["thread_ts"] == "1742550600.000100"
    block_types = [b.to_dict()["type"] for b in kwargs["blocks"]]
    assert "header" in block_types
    assert "context" in block_types  # sourcing line present


def test_need_with_degraded_recall_posts_unavailable_block(mocker: MockerFixture) -> None:
    """A RecallError still posts an explicit 'search unavailable' reply — never silent."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    mocker.patch.object(
        recall_reply,
        "recall_offers",
        new=mocker.AsyncMock(return_value=RecallError(reason="no_user_token")),
    )
    say = mocker.Mock()

    posted = recall_reply.maybe_post_recall(
        "need a generator in Exmouth",
        author="U_REQ",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token=None,
        say=say,
    )

    assert posted is True
    blocks = say.call_args.kwargs["blocks"]
    text = blocks[0].to_dict()["text"]["text"].lower()
    assert "couldn't search the workspace" in text


def test_offer_is_indexed_and_acknowledged(mocker: MockerFixture) -> None:
    """An Offer message is indexed and acknowledged with sourced, action-free blocks."""
    offer = _offer()
    mocker.patch.object(recall_reply, "parse_message", return_value=offer)
    fresh_index = OfferIndex()
    mocker.patch.object(recall_reply, "offer_index", fresh_index)
    # recall_offers must not run for an offer route.
    recall_spy = mocker.patch.object(recall_reply, "recall_offers", new=mocker.AsyncMock())
    say = mocker.Mock()

    posted = recall_reply.maybe_post_recall(
        "I have a spare generator in Exmouth, collect any time today",
        author="U_OFFERER",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token="xoxp-x",
        say=say,
    )

    assert posted is True
    recall_spy.assert_not_called()
    assert fresh_index.lookup(offer.id) == offer
    say.assert_called_once()
    blocks = say.call_args.kwargs["blocks"]
    block_types = [b.to_dict()["type"] for b in blocks]
    assert "actions" not in block_types  # acknowledgement is informational only
    assert "context" in block_types  # sourcing line present


def test_need_merges_index_and_rts_hits(mocker: MockerFixture) -> None:
    """A Need consults the index first, then RTS, and both surface in the ranked reply."""
    mocker.patch.object(recall_reply, "parse_message", return_value=_need())
    # Seed the index with a relevant offer so it must appear alongside the RTS hit.
    fresh_index = OfferIndex()
    fresh_index.add(_offer())
    mocker.patch.object(recall_reply, "offer_index", fresh_index)
    mocker.patch.object(
        recall_reply, "recall_offers", new=mocker.AsyncMock(return_value=[_match()])
    )
    say = mocker.Mock()

    posted = recall_reply.maybe_post_recall(
        "Family of 4 in Exmouth, no power — need a generator",
        author="U_REQ",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token="xoxp-x",
        say=say,
    )

    assert posted is True
    blocks = say.call_args.kwargs["blocks"]
    section_texts = " ".join(
        block.to_dict()["text"]["text"] for block in blocks if block.to_dict()["type"] == "section"
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

    posted = recall_reply.maybe_post_recall(
        "need a generator in Exmouth",
        author="U_REQ",
        event_ts=EVENT_TS,
        thread_ts="1742550600.000100",
        client=mocker.Mock(),
        user_token="xoxp-x",
        say=say,
    )

    assert posted is True
    blocks = say.call_args.kwargs["blocks"]
    block_types = [b.to_dict()["type"] for b in blocks]
    assert "header" in block_types  # ranked results, not the degraded block
    section_texts = " ".join(
        block.to_dict()["text"]["text"] for block in blocks if block.to_dict()["type"] == "section"
    )
    assert "collect any time today" in section_texts
