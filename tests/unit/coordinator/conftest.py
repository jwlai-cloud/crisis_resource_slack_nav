"""Shared fixtures for the coordinator-board unit tests.

These tests never touch real Slack: the board composer is pure, and the publisher
is exercised with a mocked ``WebClient`` so canvas create/edit calls are asserted
without a live API. Builders are exposed as fixtures (no ``__init__.py`` in the
test tree — pythonpath collection), mirroring the matching test conftest.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from entities import Offer, Status, deterministic_id
from matching.audit import AuditEvent

OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)
EVENT_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_canvas_side_effects(tmp_path: Path, mocker: MockerFixture) -> None:
    """Keep the canvas tests off the real filesystem and Slack by default.

    Every canvas test would otherwise read/write the real ``.slack/board_canvas_id``
    and try to post to a coordinator channel via :func:`coordinator.canvas.publish`.
    Point the id store at ``tmp_path`` and stub the announce so a test only sees
    those side effects when it opts in (re-patches them itself). Tests that assert
    the persistence/announce contract re-patch over these to inspect the calls.
    """
    from coordinator import canvas_store

    mocker.patch.object(
        canvas_store, "_id_path", return_value=tmp_path / ".slack" / "board_canvas_id"
    )
    mocker.patch("coordinator.canvas.announce_board")
    mocker.patch("coordinator.canvas.upsert_board_bookmark")


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
