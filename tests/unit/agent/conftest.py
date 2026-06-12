"""Fixtures for agent unit tests.

These tests never talk to a real model: every parse runs under a pydantic-ai
``override(model=...)`` with a ``FunctionModel``. But ``parse_message`` still
calls ``get_model()`` to pick the provider string before the override replaces
it, and ``get_model()`` raises if no provider key is set. This autouse fixture
supplies a dummy key (and clears ``get_model``'s cache) so model *selection*
succeeds while the override guarantees no live LLM call is ever made.
"""

import asyncio
import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _current_event_loop() -> Iterator[None]:
    """Ensure a current event loop exists for synchronous ``run_sync`` calls.

    ``parse_message`` is sync and calls pydantic-ai's ``run_sync``, which uses
    ``asyncio.get_event_loop()``. On Python 3.12+ that emits a DeprecationWarning
    when no loop is current — and our pytest config escalates warnings to errors.
    In production a loop is established by the Bolt/socket-mode runtime; in these
    sync unit tests we set (and clean up) one ourselves so the harness mirrors
    that and stays warning-clean.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def _dummy_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a dummy provider so get_model() resolves without a live key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # get_model() memoises its choice in a module global; reset it so the dummy
    # key (not whatever a prior test/run set) is what gets picked. The submodule
    # is fetched from sys.modules because the `agent` package re-exports the
    # name `agent` as the Agent *instance*, shadowing the `agent.agent` module.
    agent_module = sys.modules["agent.agent"]
    monkeypatch.setattr(agent_module, "_cached_model", None)
