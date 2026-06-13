"""Shared fixtures for the action-handler unit tests.

These tests never touch real Slack: the ``WebClient``, ``Ack``, and the
process-local singletons (offer index, audit trail) are all mocked/patched so a
click can be driven and its side effects asserted without a live App. Builders are
fixtures so test modules don't import conftest directly (no ``__init__.py`` in the
test tree — pythonpath collection).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from entities import Offer, deterministic_id
from recall.payload import ConnectPayload

OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_canvas_side_effects(tmp_path: Path, mocker: MockerFixture) -> None:
    """Keep the board hook off the real filesystem and Slack.

    Most of these tests stub ``update_board`` outright, but the isolation test
    exercises the *real* best-effort board path. Point its canvas-id store at
    ``tmp_path`` and stub the announce so no test ever reads/writes the real
    ``.slack/board_canvas_id`` or posts to a coordinator channel (task 018).
    """
    from coordinator import canvas_store

    mocker.patch.object(
        canvas_store, "_id_path", return_value=tmp_path / ".slack" / "board_canvas_id"
    )
    mocker.patch("coordinator.canvas.announce_board")


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
def make_action_body() -> Callable[..., dict]:
    """Factory: a Slack block-action ``body`` for a clicked crisis button.

    Mirrors the shape Bolt hands a block-action handler: the clicker
    (``user.id`` = the requester), the card's channel/message, and the clicked
    button (``actions[0]`` with its ``value`` and ``block_id``). Overrides let a
    test tweak the payload or strip a field to exercise a degraded path.
    """

    def _make(
        *,
        clicker: str = "U_REQUESTER",
        action_id: str = "crisis_connect",
        block_id: str = "crisis_actions_0",
        value: str | None = None,
        payload: ConnectPayload | None = None,
        blocks: list[dict] | None = None,
    ) -> dict:
        if value is None:
            payload = payload or ConnectPayload(
                offerer_id="U_OFFERER",
                offer_id="",
                snippet="2kW generator — collect any time today (Exmouth)",
            )
            value = payload.to_value()
        if blocks is None:
            blocks = [
                {"type": "section", "block_id": "snippet_0"},
                {
                    "type": "actions",
                    "block_id": block_id,
                    "elements": [
                        {"type": "button", "action_id": action_id, "value": value},
                    ],
                },
            ]
        return {
            "user": {"id": clicker},
            "channel": {"id": "C_CARD"},
            "message": {"ts": "1742550600.000300", "blocks": blocks},
            "actions": [{"action_id": action_id, "block_id": block_id, "value": value}],
        }

    return _make
