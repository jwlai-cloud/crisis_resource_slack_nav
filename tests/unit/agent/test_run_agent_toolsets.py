"""Unit tests for run_agent's toolset wiring (the mock MCP kill-switch).

These never call a model or spawn a subprocess: ``agent.run_sync`` is patched to
capture the ``toolsets`` it is handed, and the mock-server factory is patched to a
sentinel so no stdio process is launched. They pin the contract that the mock
official-directories server is wired **on by default** and removed only by the
``MOCK_MCP_DISABLED=1`` kill-switch — independently of the Slack MCP server,
which depends on a user token.
"""

import sys
import warnings
from types import ModuleType

import pytest
from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP
from pytest_mock import MockerFixture

from agent.agent import _mock_mcp_server, run_agent
from agent.deps import AgentDeps


@pytest.fixture
def _ignore_mcp_deprecation() -> object:
    """Suppress pydantic-ai's MCPServer* v2-deprecation while we still use the v1 API.

    ``MCPServerStdio`` / ``MCPServerStreamableHTTP`` are deprecated in favour of
    ``MCPToolset`` but are the classes in use today (agent/agent.py); the project's
    ``filterwarnings = ["error"]`` would otherwise turn the deprecation (raised when a
    test instantiates them directly) into a failure. Mirrors the targeted suppression
    in ``agent.agent._vertex_model``.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        yield


# The `agent` package re-exports the name `agent` as the Agent *instance*, which
# shadows the `agent.agent` *module*. Fetch the module from sys.modules so the
# module-level names (run_sync's owner, _mock_mcp_server, get_model) are patchable
# — same idiom as tests/unit/agent/conftest.py.
agent_module: ModuleType = sys.modules["agent.agent"]


@pytest.fixture
def deps(mocker: MockerFixture) -> AgentDeps:
    """AgentDeps with no Slack user token (Slack MCP off) and a stub client."""
    return AgentDeps(
        client=mocker.MagicMock(),
        user_id="U1",
        channel_id="C1",
        thread_ts="1.0",
        message_ts="1.0",
        user_token=None,
    )


@pytest.fixture
def captured_toolsets(mocker: MockerFixture) -> list[object]:
    """Patch run_sync (no LLM) and the mock-server factory (no subprocess).

    Returns the list the test should read *after* calling ``run_agent``; the
    run_sync mock appends the toolsets it received into this list.
    """
    captured: list[object] = []
    sentinel = object()
    mocker.patch.object(agent_module, "_mock_mcp_server", return_value=sentinel)
    # get_model() would otherwise demand a provider key; stub it out.
    mocker.patch.object(agent_module, "get_model", return_value="test")

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        captured.extend(toolsets)
        return mocker.MagicMock()

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)
    return captured


def _mock_sentinel() -> object:
    """The object the patched factory returns (for identity checks)."""
    return agent_module._mock_mcp_server.return_value  # type: ignore[attr-defined]


def test_mock_mcp_server_wired_on_by_default(
    deps: AgentDeps,
    captured_toolsets: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no kill-switch set, the mock server joins the toolsets."""
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)

    run_agent("Is the road open?", deps)

    assert _mock_sentinel() in captured_toolsets


def test_mock_mcp_server_removed_by_kill_switch(
    deps: AgentDeps,
    captured_toolsets: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOCK_MCP_DISABLED=1 removes the mock server from the toolsets."""
    monkeypatch.setenv("MOCK_MCP_DISABLED", "1")

    run_agent("Is the road open?", deps)

    assert _mock_sentinel() not in captured_toolsets


def test_kill_switch_only_trips_on_exactly_one(
    deps: AgentDeps,
    captured_toolsets: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-"1" MOCK_MCP_DISABLED value leaves the mock server enabled."""
    monkeypatch.setenv("MOCK_MCP_DISABLED", "false")

    run_agent("Is the road open?", deps)

    assert _mock_sentinel() in captured_toolsets


def test_mock_mcp_independent_of_slack_mcp(
    deps: AgentDeps,
    captured_toolsets: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Slack user token (Slack MCP off) still leaves the mock server wired."""
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)
    assert deps.user_token is None  # Slack MCP server would not be added

    run_agent("Is the road open?", deps)

    # Exactly the mock server, no Slack MCP server.
    assert captured_toolsets == [_mock_sentinel()]


# --- _mock_mcp_server transport selection (task 034 Part A, AC2) -------------------
#
# The factory connects to a PERSISTENT HTTP server when MOCK_MCP_URL is set (the
# deployed container path — no per-reply subprocess spawn), else falls back to the
# stdio subprocess for local `slack run`. These build the real toolset objects (no
# server is started — pydantic-ai connects lazily on run), so we assert on type/config.


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_mock_mcp_server_is_http_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """MOCK_MCP_URL set -> a persistent MCPServerStreamableHTTP (no subprocess spawn)."""
    monkeypatch.setenv("MOCK_MCP_URL", "http://127.0.0.1:8765/mcp")

    server = _mock_mcp_server()

    assert isinstance(server, MCPServerStreamableHTTP)


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_mock_mcp_server_is_stdio_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MOCK_MCP_URL -> the stdio subprocess (local dev), with the 30s init timeout."""
    monkeypatch.delenv("MOCK_MCP_URL", raising=False)

    server = _mock_mcp_server()

    assert isinstance(server, MCPServerStdio)
    # The cold-import headroom from the prior fix is preserved on the stdio path.
    assert server.timeout == 30


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_run_agent_uses_http_mock_when_url_set(
    deps: AgentDeps,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """End to end through run_agent: MOCK_MCP_URL set wires the HTTP mock toolset.

    The real factory runs here (not the sentinel patch) so we prove run_agent picks
    up the HTTP transport from the env, not a per-run stdio spawn.
    """
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)
    monkeypatch.setenv("MOCK_MCP_URL", "http://127.0.0.1:8765/mcp")
    mocker.patch.object(agent_module, "get_model", return_value="test")
    captured: list[object] = []

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        captured.extend(toolsets)
        return mocker.MagicMock()

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)

    run_agent("Is the road open?", deps)

    assert any(isinstance(toolset, MCPServerStreamableHTTP) for toolset in captured)


# --- Part B: graceful MCP degradation (AC3) ---------------------------------------
#
# An MCP toolset that fails to connect/enter must NOT take the reply down: run_agent
# retries once WITHOUT the MCP toolset(s) so the prose still composes. The official
# CARDS come from the direct read_situation path (recall_reply), not these toolsets,
# so they render regardless — these tests cover the agent run itself.


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_mcp_toolset_failure_does_not_raise_and_reply_still_composes(
    deps: AgentDeps,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """First run (with MCP toolsets) raises on enter; run_agent retries clean (AC3).

    The retry drops the MCP toolset(s) and the run returns a real result instead of
    propagating — the reply always lands.
    """
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)
    monkeypatch.delenv("MOCK_MCP_URL", raising=False)
    mocker.patch.object(agent_module, "get_model", return_value="test")
    # A real MCP toolset instance so the degradation logic recognises it to drop.
    mock_toolset = MCPServerStdio(command=sys.executable, args=["-m", "mocks.server"])
    mocker.patch.object(agent_module, "_mock_mcp_server", return_value=mock_toolset)

    calls: list[list[object]] = []
    result_marker = mocker.MagicMock()

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        calls.append(list(toolsets))
        if len(calls) == 1:
            # Simulate a toolset that fails to enter/connect (the prod hang's shape).
            raise ConnectionError("mock MCP server unreachable")
        return result_marker

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)

    result = run_agent("Is the road open?", deps)

    # Did not raise; returned a composed result.
    assert result is result_marker
    # Exactly two attempts: the first WITH the failing MCP toolset, the retry WITHOUT.
    assert len(calls) == 2
    assert mock_toolset in calls[0]
    assert mock_toolset not in calls[1]


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_mcp_failure_drops_all_mcp_toolsets_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """The retry strips the Slack MCP toolset too, not just the mock one (AC3).

    With a user token the Slack MCP toolset is also wired; the retry must drop every
    MCP server toolset so a flaky MCP source can never keep the reply down.
    """
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)
    monkeypatch.delenv("MOCK_MCP_URL", raising=False)
    deps_with_token = AgentDeps(
        client=mocker.MagicMock(),
        user_id="U1",
        channel_id="C1",
        thread_ts="1.0",
        message_ts="1.0",
        user_token="xoxp-x",
    )
    mocker.patch.object(agent_module, "get_model", return_value="test")
    mock_toolset = MCPServerStdio(command=sys.executable, args=["-m", "mocks.server"])
    mocker.patch.object(agent_module, "_mock_mcp_server", return_value=mock_toolset)

    calls: list[list[object]] = []

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        calls.append(list(toolsets))
        if len(calls) == 1:
            raise ConnectionError("mock MCP server unreachable")
        return mocker.MagicMock()

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)

    run_agent("Is the road open?", deps_with_token)

    assert len(calls) == 2
    # First attempt carries both MCP toolsets; the retry carries none.
    assert len(calls[0]) == 2  # Slack MCP + mock MCP
    assert calls[1] == []


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_retry_failure_still_propagates_not_an_mcp_swallow_all(
    deps: AgentDeps,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """If the clean retry ALSO fails, the error propagates — we only retry once (AC3).

    The degrade is a single bounded retry, not an infinite or silent swallow: a real
    model failure on the toolset-free run still surfaces to the listener's own
    error handling.
    """
    monkeypatch.delenv("MOCK_MCP_DISABLED", raising=False)
    monkeypatch.delenv("MOCK_MCP_URL", raising=False)
    mocker.patch.object(agent_module, "get_model", return_value="test")
    mock_toolset = MCPServerStdio(command=sys.executable, args=["-m", "mocks.server"])
    mocker.patch.object(agent_module, "_mock_mcp_server", return_value=mock_toolset)

    calls: list[list[object]] = []

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        calls.append(list(toolsets))
        raise ConnectionError("everything is down")

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)

    with pytest.raises(ConnectionError):
        run_agent("Is the road open?", deps)

    assert len(calls) == 2  # original + one retry, then give up


@pytest.mark.usefixtures("_ignore_mcp_deprecation")
def test_non_mcp_failure_with_no_mcp_toolsets_does_not_retry(
    deps: AgentDeps,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """A failure when NO MCP toolset was attached propagates immediately — no retry (AC3).

    The kill-switch (and no user token) leaves zero MCP toolsets; a failure then is
    unrelated to MCP, so there is nothing to drop and we must not retry/loop.
    """
    monkeypatch.setenv("MOCK_MCP_DISABLED", "1")
    mocker.patch.object(agent_module, "get_model", return_value="test")

    calls: list[list[object]] = []

    def _fake_run_sync(prompt: str, *, toolsets: list[object], **kwargs: object) -> object:
        calls.append(list(toolsets))
        raise RuntimeError("model error, nothing to do with MCP")

    mocker.patch.object(agent_module.agent, "run_sync", side_effect=_fake_run_sync)

    with pytest.raises(RuntimeError):
        run_agent("Is the road open?", deps)

    assert len(calls) == 1  # no retry — there was no MCP toolset to drop
