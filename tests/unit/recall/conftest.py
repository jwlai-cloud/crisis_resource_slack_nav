"""Shared fixtures for recall unit tests.

These tests never touch real Slack or the network: the RTS client tests mock the
``WebClient`` via ``pytest-mock`` (``mocker``). Builders are exposed as fixtures
(``make_need`` / ``make_match``) so test modules don't import from conftest
directly — the recall test dir has no ``__init__.py`` (pythonpath collection),
so a relative ``from .conftest import ...`` would fail. The fixed ``now`` /
``need_ts`` fixtures keep recency math deterministic.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from entities import Need, Urgency, deterministic_id
from recall.models import RecallMatch

# A fixed "now" and a fixed need timestamp so recency math is deterministic.
NOW = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    """The fixed reference instant ranking is scored against."""
    return NOW


@pytest.fixture
def make_need() -> Callable[..., Need]:
    """Factory: a valid Need (Exmouth / generator) with per-test field overrides."""

    def _make(**overrides: object) -> Need:
        fields: dict[str, object] = {
            "id": deterministic_id("U_REQ", NEED_TS),
            "requester": "U_REQ",
            "need_type": "generator",
            "location": "Exmouth",
            "urgency": Urgency.HIGH,
            "household_size": 4,
            "source_ts": NEED_TS,
        }
        fields.update(overrides)
        return Need(**fields)

    return _make


@pytest.fixture
def make_match() -> Callable[..., RecallMatch]:
    """Factory: a valid RecallMatch with sensible defaults for the case under test."""

    def _make(
        text: str = "I have a spare generator in Exmouth",
        author: str = "Jordan",
        channel: str = "general",
        ts: datetime = NOW,
        permalink: str = "https://example.slack.com/archives/C1/p1",
    ) -> RecallMatch:
        return RecallMatch(
            text=text,
            author=author,
            author_id="U_OFFERER",
            channel=channel,
            channel_id="C1",
            ts=ts,
            permalink=permalink,
        )

    return _make


@pytest.fixture
def need(make_need: Callable[..., Need]) -> Need:
    """A representative Need: a generator in Exmouth."""
    return make_need()
