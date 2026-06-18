"""Integration test for the mock MCP server over a real FastMCP session.

Exercises the server the way pydantic-ai will: through the MCP protocol, not by
calling the tool functions directly. FastMCP's in-memory ``Client(mcp)`` runs the
server in-process over the real session machinery — no subprocess, no port, and
**no LLM** — so this runs in CI without secrets (it is not marked ``live``).

It proves the three tools are advertised over the session, that a happy call
deserialises into the typed FeedResult shape (feed + fetched-at + records), and
that the degraded path surfaces a structured FeedError over the wire (never an
exception) so the agent can state the source by name.
"""

import pytest
from fastmcp import Client

from mocks.server import mcp

pytestmark = pytest.mark.asyncio

EXPECTED_TOOLS = {"get_road_closures", "get_evac_centres", "get_official_advice"}


async def test_session_advertises_the_three_official_tools() -> None:
    """All three official-directory tools are listed over the MCP session."""
    async with Client(mcp) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} >= EXPECTED_TOOLS


@pytest.mark.parametrize(
    ("tool_name", "feed"),
    [
        ("get_road_closures", "road_closures"),
        ("get_evac_centres", "evac_centres"),
        ("get_official_advice", "official_advice"),
    ],
)
async def test_session_happy_call_returns_sourced_feed_result(
    tool_name: str,
    feed: str,
) -> None:
    """A happy tool call deserialises to a sourced, timestamped FeedResult."""
    async with Client(mcp) as client:
        result = await client.call_tool(tool_name, {})

    # ``data`` is the deserialised return; a union return is rebuilt as a dynamic
    # object exposing the success fields (feed / fetched_at / records).
    payload = result.data
    assert payload.feed == feed
    assert payload.fetched_at, "fetched-at stamp must be present"
    assert payload.records, "seeded JSON should yield at least one record"
    assert not result.is_error


async def test_session_returns_structured_error_when_feed_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A simulated-down feed comes back as a structured FeedError over the wire."""
    monkeypatch.setenv("MOCK_FEED_DOWN", "evac_centres")

    async with Client(mcp) as client:
        result = await client.call_tool("get_evac_centres", {})

    payload = result.data
    # The degraded state crosses the session as data (error/feed/detail), not as
    # a raised exception — the agent states the source by name (guardrail 4).
    assert payload.error == "feed_down"
    assert payload.feed == "evac_centres"
    assert payload.detail
    assert not result.is_error
