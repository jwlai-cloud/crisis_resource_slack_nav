"""Unit tests for listeners.recall_reply — the parse -> recall -> compose wiring.

The recall I/O and the LLM parse are mocked (pytest-mock): we verify that a Need
triggers a sourced Block Kit ``say(...)`` into the thread, that a non-Need posts
nothing, and that a degraded recall result still posts an explicit reply.
"""

from datetime import UTC, datetime

from pytest_mock import MockerFixture

from entities import Need, Urgency, deterministic_id
from listeners import recall_reply
from recall.models import RecallError, RecallMatch

NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)
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
