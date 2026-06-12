"""Unit tests for recall.models — typed match/error + RTS message mapping.

Covers the guardrail encoded structurally here: a match timestamp must be
timezone-aware UTC, and a raw RTS message maps onto the trust-critical source
fields with its string Unix ts parsed to an aware-UTC datetime.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from recall.models import RecallError, RecallMatch, match_from_message


def test_recall_match_rejects_naive_timestamp() -> None:
    """A naive ts is rejected at the boundary (sourcing guardrail)."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        RecallMatch(
            text="offer",
            author="Jordan",
            author_id="U1",
            channel="general",
            channel_id="C1",
            ts=datetime(2026, 3, 21, 12, 0),  # naive
            permalink="https://x/p1",
        )


def test_recall_match_normalises_aware_ts_to_utc() -> None:
    """An aware non-UTC ts is converted to UTC so all timestamps are comparable."""
    plus_two = timezone(timedelta(hours=2))

    match = RecallMatch(
        text="offer",
        author="Jordan",
        author_id="U1",
        channel="general",
        channel_id="C1",
        ts=datetime(2026, 3, 21, 14, 0, tzinfo=plus_two),
        permalink="https://x/p1",
    )

    assert match.ts == datetime(2026, 3, 21, 12, 0, tzinfo=UTC)
    assert match.ts.tzinfo == UTC


def test_match_from_message_maps_source_fields() -> None:
    """Each RTS results.messages[] field lands on the right RecallMatch attribute."""
    message = {
        "content": "I have a spare 2kW generator in town",
        "author_name": "Jordan",
        "author_user_id": "U0123456",
        "channel_name": "offers",
        "channel_id": "C0123456",
        "message_ts": "1742550600.000200",
        "permalink": "https://mycompany.slack.com/archives/C0123456/p1742550600000200",
    }

    match = match_from_message(message)

    assert match.text == "I have a spare 2kW generator in town"
    assert match.author == "Jordan"
    assert match.author_id == "U0123456"
    assert match.channel == "offers"
    assert match.channel_id == "C0123456"
    assert match.permalink.endswith("p1742550600000200")
    assert match.ts == datetime.fromtimestamp(1742550600.0002, tz=UTC)
    assert match.ts.tzinfo == UTC


def test_match_from_message_tolerates_missing_optional_fields() -> None:
    """Missing optional source fields fall back to empty strings, not errors."""
    match = match_from_message({"message_ts": "1742550600.000200"})

    assert match.text == ""
    assert match.author == ""
    assert match.permalink == ""


def test_match_from_message_requires_timestamp() -> None:
    """No message_ts means the item isn't sourced — mapping must fail loudly."""
    with pytest.raises(KeyError):
        match_from_message({"content": "no timestamp here"})


def test_recall_error_defaults_detail_to_empty() -> None:
    """RecallError carries a machine reason; detail is optional."""
    error = RecallError(reason="ratelimited")

    assert error.reason == "ratelimited"
    assert error.detail == ""
