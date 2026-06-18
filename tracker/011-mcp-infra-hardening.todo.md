# 011 — MCP infra hardening + transport migration

Two non-blocking findings from 009's Tester (2026-06-12):

1. A mock-subprocess START failure (vs a feed error) crashes the agent run with an
   unhandled ExceptionGroup — compose_reply doesn't wrap run_agent for toolset
   startup failures. Same pre-existing behavior for the Slack MCP transport. Should
   degrade to a guardrail-4 message ("official directories unreachable") instead of
   no reply.
2. pydantic-ai 1.107 deprecates both MCPServerStdio and MCPServerStreamableHTTP
   (v2: MCPToolset). Project-wide transport migration when convenient — pairs with
   the GoogleCloudProvider migration note in memory.

## Log
