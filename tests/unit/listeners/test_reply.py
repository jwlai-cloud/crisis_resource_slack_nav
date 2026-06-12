"""Unit tests for listeners.reply.compose_reply — the single-reply composer.

The whole point of task 005 is "one reply per need". These tests pin that contract
without touching Slack or the LLM: ``run_agent`` is mocked (no network) and the
streamer is a recording fake. We assert that for one need the user sees exactly one
streamed message that carries both the LLM prose and the authoritative sourced match
blocks (no second, source-diverging reply), that the recall context is threaded into
the LLM call, and that channel replies open with a tappable requester mention while
DM replies do not.
"""

from datetime import UTC, datetime

from pytest_mock import MockerFixture

from agent.deps import AgentDeps
from entities import Need, Urgency, deterministic_id
from listeners import reply
from listeners.recall_reply import NeedRecall
from recall.blocks import build_recall_blocks
from recall.models import RecallError, RecallMatch

NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


class _FakeStream:
    """Records appends and the single stop() so we can assert one finalised message."""

    def __init__(self) -> None:
        self.appended: list[str] = []
        self.stop_blocks: list | None = None
        self.stop_calls = 0

    def append(self, *, markdown_text: str) -> None:
        self.appended.append(markdown_text)

    def stop(self, *, blocks=None) -> None:
        self.stop_calls += 1
        self.stop_blocks = blocks


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


def _need_recall(result=None) -> NeedRecall:
    result = [_match()] if result is None else result
    return NeedRecall(
        need=_need(),
        result=result,
        blocks=build_recall_blocks(result),
        llm_context="1 prior offer(s) found... contact=<@U1>",
    )


def _deps() -> AgentDeps:
    return AgentDeps(
        client=object(),
        user_id="U_REQ",
        channel_id="C9",
        thread_ts="1742550600.000100",
        message_ts="1742550600.000200",
    )


def _patch_run_agent(mocker: MockerFixture, output: str = "Here is what I found.") -> object:
    result = mocker.Mock()
    result.output = output
    result.all_messages.return_value = []
    return mocker.patch.object(reply, "run_agent", return_value=result)


def _stream_factory(stream: _FakeStream):
    def _factory():
        return stream

    return _factory


def test_need_produces_exactly_one_reply_with_prose_and_blocks(mocker: MockerFixture) -> None:
    """One need -> one streamed message carrying the prose AND the sourced match blocks."""
    run_agent = _patch_run_agent(mocker, output="Two prior offers look relevant.")
    stream = _FakeStream()
    recall = _need_recall()

    reply.compose_reply(
        "need a generator in Exmouth",
        _deps(),
        say_stream=_stream_factory(stream),
        recall=recall,
        mention_requester=False,
    )

    # Exactly one finalised message — no second, competing reply.
    assert stream.stop_calls == 1
    # That single message contains the LLM prose...
    assert "Two prior offers look relevant." in "".join(stream.appended)
    # ...and the authoritative sourced match blocks plus the feedback buttons.
    block_types = [b.to_dict()["type"] for b in stream.stop_blocks]
    assert "header" in block_types  # recall match header
    assert "context" in block_types  # sourcing line
    assert "context_actions" in block_types  # feedback buttons
    run_agent.assert_called_once()


def test_recall_context_is_threaded_into_the_llm_call(mocker: MockerFixture) -> None:
    """The need's recall context is passed to run_agent so the prose reasons over real data."""
    run_agent = _patch_run_agent(mocker)
    recall = _need_recall()

    reply.compose_reply(
        "need a generator in Exmouth",
        _deps(),
        say_stream=_stream_factory(_FakeStream()),
        recall=recall,
        mention_requester=False,
    )

    assert run_agent.call_args.kwargs["recall_context"] == recall.llm_context


def test_channel_reply_opens_with_requester_mention(mocker: MockerFixture) -> None:
    """A channel reply (mention_requester=True) opens with a tappable <@requester> mention."""
    _patch_run_agent(mocker)
    stream = _FakeStream()

    reply.compose_reply(
        "need a generator",
        _deps(),
        say_stream=_stream_factory(stream),
        recall=_need_recall(),
        mention_requester=True,
    )

    assert stream.appended[0] == "<@U_REQ> "


def test_dm_reply_omits_requester_mention(mocker: MockerFixture) -> None:
    """A DM reply (mention_requester=False) does not prepend a requester mention."""
    _patch_run_agent(mocker)
    stream = _FakeStream()

    reply.compose_reply(
        "need a generator",
        _deps(),
        say_stream=_stream_factory(stream),
        recall=_need_recall(),
        mention_requester=False,
    )

    assert all(not text.startswith("<@U_REQ>") for text in stream.appended)


def test_non_need_reply_streams_prose_with_feedback_only(mocker: MockerFixture) -> None:
    """With no recall (non-need turn) the single reply is prose + feedback, no match blocks."""
    _patch_run_agent(mocker, output="Hello there.")
    stream = _FakeStream()

    reply.compose_reply(
        "hello",
        _deps(),
        say_stream=_stream_factory(stream),
        recall=None,
        mention_requester=False,
    )

    assert stream.stop_calls == 1
    block_types = [b.to_dict()["type"] for b in stream.stop_blocks]
    assert block_types == ["context_actions"]  # feedback only, no recall blocks


def test_degraded_recall_still_one_reply(mocker: MockerFixture) -> None:
    """A degraded recall still composes one reply: prose + the 'unavailable' block."""
    _patch_run_agent(mocker, output="I could not search the workspace right now.")
    stream = _FakeStream()
    recall = _need_recall(result=RecallError(reason="ratelimited"))

    reply.compose_reply(
        "need a generator",
        _deps(),
        say_stream=_stream_factory(stream),
        recall=recall,
        mention_requester=False,
    )

    assert stream.stop_calls == 1
    text = stream.stop_blocks[0].to_dict()["text"]["text"].lower()
    assert "couldn't search the workspace" in text
