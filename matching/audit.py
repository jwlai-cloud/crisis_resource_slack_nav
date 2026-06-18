"""In-memory audit trail for human-confirmed button actions (task 010).

Every bounded-autonomy button press — Connect, Mark resolved, Not relevant —
appends one immutable :class:`AuditEvent` here: who acted, what they did, the
target match, and when (aware-UTC). This is a thin precursor to W4's audit log:
process-local, no persistence, surfaced only as a log count for now. It exists so
the human-decides guardrail leaves a trail — the agent never acts, so every event
in here is a person's deliberate confirmation.

Process-local and not durable by design, mirroring the matching index
(``docs/adr/0003-in-memory-matching-index.md``). It dies with the process; that is
fine for the demo. A :class:`threading.Lock` guards the append since button
handlers run on Bolt's thread pool.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def _ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC.

    The audit timestamp is a "when did the human confirm this" record, so the same
    boundary rule the rest of the system uses applies: a naive value silently
    assumes local time and is rejected.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("ts must be timezone-aware (UTC); naive datetimes are rejected")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class AuditEvent:
    """One human-confirmed button action: actor, action, target, timestamp."""

    actor_id: str
    action: str
    target: str
    ts: datetime


class AuditTrail:
    """A process-local, append-only list of :class:`AuditEvent` records.

    Not durable by design (see the module docstring). Thread-safe: a lock guards
    the append and the snapshot read because button handlers mutate from Bolt's
    thread pool.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def record(self, actor_id: str, action: str, target: str) -> AuditEvent:
        """Append an event stamped with the current aware-UTC instant; return it.

        Logs the running event count — the only surface for the trail in v1 (the
        W4 audit log will render it).
        """
        event = AuditEvent(
            actor_id=actor_id,
            action=action,
            target=target,
            ts=_ensure_aware_utc(datetime.now(UTC)),
        )
        with self._lock:
            self._events.append(event)
            count = len(self._events)
        logger.info("Audit: %s by %s on %s (%d events recorded)", action, actor_id, target, count)
        return event

    def list_events(self) -> list[AuditEvent]:
        """Return a snapshot copy of every recorded event (insertion order)."""
        with self._lock:
            return list(self._events)


# Module-level singleton: one trail per socket-mode process, mirroring the
# matching-index singleton. Handlers import this directly.
audit_trail = AuditTrail()
