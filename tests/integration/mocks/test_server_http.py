"""Integration test for the persistent HTTP mock MCP server (task 034, Part A).

Proves the deployed container's transport for real: the mock server is started as a
SUBPROCESS over HTTP (``MOCK_MCP_HTTP_PORT`` set — the way ``deploy/entrypoint.sh``
launches it), and the agent's client class — pydantic-ai's ``MCPServerStreamableHTTP``,
the same one ``agent.agent._mock_mcp_server`` returns when ``MOCK_MCP_URL`` is set —
connects to it, lists the three tools, and calls one. No LLM, no secrets, so it runs
in CI; it is not marked ``live``.

This is the genuine end-to-end of the fix: a long-lived HTTP server reached over the
wire, not the in-memory ``Client(mcp)`` of the stdio-shape session test.
"""

import os
import socket
import subprocess
import sys
import time
import warnings
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.asyncio

# A high, unlikely-contended port for the test server. Localhost only.
_TEST_PORT = 8791
_BIND_TIMEOUT_S = 30


def _port_is_bound(port: int) -> bool:
    """True if something is accepting TCP connections on 127.0.0.1:port."""
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture
def http_mock_server() -> Iterator[str]:
    """Start ``python -m mocks.server`` over HTTP in a subprocess; yield its URL.

    Mirrors ``deploy/entrypoint.sh``: set ``MOCK_MCP_HTTP_PORT``, launch the server,
    wait for the port to bind, hand back the ``…/mcp`` URL, and tear the process down
    afterwards. Uses the SAME interpreter that runs the tests so it picks up the
    locked deps.
    """
    env = {**os.environ, "MOCK_MCP_HTTP_PORT": str(_TEST_PORT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mocks.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + _BIND_TIMEOUT_S
        while not _port_is_bound(_TEST_PORT):
            if proc.poll() is not None:
                raise RuntimeError("mock MCP server exited before binding the HTTP port")
            if time.monotonic() > deadline:
                raise RuntimeError(f"mock MCP server did not bind within {_BIND_TIMEOUT_S}s")
            time.sleep(0.2)
        yield f"http://127.0.0.1:{_TEST_PORT}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


async def test_agent_connects_to_persistent_http_server(http_mock_server: str) -> None:
    """MCPServerStreamableHTTP (the agent's client) reaches the persistent HTTP server."""
    with warnings.catch_warnings():
        # MCPServerStreamableHTTP is deprecated in favour of MCPToolset but is the
        # class the agent uses today; filterwarnings=error would otherwise fail here.
        warnings.simplefilter("ignore", DeprecationWarning)
        from pydantic_ai.mcp import MCPServerStreamableHTTP

        server = MCPServerStreamableHTTP(http_mock_server)

    async with server:
        tools = await server.list_tools()
        names = {tool.name for tool in tools}

        assert names >= {"get_road_closures", "get_evac_centres", "get_official_advice"}

        # A real round-trip call over HTTP returns the road-closures feed data.
        result = await server.direct_call_tool("get_road_closures", {})

    # The union return deserialises to a mapping carrying the feed name + records.
    assert result["feed"] == "road_closures"
    assert result["records"]
