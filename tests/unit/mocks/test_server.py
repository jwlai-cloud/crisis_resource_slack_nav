"""Unit tests for the mock MCP server tool bodies (mocks.server).

The three official-directory tools (``get_road_closures`` / ``get_evac_centres``
/ ``get_official_advice``) are exercised directly, not through the MCP session
(that is the integration test). Three behaviours per CLAUDE.md's FastMCP rules:

* **happy path** — the static JSON loads into a typed ``FeedResult`` carrying the
  feed name, an aware-UTC ``fetched_at``, and the records (sourcing guardrail);
* **missing / corrupt file** — a structured ``FeedError`` is *returned*, never an
  exception raised (degraded-states guardrail);
* **simulated down** — when ``MOCK_FEED_DOWN`` names the feed, the same structured
  ``FeedError`` comes back so the demo can show the degraded state on cue.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pytest_mock import MockerFixture

import mocks.server as server_module
from mocks.server import (
    FEEDS,
    EvacCentre,
    FeedError,
    FeedResult,
    OfficialAdvice,
    RoadClosure,
    get_evac_centres,
    get_official_advice,
    get_road_closures,
)

# (feed name, tool callable, record model, a field every record of that feed has).
TOOLS: list[tuple[str, Callable[[], FeedResult | FeedError], type, str]] = [
    ("road_closures", get_road_closures, RoadClosure, "road"),
    ("evac_centres", get_evac_centres, EvacCentre, "name"),
    ("official_advice", get_official_advice, OfficialAdvice, "title"),
]
TOOL_IDS = [name for name, *_ in TOOLS]


@pytest.mark.parametrize(("feed", "tool", "model", "field"), TOOLS, ids=TOOL_IDS)
def test_tool_happy_path_returns_typed_feed_result(
    feed: str,
    tool: Callable[[], FeedResult | FeedError],
    model: type,
    field: str,
) -> None:
    """A tool loads its static JSON into a sourced, timestamped FeedResult."""
    result = tool()

    assert isinstance(result, FeedResult)
    assert result.feed == feed
    # fetched-at is the trust stamp: aware UTC, set at call time (guardrail 3).
    assert result.fetched_at.tzinfo == UTC
    assert result.records, "seeded JSON should yield at least one record"
    for record in result.records:
        assert isinstance(record, model)
        assert getattr(record, field)
        # every record carries its own aware-UTC source timestamp.
        assert record.updated_at.tzinfo == UTC


@pytest.mark.parametrize(("feed", "tool", "model", "field"), TOOLS, ids=TOOL_IDS)
def test_tool_returns_feed_error_when_file_missing(
    feed: str,
    tool: Callable[[], FeedResult | FeedError],
    model: type,
    field: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing data file yields a structured FeedError, not an exception."""
    # Point the loader at an empty dir so every feed file is absent.
    monkeypatch.setattr("mocks.server.DATA_DIR", tmp_path)

    result = tool()

    assert isinstance(result, FeedError)
    assert result.feed == feed
    assert result.error == "feed_unavailable"
    assert result.detail


@pytest.mark.parametrize(("feed", "tool", "model", "field"), TOOLS, ids=TOOL_IDS)
def test_tool_returns_feed_error_when_file_corrupt(
    feed: str,
    tool: Callable[[], FeedResult | FeedError],
    model: type,
    field: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt JSON yields a structured FeedError, not an exception."""
    monkeypatch.setattr("mocks.server.DATA_DIR", tmp_path)
    (tmp_path / f"{feed}.json").write_text("{ this is not valid json ]", encoding="utf-8")

    result = tool()

    assert isinstance(result, FeedError)
    assert result.feed == feed
    assert result.error == "feed_unavailable"


@pytest.mark.parametrize(("feed", "tool", "model", "field"), TOOLS, ids=TOOL_IDS)
def test_tool_returns_feed_error_when_simulated_down(
    feed: str,
    tool: Callable[[], FeedResult | FeedError],
    model: type,
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOCK_FEED_DOWN naming the feed forces the degraded state on cue."""
    monkeypatch.setenv("MOCK_FEED_DOWN", feed)

    result = tool()

    assert isinstance(result, FeedError)
    assert result.feed == feed
    assert result.error == "feed_down"
    assert result.detail


def test_mock_feed_down_accepts_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOCK_FEED_DOWN can name several feeds; only those are down."""
    monkeypatch.setenv("MOCK_FEED_DOWN", "road_closures, official_advice")

    assert isinstance(get_road_closures(), FeedError)
    assert isinstance(get_official_advice(), FeedError)
    # evac_centres was not named, so it still loads.
    assert isinstance(get_evac_centres(), FeedResult)


def test_mock_feed_down_is_case_and_space_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sloppy MOCK_FEED_DOWN value still trips the named feed."""
    monkeypatch.setenv("MOCK_FEED_DOWN", "  Road_Closures  ")

    assert isinstance(get_road_closures(), FeedError)


def test_feeds_registry_lists_all_three_official_directories() -> None:
    """FEEDS is the single source of truth for the wired feed names."""
    assert set(FEEDS) == {"road_closures", "evac_centres", "official_advice"}


def test_road_closure_records_are_aware_utc_and_seeded() -> None:
    """The Narelle road-closure scenario is present and sourced."""
    result = get_road_closures()

    assert isinstance(result, FeedResult)
    roads = {record.road for record in result.records}
    assert "Minilya-Exmouth Road" in roads
    assert "Learmonth Access Road" in roads
    minilya = next(r for r in result.records if r.road == "Minilya-Exmouth Road")
    assert minilya.status == "CLOSED"
    assert "Yannarie" in minilya.segment


def test_evac_centre_records_carry_capacity_and_water_point() -> None:
    """The Exmouth Rec Centre evac/water-point record is present with capacity."""
    result = get_evac_centres()

    assert isinstance(result, FeedResult)
    rec_centre = next(r for r in result.records if "Recreation Centre" in r.name)
    assert rec_centre.capacity > 0
    assert any("water" in service.lower() for service in rec_centre.services)


# --- Transport selection (task 034): HTTP when MOCK_MCP_HTTP_PORT is set, else stdio --
#
# ``_run`` never actually starts a server here — ``mcp.run`` is patched to capture the
# transport it was asked for, so the test is fast and binds no port.


def test_run_uses_http_transport_when_port_set(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOCK_MCP_HTTP_PORT set -> mcp.run(transport='http', host=127.0.0.1, port=...)."""
    monkeypatch.setenv("MOCK_MCP_HTTP_PORT", "8765")
    run = mocker.patch.object(server_module.mcp, "run")

    server_module._run()

    run.assert_called_once_with(transport="http", host="127.0.0.1", port=8765, show_banner=False)


def test_run_uses_stdio_transport_by_default(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MOCK_MCP_HTTP_PORT -> stdio default (mcp.run with no transport)."""
    monkeypatch.delenv("MOCK_MCP_HTTP_PORT", raising=False)
    run = mocker.patch.object(server_module.mcp, "run")

    server_module._run()

    run.assert_called_once_with(show_banner=False)


def test_run_http_port_is_coerced_to_int(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env port (a string) is passed to mcp.run as an int."""
    monkeypatch.setenv("MOCK_MCP_HTTP_PORT", "9001")
    run = mocker.patch.object(server_module.mcp, "run")

    server_module._run()

    assert run.call_args.kwargs["port"] == 9001
    assert isinstance(run.call_args.kwargs["port"], int)


def test_record_updated_at_is_naive_rejected() -> None:
    """A naive updated_at is rejected at the model boundary (sourcing guardrail)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="timezone-aware"):
        RoadClosure(
            road="Test Rd",
            segment="x",
            status="CLOSED",
            reason="y",
            detour="z",
            updated_at=datetime(2026, 3, 14, 22, 10),  # naive
        )
