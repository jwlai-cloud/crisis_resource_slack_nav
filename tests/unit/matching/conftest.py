"""Shared fixtures for the matching unit tests.

These tests never touch real Slack or the network. Builders are exposed as
fixtures (``make_offer`` / ``make_need``) so test modules don't import from
conftest directly — the matching test dir has no ``__init__.py`` (pythonpath
collection), so a relative ``from .conftest import ...`` would fail. A fresh
``OfferIndex`` fixture keeps each test isolated from the module-level singleton.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from entities import Need, Offer, Urgency, deterministic_id
from matching.index import OfferIndex

# Fixed timestamps so id derivation and recency math stay deterministic.
OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)
NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


@pytest.fixture
def make_offer() -> Callable[..., Offer]:
    """Factory: a valid Offer (generator in Exmouth) with per-test overrides."""

    def _make(**overrides: object) -> Offer:
        offerer = str(overrides.pop("offerer", "U_OFFERER"))
        source_ts = overrides.pop("source_ts", OFFER_TS)
        assert isinstance(source_ts, datetime)
        fields: dict[str, object] = {
            "id": deterministic_id(offerer, source_ts),
            "offerer": offerer,
            "resource_type": "generator",
            "location": "Exmouth",
            "availability": "collect any time today",
            "source_ts": source_ts,
        }
        fields.update(overrides)
        return Offer(**fields)

    return _make


@pytest.fixture
def make_need() -> Callable[..., Need]:
    """Factory: a valid Need (generator in Exmouth) with per-test overrides."""

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
def index() -> OfferIndex:
    """A fresh, empty index isolated from the module-level singleton."""
    return OfferIndex()
