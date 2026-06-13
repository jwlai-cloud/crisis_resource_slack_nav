"""Shared fixtures for the coordinator-board unit tests.

These tests never touch real Slack: the board composer is pure, and the publisher
is exercised with a mocked ``WebClient`` so canvas create/edit calls are asserted
without a live API. Builders are exposed as fixtures (no ``__init__.py`` in the
test tree — pythonpath collection), mirroring the matching test conftest.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from entities import Offer, Status, deterministic_id
from matching.audit import AuditEvent

OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)
EVENT_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


@pytest.fixture
def make_offer() -> Callable[..., Offer]:
    """Factory: a valid Offer (generator in Exmouth) with per-test overrides."""

    def _make(**overrides: object) -> Offer:
        offerer = str(overrides.pop("offerer", "U_OFFERER"))
        source_ts = overrides.pop("source_ts", OFFER_TS)
        assert isinstance(source_ts, datetime)
        status = overrides.pop("status", Status.OPEN)
        fields: dict[str, object] = {
            "id": deterministic_id(offerer, source_ts),
            "offerer": offerer,
            "resource_type": "generator",
            "location": "Exmouth",
            "availability": "collect any time today",
            "status": status,
            "source_ts": source_ts,
        }
        fields.update(overrides)
        return Offer(**fields)

    return _make


@pytest.fixture
def make_event() -> Callable[..., AuditEvent]:
    """Factory: an AuditEvent (a connect on an offer) with per-test overrides."""

    def _make(**overrides: object) -> AuditEvent:
        fields: dict[str, object] = {
            "actor_id": "U_REQUESTER",
            "action": "connect",
            "target": "offer:abc-123",
            "ts": EVENT_TS,
        }
        fields.update(overrides)
        return AuditEvent(**fields)  # type: ignore[arg-type]

    return _make
