"""Unit tests for the typed core (entities.models).

Covers the two guardrails encoded structurally in the models: source timestamps
must be timezone-aware UTC, and ids must be deterministic for idempotent
re-parsing.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from entities import (
    PROJECT_NAMESPACE,
    Need,
    Offer,
    Resolution,
    Status,
    Urgency,
    deterministic_id,
)

AWARE_TS = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)
NAIVE_TS = datetime(2026, 3, 14, 9, 30)


def _need(**overrides: object) -> Need:
    """Build a valid Need, with field overrides for the case under test."""
    fields: dict[str, object] = {
        "id": deterministic_id("U_REQ", AWARE_TS),
        "requester": "U_REQ",
        "need_type": "drinking water",
        "location": "Exmouth",
        "urgency": Urgency.HIGH,
        "household_size": 3,
        "source_ts": AWARE_TS,
    }
    fields.update(overrides)
    return Need(**fields)


def _offer(**overrides: object) -> Offer:
    """Build a valid Offer, with field overrides for the case under test."""
    fields: dict[str, object] = {
        "id": deterministic_id("U_OFF", AWARE_TS),
        "offerer": "U_OFF",
        "resource_type": "generator",
        "location": "Exmouth",
        "availability": "this afternoon",
        "source_ts": AWARE_TS,
    }
    fields.update(overrides)
    return Offer(**fields)


# --- happy-path construction --------------------------------------------------


def test_need_defaults_to_open_status() -> None:
    """A Need with no explicit status starts OPEN."""
    need = _need()

    assert need.status is Status.OPEN


def test_offer_defaults_to_open_status() -> None:
    """An Offer with no explicit status starts OPEN."""
    offer = _offer()

    assert offer.status is Status.OPEN


def test_need_coerces_string_urgency_to_enum() -> None:
    """A raw urgency string from the parser coerces to the Urgency enum."""
    need = _need(urgency="critical")

    assert need.urgency is Urgency.CRITICAL


@pytest.mark.parametrize("status", ["open", "matched", "resolved"])
def test_status_enum_accepts_each_member(status: str) -> None:
    """Each documented status value round-trips through the enum."""
    need = _need(status=status)

    assert need.status.value == status


# --- naive-datetime rejection (product guardrail) -----------------------------


def test_need_rejects_naive_source_ts() -> None:
    """A naive source_ts is rejected: timestamps are a product guardrail."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        _need(source_ts=NAIVE_TS)


def test_offer_rejects_naive_source_ts() -> None:
    """A naive source_ts is rejected on Offers too."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        _offer(source_ts=NAIVE_TS)


def test_resolution_rejects_naive_timestamp() -> None:
    """Resolution's confirmation timestamp must also be timezone-aware."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        Resolution(
            need_id=deterministic_id("U_REQ", AWARE_TS),
            offer_id=deterministic_id("U_OFF", AWARE_TS),
            confirmed_by="U_COORD",
            timestamp=NAIVE_TS,
        )


def test_aware_non_utc_source_ts_normalised_to_utc() -> None:
    """An aware non-UTC source_ts is normalised to UTC, not rejected."""
    perth = timezone(timedelta(hours=8))
    need = _need(source_ts=datetime(2026, 3, 14, 17, 30, tzinfo=perth))

    assert need.source_ts.tzinfo is UTC
    assert need.source_ts == datetime(2026, 3, 14, 9, 30, tzinfo=UTC)


# --- deterministic ids (idempotent re-parsing) --------------------------------


def test_deterministic_id_is_stable_across_calls() -> None:
    """Same (author, ts) -> same id: re-parsing one message never duplicates."""
    first = deterministic_id("U_REQ", AWARE_TS)
    second = deterministic_id("U_REQ", AWARE_TS)

    assert first == second


def test_deterministic_id_is_uuid5_in_project_namespace() -> None:
    """The id is a UUID5 (version 5), not a random uuid4."""
    generated = deterministic_id("U_REQ", AWARE_TS)

    assert isinstance(generated, UUID)
    assert generated.version == 5


def test_deterministic_id_differs_by_author() -> None:
    """Different authors at the same instant get different ids."""
    a = deterministic_id("U_ONE", AWARE_TS)
    b = deterministic_id("U_TWO", AWARE_TS)

    assert a != b


def test_deterministic_id_differs_by_timestamp() -> None:
    """Same author at different instants get different ids."""
    later = AWARE_TS + timedelta(minutes=1)
    a = deterministic_id("U_REQ", AWARE_TS)
    b = deterministic_id("U_REQ", later)

    assert a != b


def test_deterministic_id_collides_across_equal_instants_in_different_zones() -> None:
    """Two zone representations of the same instant produce the same id."""
    perth = timezone(timedelta(hours=8))
    utc_repr = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)
    perth_repr = datetime(2026, 3, 14, 17, 30, tzinfo=perth)

    assert deterministic_id("U_REQ", utc_repr) == deterministic_id("U_REQ", perth_repr)


def test_deterministic_id_rejects_naive_timestamp() -> None:
    """deterministic_id refuses naive datetimes at the boundary too."""
    with pytest.raises(ValueError, match="timezone-aware"):
        deterministic_id("U_REQ", NAIVE_TS)


def test_project_namespace_is_pinned() -> None:
    """The UUID5 namespace is a pinned literal; moving it re-keys every id."""
    assert UUID("6f9c8b1a-3d2e-5f4b-9a8c-1e0d2c3b4a59") == PROJECT_NAMESPACE
