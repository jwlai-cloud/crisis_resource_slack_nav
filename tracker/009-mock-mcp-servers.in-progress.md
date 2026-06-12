# 009 — Mock MCP servers (external reach pillar)

Design doc §3/§9 + W3 milestone: thin FastMCP servers backed by static JSON under `mocks/`, consumed by the agent as additional pydantic-ai toolsets — same pattern as the already-wired Slack MCP server. The integration pattern is what's judged; never claim live feeds.

## Acceptance criteria

1. `mocks/` package: one FastMCP server exposing the Exmouth scenario feeds (single server, multiple tools — keep it thin):
   - `get_road_closures()` — Main Roads WA-style closures (Minilya–Exmouth Rd CLOSED at Yannarie River crossing, Learmonth access under assessment, …)
   - `get_evac_centres()` — DFES-style evac centre list with capacity/status
   - `get_official_advice()` — Emergency WA-style advice notices (incl. the Exmouth Rec Centre water point from the demo script)
2. Static JSON data files (`mocks/road_closures.json`, `mocks/evac_centres.json`, `mocks/official_advice.json`) seeded with realistic Cyclone Narelle scenario data; every record carries an `updated_at` timestamp (aware UTC ISO) — feeds the fetched-at stamping.
3. Conventions (CLAUDE.md): tool names verb_noun snake_case; Pydantic models for every argument and return; expected failures return structured error results (e.g. feed_unavailable simulation flag) — never exceptions.
4. Every tool return includes feed name + `fetched_at` so replies can render `feed / fetched-at` + verify note (guardrail 3).
5. Agent wiring: the mock server joins `run_agent`'s toolsets (alongside Slack MCP) — config via env (`MOCK_MCP_URL` or stdio subprocess; pick the simplest that works with `slack run`, document the choice in the task log; ADR if it forks from "thin mocks" posture).
6. System prompt: extend the plan-step source list so the model knows the official tools exist and must stamp their results (anchor test for the new section).
7. Tests: unit-test tool bodies directly (parametrized); integration-test the session via FastMCP's test client (CLAUDE.md testing rules). Zero warnings.
8. [HUMAN] live verification: need message → reply contains an official MCP-sourced item with feed/fetched-at + verify note (demo-script beat 0:55–1:20).

## Out of scope
Action buttons (010), card visual parity (008), Canvas (W4).

## Log
