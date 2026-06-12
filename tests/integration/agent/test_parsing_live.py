"""Live integration test for parsing (AC #6, optional).

This is the one test that exercises ``parse_message`` against the *real*
configured model — no override, no FunctionModel. It is marked ``live`` and
skips unless a provider key is present, so it never runs in CI without secrets
and never blocks the unit gate. Run it locally with a real key to sanity-check
that the parsing prompt + union output type actually drive a model to classify a
clear need message.
"""

import os
from datetime import UTC, datetime

import pytest

from agent.parsing import NotACrisisMessage
from entities import Need

_HAS_PROVIDER_KEY = any(
    os.environ.get(var)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _HAS_PROVIDER_KEY, reason="no live provider key configured"),
]


def test_live_parse_clear_need_message() -> None:
    """A clear need message parses to a Need against the real model."""
    from agent.parsing import parse_message

    ts = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)
    result = parse_message(
        "We're out of drinking water in Exmouth, there are 4 of us and it's urgent.",
        author="U_LIVE",
        ts=ts,
    )

    assert not isinstance(result, NotACrisisMessage)
    assert isinstance(result, Need)
    assert result.requester == "U_LIVE"
    assert result.source_ts == ts
