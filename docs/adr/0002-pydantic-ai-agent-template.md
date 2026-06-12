# 0002. Use the pydantic-ai starter-agent template for the reasoning loop

**Status:** Accepted
**Date:** 2026-06-12

## Context

The design doc fixes the stack at Bolt for Python on the native agent surface but leaves the LLM SDK powering the parse → plan → rank → compose loop open. The Slack CLI offers three variants of `slack-samples/bolt-python-starter-agent`: `claude-agent-sdk`, `openai-agents-sdk`, and `pydantic-ai`. The choice locks in how tools, MCP toolsets, and structured outputs are wired, and which API keys the demo needs. Our data model leans heavily on typed structured fields (Need / Offer / Resolution as Pydantic models), and W3 requires connecting MCP servers as agent toolsets.

## Decision

We scaffold from `bolt-python-starter-agent --subdir pydantic-ai`. The agent is a pydantic-ai `Agent`; the model provider is selected at runtime by `agent/agent.py:get_model()` (Anthropic preferred when both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set), so the project stays provider-agnostic.

## Consequences

- Parsing needs into structured fields uses pydantic-ai's native typed outputs — same Pydantic models as the FastMCP mocks, one validation idiom across the codebase.
- The template already ships an `MCPServerStreamableHTTP` toolset wired to Slack's MCP server, which is the exact integration pattern W3 needs for our mock servers.
- Provider-agnostic: judges or teammates can run the demo with either an Anthropic or OpenAI key.
- We give up the deeper Anthropic-specific agent features of the Claude Agent SDK (subagents, hooks); nothing in the v1 scope needs them.
