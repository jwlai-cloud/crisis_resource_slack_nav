"""Unit tests for free-text -> typed parsing (agent.parsing).

No live LLM: every test drives ``parse_message`` through
``parsing_agent.override(model=FunctionModel(...))``, where the FunctionModel
deterministically emits one of the union output tools. We assert that
``parse_message`` then wraps that into the right typed entity with the
trust-critical source fields (author, ts, deterministic id) threaded in.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent.parsing import (
    NotACrisisMessage,
    ParsedNeed,
    ParsedOffer,
    parse_message,
    parsing_agent,
)
from entities import Need, Offer, Status, Urgency, deterministic_id

AUTHOR = "U_AUTHOR"
TS = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)
NAIVE_TS = datetime(2026, 3, 14, 9, 30)


def _emit(output_type_name: str, args: dict[str, object]) -> Callable[..., ModelResponse]:
    """Build a FunctionModel callback that emits one named output tool.

    pydantic-ai exposes the union's output tools as ``final_result_<TypeName>``;
    we pick the one whose name contains ``output_type_name`` and return its
    structured args, simulating exactly what a real model would do.
    """

    def callback(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool_name = next(t.name for t in info.output_tools if output_type_name in t.name)
        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return callback


def parse_under_override(text: str, ts: datetime = TS) -> Need | Offer | NotACrisisMessage:
    """Call parse_message with the fixed test author and timestamp."""
    return parse_message(text, AUTHOR, ts)


def test_parse_need_message_returns_typed_need() -> None:
    """A need message becomes a Need with author/ts/id threaded in."""
    callback = _emit(
        ParsedNeed.__name__,
        {
            "need_type": "drinking water",
            "location": "Exmouth",
            "urgency": "critical",
            "household_size": 4,
        },
    )

    with parsing_agent.override(model=FunctionModel(callback)):
        result = parse_under_override("We have no water left, 4 of us in Exmouth")

    assert isinstance(result, Need)
    assert result.requester == AUTHOR
    assert result.source_ts == TS
    assert result.id == deterministic_id(AUTHOR, TS)
    assert result.need_type == "drinking water"
    assert result.urgency is Urgency.CRITICAL
    assert result.household_size == 4
    assert result.status is Status.OPEN


def test_parse_offer_message_returns_typed_offer() -> None:
    """An offer message becomes an Offer with author/ts/id threaded in."""
    callback = _emit(
        ParsedOffer.__name__,
        {
            "resource_type": "generator",
            "location": "Learmonth",
            "availability": "this afternoon, can deliver",
        },
    )

    with parsing_agent.override(model=FunctionModel(callback)):
        result = parse_under_override("I have a spare generator, can drop it off this arvo")

    assert isinstance(result, Offer)
    assert result.offerer == AUTHOR
    assert result.source_ts == TS
    assert result.id == deterministic_id(AUTHOR, TS)
    assert result.resource_type == "generator"
    assert result.availability == "this afternoon, can deliver"
    assert result.status is Status.OPEN


def test_parse_chit_chat_returns_not_a_crisis_message() -> None:
    """A non-need/non-offer message returns the NotACrisisMessage marker."""
    callback = _emit(NotACrisisMessage.__name__, {"reason": "greeting"})

    with parsing_agent.override(model=FunctionModel(callback)):
        result = parse_under_override("morning everyone, hope you're all safe!")

    assert isinstance(result, NotACrisisMessage)
    assert result.reason == "greeting"


# Crisis-relevant information/safety questions classify as Needs (task 029): the
# broadened PARSING_PROMPT should drive the model to emit a ParsedNeed whose
# need_type captures the information sought and whose location is the place it
# concerns, so the existing reply pipeline answers them (refusing to assert
# safety, citing official sources) instead of the passive listener dropping them
# as chatter. Each entry: (message, emitted need_type, emitted location).
INFO_QUESTION_CASES = [
    (
        "Is the road to Learmonth safe to drive?",
        "road safety: Learmonth",
        "Learmonth",
    ),
    (
        "can I drive to Exmouth?",
        "road safety: Exmouth",
        "Exmouth",
    ),
    (
        "where do we evacuate?",
        "where to evacuate",
        "",
    ),
    (
        "where can we get drinking water?",
        "where to get water",
        "",
    ),
]


@pytest.mark.parametrize(
    ("text", "need_type", "location"),
    INFO_QUESTION_CASES,
    ids=[case[0] for case in INFO_QUESTION_CASES],
)
def test_parse_info_question_returns_typed_need(text: str, need_type: str, location: str) -> None:
    """A crisis-relevant information/safety question becomes a Need (task 029)."""
    callback = _emit(
        ParsedNeed.__name__,
        {
            "need_type": need_type,
            "location": location,
            "urgency": "medium",
            "household_size": 1,
        },
    )

    with parsing_agent.override(model=FunctionModel(callback)):
        result = parse_under_override(text)

    assert isinstance(result, Need)
    assert result.requester == AUTHOR
    assert result.source_ts == TS
    assert result.id == deterministic_id(AUTHOR, TS)
    assert result.need_type == need_type
    assert result.location == location
    assert result.urgency is Urgency.MEDIUM
    assert result.household_size == 1
    assert result.status is Status.OPEN


# Social / off-topic messages STAY NotACrisisMessage (task 029): broadening the
# need definition must not re-introduce channel noise (ADR-0004). Greetings,
# thanks, generic status updates, and off-topic questions are still dropped.
# Each entry: (message, emitted reason).
NOISE_CASES = [
    ("thanks everyone, stay safe", "thanks / social"),
    ("anyone know a good podcast?", "off-topic question"),
    ("power's back in town", "coordinator status update"),
    ("good morning all", "greeting"),
]


@pytest.mark.parametrize(
    ("text", "reason"),
    NOISE_CASES,
    ids=[case[0] for case in NOISE_CASES],
)
def test_parse_social_or_off_topic_stays_not_a_crisis(text: str, reason: str) -> None:
    """Greetings/thanks/social/status/off-topic questions stay NotACrisis (task 029)."""
    callback = _emit(NotACrisisMessage.__name__, {"reason": reason})

    with parsing_agent.override(model=FunctionModel(callback)):
        result = parse_under_override(text)

    assert isinstance(result, NotACrisisMessage)
    assert result.reason == reason


def test_parse_need_with_naive_ts_is_rejected() -> None:
    """A naive ts is rejected when wrapping a parsed need (timestamp guardrail)."""
    callback = _emit(
        ParsedNeed.__name__,
        {"need_type": "water", "location": "Exmouth", "urgency": "high"},
    )

    with (
        parsing_agent.override(model=FunctionModel(callback)),
        pytest.raises(ValueError, match="timezone-aware"),
    ):
        parse_under_override("need water in Exmouth", ts=NAIVE_TS)


def test_parse_is_deterministic_for_same_message() -> None:
    """Re-parsing the same (author, ts) yields the same id — idempotent parse."""
    callback = _emit(
        ParsedNeed.__name__,
        {"need_type": "water", "location": "Exmouth", "urgency": "high"},
    )

    with parsing_agent.override(model=FunctionModel(callback)):
        first = parse_under_override("need water in Exmouth")
        second = parse_under_override("need water in Exmouth")

    assert isinstance(first, Need)
    assert isinstance(second, Need)
    assert first.id == second.id
