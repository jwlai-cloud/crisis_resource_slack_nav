"""Unit tests for recall.payload — the button value round-trip.

The match identity rides a Slack button ``value`` as compact JSON. These tests
pin the contract the handlers depend on: a payload survives serialise -> parse
intact, optional fields tolerate absence, the snippet is truncated to stay under
Slack's 2000-char limit, and a malformed/identity-less value fails loudly so a
handler degrades explicitly rather than acting on a half-parsed match.
"""

import json

import pytest

from recall.payload import ConnectPayload


def test_index_hit_payload_round_trips() -> None:
    """An index-hit payload (offer_id present) survives serialise -> parse intact."""
    payload = ConnectPayload(
        offerer_id="U_OFFERER",
        offer_id="6f9c8b1a-3d2e-5f4b-9a8c-1e0d2c3b4a59",
        snippet="2kW generator — collect any time today (Exmouth)",
    )

    restored = ConnectPayload.from_value(payload.to_value())

    assert restored == payload


def test_rts_only_payload_round_trips() -> None:
    """An RTS-only payload (no offer_id, carries permalink) round-trips intact."""
    payload = ConnectPayload(
        offerer_id="U_SAM",
        permalink="https://example.slack.com/archives/C1/p1",
        snippet="I can lend a generator",
    )

    restored = ConnectPayload.from_value(payload.to_value())

    assert restored == payload
    assert restored.offer_id == ""


def test_to_value_omits_empty_optional_fields() -> None:
    """Empty optional fields are dropped from the serialised value to keep it small."""
    payload = ConnectPayload(offerer_id="U_OFFERER")

    data = json.loads(payload.to_value())

    assert data == {"offerer_id": "U_OFFERER"}


def test_long_snippet_is_truncated_under_slack_limit() -> None:
    """A pathologically long snippet is truncated; the value stays under 2000 chars."""
    payload = ConnectPayload(offerer_id="U_OFFERER", snippet="x" * 5000)

    value = payload.to_value()

    assert len(value) < 2000
    # The handler still parses; the snippet is shortened, not dropped here.
    assert ConnectPayload.from_value(value).snippet


def test_from_value_rejects_malformed_json() -> None:
    """A non-JSON value fails loudly so the handler degrades explicitly."""
    with pytest.raises(ValueError, match="not valid JSON"):
        ConnectPayload.from_value("not json {")


def test_from_value_rejects_missing_offerer_id() -> None:
    """A value with no offerer_id fails loudly — we never act on an unidentified match."""
    with pytest.raises(ValueError, match="missing offerer_id"):
        ConnectPayload.from_value(json.dumps({"offer_id": "x"}))
