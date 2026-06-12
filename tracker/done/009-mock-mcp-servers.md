# 009 — Mock MCP servers (external reach pillar)

Design doc §3/§9 + W3 milestone: thin FastMCP servers backed by static JSON under `mocks/`, consumed by the agent as additional pydantic-ai toolsets — same pattern as the already-wired Slack MCP server. The integration pattern is what's judged; never claim live feeds.

## Acceptance criteria

1. [x] `mocks/` package: one FastMCP server exposing the Exmouth scenario feeds (single server, multiple tools — keep it thin):
   - `get_road_closures()` — Main Roads WA-style closures (Minilya–Exmouth Rd CLOSED at Yannarie River crossing, Learmonth access under assessment, …)
   - `get_evac_centres()` — DFES-style evac centre list with capacity/status
   - `get_official_advice()` — Emergency WA-style advice notices (incl. the Exmouth Rec Centre water point from the demo script)
2. [x] Static JSON data files (`mocks/road_closures.json`, `mocks/evac_centres.json`, `mocks/official_advice.json`) seeded with realistic Cyclone Narelle scenario data; every record carries an `updated_at` timestamp (aware UTC ISO) — feeds the fetched-at stamping.
3. [x] Conventions (CLAUDE.md): tool names verb_noun snake_case; Pydantic models for every argument and return; expected failures return structured error results (e.g. feed_unavailable simulation flag) — never exceptions.
4. [x] Every tool return includes feed name + `fetched_at` so replies can render `feed / fetched-at` + verify note (guardrail 3).
5. [x] Agent wiring: the mock server joins `run_agent`'s toolsets (alongside Slack MCP) — config via env (`MOCK_MCP_URL` or stdio subprocess; pick the simplest that works with `slack run`, document the choice in the task log; ADR if it forks from "thin mocks" posture).
6. [x] System prompt: extend the plan-step source list so the model knows the official tools exist and must stamp their results (anchor test for the new section).
7. [x] Tests: unit-test tool bodies directly (parametrized); integration-test the session via FastMCP's test client (CLAUDE.md testing rules). Zero warnings.
8. [ ] [HUMAN] live verification: need message → reply contains an official MCP-sourced item with feed/fetched-at + verify note (demo-script beat 0:55–1:20). — NOT RUN (needs `slack run` + a live LLM key in the sandbox).

## Out of scope
Action buttons (010), card visual parity (008), Canvas (W4).

## Log

### [SWE] 2026-06-12 20:05 — Implementation

**Transport decision: pydantic-ai `MCPServerStdio` launching `python -m mocks.server` as a stdio subprocess.**

- Simplest thing that works under `slack run`: no port, no URL, no second process to start/stop by hand. pydantic-ai spawns and tears down the subprocess around each agent run, so the host app manages nothing extra.
- Matches the existing toolset wiring exactly — the mock server is just another entry appended to `run_agent`'s `toolsets` list, beside the Slack `MCPServerStreamableHTTP`.
- Consistent with the "thin mocks" posture (design doc §9) and ADR-0003 — no architectural fork, so **no new ADR**.
- Uses `sys.executable` + `cwd=<repo root>` so the subprocess runs under the same locked interpreter regardless of where the Slack CLI launches the app.
- FastMCP banner suppressed (`mcp.run(show_banner=False)`) to keep `slack run` logs clean.

**Research evidence (verified it actually runs, no live LLM):**
- `fastmcp` 3.4.2 already present (transitive via pydantic-ai's `fastmcp` extra); `pydantic_ai.mcp.MCPServerStdio(command, args, *, env, cwd)` confirmed present in pydantic-ai 1.107.0. Promoted `fastmcp` to a *declared* runtime dep (`uv add "fastmcp>=3.4,<4"`) since `mocks/server.py` imports it directly — relying on a transitive pin is fragile; `<4` guards the FastMCP API we use against a major bump.
- FastMCP in-memory `Client(mcp)` smoke: a `@mcp.tool` returning a Pydantic model deserialises cleanly (`result.data` rebuilds the object; union returns wrap under `structured_content["result"]` but `.data` exposes fields directly — integration test uses `.data`).
- **End-to-end through `run_agent`'s real path** with `TestModel` (no live LLM): pydantic-ai launched `python -m mocks.server` over stdio, advertised all three tools, and `TestModel` called each — `get_road_closures` returned the seeded Narelle data (Minilya-Exmouth Rd CLOSED at Yannarie River) with an aware-UTC `fetched_at`. Degraded path verified too: `MOCK_FEED_DOWN=road_closures` returns a structured `FeedError` over the session (`is_error: False`, data carries `error="feed_down"`), other feeds stay up.

**Files created**
- `mocks/__init__.py` — package docstring (thin mocks, never live feeds).
- `mocks/server.py` — one FastMCP server `mcp`; three `verb_noun` tools (`get_road_closures` / `get_evac_centres` / `get_official_advice`); Pydantic record models (`RoadClosure` / `EvacCentre` / `OfficialAdvice`) with an aware-UTC `updated_at` validator; `FeedResult` (feed + `fetched_at` + records) / `FeedError` (returned, never raised) for happy/degraded; `FEEDS` registry; `MOCK_FEED_DOWN` (comma-separated, lenient) simulation; loader returns `FeedError` for missing/corrupt JSON.
- `mocks/road_closures.json`, `mocks/evac_centres.json`, `mocks/official_advice.json` — seeded Narelle data (Minilya-Exmouth Rd CLOSED at Yannarie; Learmonth access UNDER ASSESSMENT; Exmouth Rec Centre evac+water point with capacity; 3 Emergency WA notices incl. the water-point advice), every record with an aware-UTC `updated_at`.
- `tests/unit/mocks/test_server.py` — tool bodies direct, parametrized (happy / missing file / corrupt / simulated-down), plus seed-data + naive-rejection assertions (18 tests).
- `tests/integration/mocks/test_server_session.py` — FastMCP in-session via `Client(mcp)` (no subprocess, no LLM → runs in CI, not marked `live`): advertises 3 tools, happy call → sourced FeedResult, simulated-down → structured FeedError over the wire (5 tests).
- `tests/unit/agent/test_run_agent_toolsets.py` — `run_agent` wiring: mock server on by default, removed only by `MOCK_MCP_DISABLED=1`, independent of Slack MCP (4 tests).

**Files modified**
- `agent/agent.py` — imports `sys` / `Path` / `MCPServerStdio`; `_mock_mcp_server()` factory + `_REPO_ROOT`; `run_agent` appends the mock server to `toolsets` unless `MOCK_MCP_DISABLED=1`; new **OFFICIAL DIRECTORIES** prompt section (names the 3 tools; every result carries feed + `fetched_at` + verify note; relays official sources, never asserts safety; a feed error is stated by name, never silently skipped).
- `tests/unit/test_system_prompt.py` — anchor assertions for the OFFICIAL DIRECTORIES section (tool names + feed/fetched-at + verify + degraded-by-name + no-invented-feeds).
- `.env.example` — documents `MOCK_MCP_DISABLED` (kill-switch) and `MOCK_FEED_DOWN` (demo degraded cue).
- `pyproject.toml` / `uv.lock` — `fastmcp>=3.4,<4` added as a runtime dep.

**Tests**
- Unit: 150 passing, 0 failing (`make pre-commit`). New: 18 mock-server + 4 wiring + 6 prompt-anchor.
- Integration: 5 passing, 1 skipped (pre-existing live-LLM parsing test; no key). The FastMCP session test runs in CI without secrets.

**Acceptance criteria**
- [x] AC1 — `tests/unit/mocks/test_server.py::test_tool_happy_path_returns_typed_feed_result`, `::test_feeds_registry_lists_all_three_official_directories`.
- [x] AC2 — `::test_road_closure_records_are_aware_utc_and_seeded`, `::test_evac_centre_records_carry_capacity_and_water_point`; every record `updated_at` aware-UTC.
- [x] AC3 — `verb_noun` tools, Pydantic returns; `::test_tool_returns_feed_error_when_file_missing` / `_corrupt` / `_simulated_down` (structured error, never exception); `::test_record_updated_at_is_naive_rejected`.
- [x] AC4 — `FeedResult.feed` + `.fetched_at` asserted in unit + session tests.
- [x] AC5 — `tests/unit/agent/test_run_agent_toolsets.py` (default-on + `MOCK_MCP_DISABLED=1` kill-switch); stdio transport (decision above).
- [x] AC6 — `tests/unit/test_system_prompt.py::test_official_directories_section_anchored`, `::test_official_directories_names_all_three_tools`.
- [x] AC7 — `tests/integration/mocks/test_server_session.py` via FastMCP `Client`; `filterwarnings=["error"]`, zero warnings.
- [ ] [HUMAN] AC8 — NOT RUN: needs `slack run` against the sandbox + a live LLM key (demo beat 0:55–1:20). E2E through `run_agent`'s real toolset path is verified with `TestModel` (no LLM) — see evidence above.

**Evidence**
```
$ make pre-commit
... 150 passed in 4.66s

$ make integration-tests
tests/integration/agent/test_parsing_live.py s
tests/integration/mocks/test_server_session.py .....
5 passed, 1 skipped in 2.92s

$ # e2e through run_agent path, TestModel (no live LLM)
TOOLS CALLED: ['add_emoji_reaction', 'get_evac_centres', 'get_official_advice', 'get_road_closures']
  get_road_closures -> {'feed': 'road_closures', 'fetched_at': '2026-06-12T12:01:24.614788Z', 'records': [{'road'...
E2E OK: stdio subprocess reachable via pydantic-ai; banner suppressed.

$ # degraded path
MOCK_FEED_DOWN=road_closures -> Root(feed='road_closures', error='feed_down', detail='...simulated outage...')
                                evac_centres still up, records: 3
```

**QA tail**
```
$ make format-fix && make lint-fix && make format-check && make lint-check
58 files left unchanged          (ruff format)
All checks passed!               (ruff check --fix)
58 files already formatted       (ruff format --check)
All checks passed!               (ruff check)
```

**Notes**
- `fastmcp` promoted from transitive → declared runtime dep (justified above); this is the only new dependency.
- No listener/recall/matching changes — wiring lives entirely in `agent/agent.py`.
- No ADR: stdio transport is the thinnest option and does not fork from the "thin mocks" posture (design doc §9) or ADR-0003.
- The session-test reads `result.data` (not `structured_content`) because FastMCP wraps a union return under `structured_content["result"]`; `.data` exposes fields directly. Documented inline.
- `MOCK_MCP_DISABLED=1` is a kill-switch (default ON, matching the task); `MOCK_FEED_DOWN=<feed[,feed]>` is the demo degraded-state cue (case/space-insensitive).
- AC8 ([HUMAN]) left for the Tester/human to run live in the sandbox.

### [Tester] 2026-06-12 20:12 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`58 files already formatted`, `All checks passed!`, `150 passed`)
- Unit tests: 150 passed / 0 failed
- Integration tests: 5 passed / 1 skipped (skip = pre-existing live-LLM parsing test, no key); the 5 FastMCP session tests RUN (confirmed `-v`, no skips) — no live LLM needed
- Warnings: 0 (`filterwarnings=["error"]`; double full-suite run 155 passed deterministically, no state pollution)
- `uv lock --check`: clean (166 packages resolved); `fastmcp>=3.4,<4` → 3.4.2

**E2E adversarial pass**
- Happy path (no env): all 3 tools → `FeedResult` w/ feed + aware-UTC `fetched_at` + 3 records each. PASS.
- Break 1 (corrupt JSON, real loader): `{ not valid json ]` → `FeedError(feed_unavailable)`, no exception escaped. PASS.
- Break 2 (schema drift / non-list / naive-ts-in-JSON): each → `FeedError(feed_unavailable)`, no exception. PASS.
- Break 3 (MOCK_FEED_DOWN=all three): every tool → `FeedError(feed_down)` by name, none crash. PASS.
- Break 4 (integration client, unexpected arg `{bogus:x}` + unknown tool): both → structured `ToolError` over the protocol, clean reject. PASS.
- Break 5 (subprocess fails to start — `-m mocks.does_not_exist` through a real agent run): run **crashes with unhandled `ExceptionGroup`**; `compose_reply` does NOT wrap `run_agent`. NON-BLOCKING — out of AC scope (AC3/AC4 scope "expected failures" to feed-data, all handled) and identical to the pre-existing Slack-MCP transport behaviour. See "Other issues".
- Break 6 (future aware timestamp in JSON): ACCEPTED (no future-rejection validator). NON-BLOCKING — `_ensure_aware_utc` is a faithful mirror of `entities.models._ensure_aware_utc`, which also accepts future dates; AC2 only requires aware UTC. Consistent with project convention.
- Empty `[]` JSON → valid empty `FeedResult(records=[])`. Reasonable (prompt says "say you found nothing").

**Acceptance criteria**
- [x] PASS — AC1 one FastMCP server, 3 verb_noun tools — `mocks/server.py:183/195/207`; session advertises all three (`test_server_session.py::test_session_advertises_the_three_official_tools`).
- [x] PASS — AC2 3 JSON files, every record aware-UTC ISO `updated_at` — runtime check: 3/3/3 records all aware-ISO; Narelle content present (Minilya-Exmouth Rd CLOSED at Yannarie, Learmonth UNDER ASSESSMENT, Exmouth Rec Centre water point).
- [x] PASS — AC3 conventions — verb_noun + Pydantic models on all returns; structured `FeedError` (never raised) for missing/corrupt/schema-drift/non-list/simulated-down (probed directly through real loader); naive `updated_at` rejected at model boundary.
- [x] PASS — AC4 feed + `fetched_at` on every return — `FeedResult.feed`/`.fetched_at` aware-UTC at runtime and over the session (`.data` carries them).
- [x] PASS — AC5 agent wiring — REAL factory path verified: default-on appends `MCPServerStdio(args=['-m','mocks.server'], cwd=<repo>)`; `MOCK_MCP_DISABLED=1` removes it; independent of Slack MCP. Transport (stdio subprocess) documented; no ADR fork.
- [x] PASS — AC6 prompt section — OFFICIAL DIRECTORIES present; 9 anchors pass; gutting simulation breaks 7/8 anchors (not vacuous); pre-existing guardrail/placeholder anchors survive.
- [x] PASS — AC7 tests — tool bodies unit-tested (parametrized, 18); session integration-tested via `Client(mcp)` (5, run in CI, no `live` mark); 0 warnings.
- [ ] [HUMAN] AC8 — Awaiting human verification: needs `slack run` + live LLM key (demo beat 0:55–1:20). E2E through `run_agent`'s real toolset path verified with TestModel (no LLM).

**Guardrail re-check (SYSTEM_PROMPT touched — all PASS, quoted in prompt)**
- G1 human decides: "confirmation step" / "never an automatic action".
- G2 never assert safety: "Never assert safety." / "never say a road is safe or that it is okay to travel".
- G3 sourced+timestamped: "show who posted it and when (who/when)" / "feed / fetched-at".
- G4 degraded explicit: "Degraded states are explicit." / "name the source that could not".
- Placeholder rule: "Never emit placeholder text".
- NEW official-directories stamping rule: "carries a feed name and a `fetched_at` timestamp", "render it as `feed / fetched-at`", "verify before relying on this", "Never restate a closure or advisory as a safety assertion of your own", degraded feed named never silently skipped — all present and reinforced at the MCP-tool layer.

**Evidence**
```
$ make pre-commit
58 files already formatted / All checks passed! / 150 passed in 3.80s
$ uv run pytest tests/integration/mocks/test_server_session.py -v
5 passed in 3.91s   (no skips — session tests run without secrets)
$ make integration-tests
5 passed, 1 skipped in 3.61s   (skip = live-LLM parsing test only)
$ uv lock --check
Resolved 166 packages   (fastmcp 3.4.2, specifier >=3.4,<4)
$ MOCK_FEED_DOWN="road_closures,evac_centres,official_advice" (all 3) -> FeedError(feed_down) each, none crash
$ corrupt/schema-drift/non-list/naive-ts JSON via real loader -> FeedError(feed_unavailable), no exception escaped
```

**Other issues found (NON-BLOCKING — follow-up, orchestrator's call)**
- `MCPServerStdio` (and the pre-existing Slack `MCPServerStreamableHTTP`) emit a `DeprecationWarning` in pydantic-ai 1.107 ("removed in v2; use `MCPToolset(...)`"). Not tripped by the suite because the wiring test mocks the factory; works correctly at runtime today. Project-wide migration (touches the Slack path too) is a separate refactor — file as a follow-up, not a 009 blocker.
- A mock-subprocess *start* failure (e.g. `mocks.server` unimportable) crashes the agent run with an unhandled `ExceptionGroup`; `compose_reply` doesn't wrap `run_agent`. Out of AC scope (AC3/AC4 scope "expected failures" to feed data, all handled) and identical to the pre-existing Slack-MCP behaviour. Worth a hardening follow-up (wrap the run / connect step) so an infra failure degrades to a guardrail-4 message rather than no reply.
- No future-timestamp rejection in `_ensure_aware_utc` — matches the existing `entities.models` validator; AC2 doesn't require it. Note only.

**VERDICT: PASS**
All seven implementable ACs verified with runtime evidence; AC8 is [HUMAN], awaiting live sandbox. Full suite green, 0 warnings, e2e adversarial pass green on every in-scope break path; all four guardrails + placeholder rule + new stamping rule hold. The two non-blocking items above are pre-existing-pattern follow-ups, not 009 regressions.

### [Human] 2026-06-12 20:18 — AC8 live verification (PASS)
Need message in sandbox DM produced the full three-tech reply: RTS workspace match
(generator+water offer, contact mention) + MCP official data (water point, road
closures incl. Yannarie crossing CLOSED and Learmonth under assessment, two evac
centres) — every MCP item stamped feed/fetched-at with the verify note. Demo-script
beat 0:55-1:20 reproduced live.
