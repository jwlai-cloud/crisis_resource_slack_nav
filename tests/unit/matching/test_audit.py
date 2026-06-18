"""Unit tests for matching.audit — the in-memory audit trail.

Every button action appends one immutable, aware-UTC-stamped event. These tests
pin the append contract the handlers rely on: a recorded event carries the actor,
action, and target; the timestamp is aware-UTC; and the trail returns an
insertion-ordered snapshot. A naive timestamp can never slip in — the trail
stamps ``datetime.now(UTC)`` itself, asserted aware here.
"""

from datetime import UTC

from matching.audit import AuditEvent, AuditTrail


def test_record_appends_event_with_fields() -> None:
    """A recorded event carries actor, action, and target verbatim."""
    trail = AuditTrail()

    event = trail.record(actor_id="U_REQ", action="connect", target="offer:abc")

    assert isinstance(event, AuditEvent)
    assert event.actor_id == "U_REQ"
    assert event.action == "connect"
    assert event.target == "offer:abc"


def test_recorded_timestamp_is_aware_utc() -> None:
    """The audit timestamp is timezone-aware UTC (never a naive local time)."""
    trail = AuditTrail()

    event = trail.record(actor_id="U_REQ", action="resolve", target="offer:abc")

    assert event.ts.tzinfo == UTC


def test_list_events_returns_snapshot_in_order() -> None:
    """list_events returns every event in insertion order, as a copy."""
    trail = AuditTrail()
    trail.record(actor_id="U_A", action="connect", target="offer:1")
    trail.record(actor_id="U_B", action="not_relevant", target="offer:2")

    events = trail.list_events()

    assert [(e.actor_id, e.action) for e in events] == [
        ("U_A", "connect"),
        ("U_B", "not_relevant"),
    ]
    # Snapshot, not the live list: mutating the returned list does not affect the trail.
    events.clear()
    assert len(trail.list_events()) == 2
