"""Unit tests for run_agent's toolset wiring (the mock MCP kill-switch).

These never call a model or spawn a subprocess: ``agent.run_sync`` is patched to
capture the ``toolsets`` it is handed, and the mock-server factory is patched to a
sentinel so no stdio process is launched. They pin the contract that the mock
official-directories server is wired **on by default** and removed only by the
``MOCK_MCP_DISABLED=1`` kill-switch — independently of the Slack MCP server,
which depends on a user token.
"""

import sys
from types import ModuleType

import pytest
from pytest_mock import MockerFixture

from agent.agent import run_agent
from agent.deps import AgentDeps

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
