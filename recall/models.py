"""Typed results for the RTS recall step (the *plan*/*rank* layer).

The recall layer turns Real-Time Search API hits into a small typed surface the
rest of the agent ranks and composes from. Two product guardrails are encoded
here structurally, the same way ``entities.models`` does for Need/Offer:

* **Every item is sourced and timestamped.** ``RecallMatch`` carries the author,
  the channel, a permalink, and a required timezone-aware UTC ``ts``. A field
  validator rejects naive datetimes at the boundary (CLAUDE.md "Key Python
  Design Choices").
* **Degraded states are explicit.** A search that cannot run returns a typed
  ``RecallError`` (never an exception swallowed into silence, never an empty
  list pretending to be "no results"). Callers branch on the result type and
  say so on screen.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


def _ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC.

    Mirrors ``entities.models._ensure_aware_utc``: a recall match's timestamp is
    shown on screen and feeds recency ranking, so a naive value (which silently
    assumes local time) is rejected at the boundary.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("ts must be timezone-aware (UTC); naive datetimes are rejected")
    return value.astimezone(UTC)


class RecallMatch(BaseModel):
    """One Real-Time Search hit, with its source and timestamp.

    Maps a single ``results.messages[]`` entry from ``assistant.search.context``.
    ``author``/``channel``/``permalink``/``ts`` are the trust-critical source
    fields the composed reply must surface for every item.
    """

    text: str
    author: str
    author_id: str
    channel: str
    channel_id: str
    ts: datetime
    permalink: str
    # The in-memory index id of the originating offer, as a string, when this match
    # came from the matching index; empty for an RTS-only hit (which links to the
    # workspace via ``permalink`` instead). The action-button handlers use it to
    # resolve the offer in the index on a Mark-resolved click. Optional and default
    # empty so RTS-sourced matches construct unchanged.
    offer_id: str = ""

    _validate_ts = field_validator("ts")(_ensure_aware_utc)


class RecallError(BaseModel):
    """A search that could not run — the typed "degraded" result.

    ``reason`` is a short machine code (e.g. the Slack error string, or
    ``"no_user_token"``); ``detail`` is a human-readable line for logs. The
    composed reply never renders the raw reason verbatim — it shows a calm
    "couldn't search the workspace right now" message — but callers log it.
    """

    reason: str
    detail: str = ""


def match_from_message(message: dict[str, object]) -> RecallMatch:
    """Build a :class:`RecallMatch` from one RTS ``results.messages[]`` dict.

    ``message_ts`` arrives as a string Unix timestamp (e.g. ``"1742550600.0002"``);
    we parse it to an aware-UTC datetime so ranking and on-screen display share
    one normalised "when". Missing optional source fields fall back to empty
    strings rather than raising — a hit with no permalink is still a hit, just a
    less linkable one — but ``message_ts`` is required (no timestamp = not a
    sourced item, and we never surface unsourced items).
    """
    raw_ts = message["message_ts"]
    ts = datetime.fromtimestamp(float(raw_ts), tz=UTC)  # type: ignore[arg-type]
    return RecallMatch(
        text=str(message.get("content", "")),
        author=str(message.get("author_name", "")),
        author_id=str(message.get("author_user_id", "")),
        channel=str(message.get("channel_name", "")),
        channel_id=str(message.get("channel_id", "")),
        ts=ts,
        permalink=str(message.get("permalink", "")),
    )
