"""Need / Offer / Resolution models — the typed core from design doc §6.

Two product guardrails are encoded structurally here, not left to convention:

* **Every item is sourced and timestamped.** ``source_ts`` is a required,
  timezone-aware UTC datetime; a field validator rejects naive datetimes at the
  boundary (see CLAUDE.md "Key Python Design Choices").
* **Idempotent re-parsing.** Ids are UUID5 derived from a fixed project
  namespace plus the message's (author, source_ts). Re-parsing the same Slack
  message — e.g. on a listener retry or a backfill — yields the *same* id, so
  the matching index never accumulates duplicate Needs/Offers for one post.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, field_validator

# Fixed UUID5 namespace for this project. Generated once (uuid5 of the DNS
# namespace and "crisis-resource-navigator"); pinned as a literal so it never
# moves. Never regenerate it — changing it would re-key every existing id.
PROJECT_NAMESPACE = UUID("6f9c8b1a-3d2e-5f4b-9a8c-1e0d2c3b4a59")


class Status(StrEnum):
    """Lifecycle of a Need or an Offer."""

    OPEN = "open"
    MATCHED = "matched"
    RESOLVED = "resolved"


class Urgency(StrEnum):
    """How time-critical a Need is. Ordered low -> high by listing order."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC.

    Source timestamps are a product guardrail (CLAUDE.md): we never let a naive
    datetime in, because "when" is shown on screen and used for ranking, and a
    naive value silently assumes local time. Aware non-UTC values are converted
    to UTC so all stored timestamps are comparable.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("source_ts must be timezone-aware (UTC); naive datetimes are rejected")
    return value.astimezone(UTC)


def deterministic_id(author: str, source_ts: datetime) -> UUID:
    """Derive a stable UUID5 id from the originating message.

    The id is a pure function of (author, source_ts) within
    ``PROJECT_NAMESPACE``, so parsing the same message twice produces the same
    id. ``source_ts`` is normalised to UTC ISO-8601 first, so two aware
    datetimes denoting the same instant in different zones collide on purpose.
    """
    aware = _ensure_aware_utc(source_ts)
    return uuid5(PROJECT_NAMESPACE, f"{author}|{aware.isoformat()}")


class Need(BaseModel):
    """A resident's request for a resource (design doc §6)."""

    id: UUID
    requester: str
    need_type: str
    location: str
    urgency: Urgency
    household_size: int
    status: Status = Status.OPEN
    source_ts: datetime

    _validate_source_ts = field_validator("source_ts")(_ensure_aware_utc)


class Offer(BaseModel):
    """A volunteer's offer of a resource (design doc §6)."""

    id: UUID
    offerer: str
    resource_type: str
    location: str
    availability: str
    status: Status = Status.OPEN
    source_ts: datetime

    _validate_source_ts = field_validator("source_ts")(_ensure_aware_utc)


class Resolution(BaseModel):
    """A human-confirmed link between a Need and an Offer (design doc §6).

    Created only via the bounded-autonomy confirmation step: ``confirmed_by`` is
    the human who pressed Connect / Mark resolved, never the agent itself.
    """

    need_id: UUID
    offer_id: UUID
    confirmed_by: str
    timestamp: datetime

    _validate_timestamp = field_validator("timestamp")(_ensure_aware_utc)
