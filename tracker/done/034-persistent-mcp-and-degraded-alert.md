# 034 — Persistent HTTP mock MCP server + graceful degradation + degraded-official alert

Live deploy on a free GCE e2-micro exposed two real issues:
- The mock MCP server is spawned **per reply** over stdio; on the slow VM the cold
  FastMCP import (~5–12s) blew past `MCPServerStdio`'s 5s init timeout → handshake
  `BrokenResourceError` → **the whole reply hung** (uncaught). Bumping the timeout to
  30s unblocked it, but every reply still pays a ~5s subprocess spawn.
- A toolset that fails to start is **fatal** — the agent run raises and the reply never
  lands. That violates the degraded-states guardrail: a flaky external source must
  degrade, not take the agent down.

Fix all three: serve the mock MCP **persistently over HTTP**, **degrade gracefully** if
any MCP toolset is unavailable, and **alert the user** when official info can't be
retrieved (rather than silently omitting it or implying the picture is complete).

FastMCP 3.4.2 supports `transport="http"`; pydantic-ai has `MCPServerStreamableHTTP`
(already used for Slack's MCP server). Both confirmed installed.

## Part A — Persistent HTTP mock MCP server
- `mocks/server.py`: when an env flag is set (e.g. `MOCK_MCP_HTTP_PORT`), run
  `mcp.run(transport="http", host="127.0.0.1", port=<port>, show_banner=False)`;
  otherwise keep the **stdio default** (so local `slack run` is unchanged, zero-config).
- `agent/agent.py` `_mock_mcp_server()`: if `MOCK_MCP_URL` is set, connect via
  `MCPServerStreamableHTTP(MOCK_MCP_URL)` (persistent, no per-run spawn); else the
  current `MCPServerStdio(..., timeout=30)` (local dev). Keep `MOCK_MCP_DISABLED` honored.
- Container: a small `deploy/entrypoint.sh` that starts the mock MCP HTTP server in the
  background (sets `MOCK_MCP_HTTP_PORT`), waits for it to bind, sets `MOCK_MCP_URL=http://127.0.0.1:<port>/mcp`,
  then `exec`s `python app.py`. Dockerfile runtime `CMD` → the entrypoint. With
  `--container-restart-policy=always`, a crash restarts the whole container.
- Result: import once at container start, warm thereafter → fast replies, genuine
  long-lived MCP server (same shape as the Slack MCP integration).

## Part B — Graceful MCP degradation (never hang/crash a reply)
- The agent run must not die if an MCP toolset can't be entered/reached. Wrap
  `agent.run_sync` (in `agent/agent.py`'s run path) so that on an MCP/toolset
  connection failure it **retries once without the failing MCP toolset(s)** (or catches
  and re-runs with the remaining toolsets), so the reply always composes. The official
  **cards** come from the direct `read_situation()` path (not the MCP toolset), so they
  still render regardless. Log the degradation (INFO/WARNING), never raise out to the
  listener.

## Part C — Degraded-official alert (user-facing)
- `read_situation()` already renders a per-feed "feed unavailable: <feed> — <detail>"
  card (guardrail 4). Strengthen the **whole-path** case: if the situation read fails
  entirely (raises) OR every relevant official feed is unavailable, the reply must carry
  an explicit, plain user-facing line — e.g. *"I couldn't reach the official directories
  right now, so I can't give you current road/official conditions — please verify
  directly with the official source."* — not silence, not an implied-complete answer.
- Thread this into the info-need `llm_context` (recall_reply) + the official-blocks
  composer: when official data is unavailable, the prose + a degraded notice say so
  plainly. Never assert safety; never fill the gap with a guess.

## Acceptance criteria
1. [x] `mocks/server.py` runs HTTP transport when `MOCK_MCP_HTTP_PORT` is set; stdio by
   default. — unit test (env on → http path selected; unset → stdio).
2. [x] `_mock_mcp_server()` returns `MCPServerStreamableHTTP(MOCK_MCP_URL)` when
   `MOCK_MCP_URL` set, else `MCPServerStdio(timeout=30)`; `MOCK_MCP_DISABLED=1` still
   skips it. — unit tests for all three branches.
3. [x] An MCP toolset connection/enter failure does NOT raise out of the agent run —
   the reply still composes (without that toolset). — unit test: a toolset that raises
   on enter → run still returns; official cards + prose still produced.
4. [x] When official info is fully unavailable (situation read raises, or all relevant
   feeds down), the reply carries an explicit user-facing "couldn't reach official
   sources — can't give current conditions, verify directly" alert (prose + a degraded
   notice). Never asserts safety, never invents. — unit tests on the composer +
   llm_context.
5. [x] `deploy/entrypoint.sh` starts the HTTP mock server in the background + execs
   app.py; Dockerfile runtime CMD uses it. Local `slack run` is unchanged (stdio). —
   code-evident + the entrypoint is shellcheck-clean.
6. [x] Guardrail recheck (Part C touches degraded-states + the llm_context): all 4
   guardrails intact — human-confirms, never-assert-safety, sourced+timestamped,
   degraded-loud. A PASS skipping this is a FAIL.
7. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
8. [ ] [HUMAN] Live (after redeploy): replies are fast (no ~5s per-reply spawn); a
   safety question still returns the official cards + consistent prose; simulating a
   down feed shows the explicit "official sources unavailable" alert.

## BDD
- Given `MOCK_MCP_URL` set, when the agent runs, then it connects to the persistent
  HTTP server (no subprocess spawn).
- Given the mock MCP server is unreachable, when a need is answered, then the reply
  still lands (official cards via the direct path) — no hang/crash.
- Given the official feeds are all down, when a road-safety question is asked, then the
  reply explicitly says the official directories are unavailable + refuses to judge
  safety + tells the user to verify directly.
- Given local `slack run` (no MOCK_MCP_URL), when the agent runs, then it uses the
  stdio mock server as before.

## Out of scope
- Replacing the mock data with real government feeds (situation.py stays the swap point).
- e2-small / paid tiers (the persistent server makes e2-micro viable).

## Log

### [SWE] 2026-06-17 17:10 — Implementation

**Files modified**
- `mocks/server.py` — `_run()` selects transport: HTTP (`transport="http", host=127.0.0.1, port=…`) when `MOCK_MCP_HTTP_PORT` set, else stdio default; `__main__` calls `_run()` (Part A).
- `agent/agent.py` — `_mock_mcp_server()` returns `MCPServerStreamableHTTP(MOCK_MCP_URL)` when `MOCK_MCP_URL` set, else `MCPServerStdio(timeout=30)`; new `_run_with_mcp_degradation()` wraps `agent.run_sync` and retries once without the MCP toolset(s) on failure (`_MCP_TOOLSET_TYPES`) (Parts A + B).
- `recall/official_blocks.py` — `OFFICIAL_UNAVAILABLE_ALERT`, `is_official_fully_unavailable()`, `build_official_unavailable_blocks()`; `build_official_blocks()` leads with the alert when every relevant feed is down (Part C).
- `recall/__init__.py` — re-export the three new official-blocks symbols.
- `listeners/recall_reply.py` — `_OFFICIAL_UNAVAILABLE_CONTEXT_NOTE` + `_info_need_official_content()`; info-need branch threads the alert into `llm_context` and renders the alert block when official info is fully unavailable (read raised, or all relevant feeds down) (Part C).
- `deploy/entrypoint.sh` (new) — starts the HTTP mock server in the background, waits for the port to bind (Python socket probe, no curl dep), exports `MOCK_MCP_URL`, `exec`s `app.py`; `set -euo pipefail`, shellcheck-clean.
- `Dockerfile` — runtime `CMD ["/app/deploy/entrypoint.sh"]`; docstring updated.
- `.dockerignore` — `deploy/*` + `!deploy/entrypoint.sh` so only the entrypoint enters the image (secrets still excluded).
- `.env.example`, `deploy/README.md` — document the persistent-HTTP transport + the new env vars.
- Tests: `tests/unit/mocks/test_server.py` (transport selection), `tests/unit/agent/test_run_agent_toolsets.py` (HTTP/stdio factory + Part B degradation), `tests/unit/recall/test_official_blocks.py` (Part C composer), `tests/unit/listeners/test_recall_reply.py` (Part C llm_context + blocks; updated the old "empty blocks" info-need test to the new degraded-loud contract), `tests/integration/mocks/test_server_http.py` (new: real HTTP round-trip via `MCPServerStreamableHTTP`).

**Tests**
- Unit: 532 passing, 0 failing (`make pre-commit`). Full suite (unit + integration): 538 passing, 1 skipped (live-provider parse, no key), 0 failing. Zero warnings (`filterwarnings=error`). Double-run stable.
- Integration: 6 (1 new HTTP round-trip + 5 existing session + 1 skipped live).

**Acceptance criteria**
- [x] AC1 — `tests/unit/mocks/test_server.py::test_run_uses_http_transport_when_port_set`, `::test_run_uses_stdio_transport_by_default`, `::test_run_http_port_is_coerced_to_int`.
- [x] AC2 — `tests/unit/agent/test_run_agent_toolsets.py::test_mock_mcp_server_is_http_when_url_set`, `::test_mock_mcp_server_is_stdio_when_url_unset`, `::test_mock_mcp_server_removed_by_kill_switch`, `::test_run_agent_uses_http_mock_when_url_set`.
- [x] AC3 — `tests/unit/agent/test_run_agent_toolsets.py::test_mcp_toolset_failure_does_not_raise_and_reply_still_composes`, `::test_mcp_failure_drops_all_mcp_toolsets_on_retry`, `::test_retry_failure_still_propagates_not_an_mcp_swallow_all`, `::test_non_mcp_failure_with_no_mcp_toolsets_does_not_retry`.
- [x] AC4 — `tests/unit/recall/test_official_blocks.py::test_all_relevant_feeds_down_renders_explicit_alert_block`, `::test_build_official_unavailable_blocks_is_loud_and_button_free`, `::test_build_official_unavailable_blocks_never_asserts_safety`, `::test_is_official_fully_unavailable_*`; `tests/unit/listeners/test_recall_reply.py::test_info_need_situation_read_failure_renders_explicit_alert`, `::test_info_need_all_relevant_feeds_down_threads_alert_into_context`, `::test_info_need_available_feed_does_not_thread_the_alert`.
- [x] AC5 — `deploy/entrypoint.sh` + Dockerfile CMD (code-evident); shellcheck-clean; real entrypoint flow exercised end-to-end (started HTTP mock, waited for bind, exported `MOCK_MCP_URL`, exec'd a stand-in app that saw the env).
- [x] AC6 — 4-guardrail recheck below.
- [x] AC7 — green, zero warnings, double-run stable (above).
- [ ] AC8 — [HUMAN] live after redeploy.

**Guardrail recheck (AC6 — mandatory, Part C touches degraded-states + llm_context)**
1. **A human decides; agent surfaces and ranks.** Unchanged. The degraded alert card and `build_official_unavailable_blocks` carry NO action buttons (asserted: `test_build_official_unavailable_blocks_is_loud_and_button_free`, `test_info_need_situation_read_failure_renders_explicit_alert` checks no `actions` block). No auto-action introduced.
2. **Never assert safety.** The alert states the gap and says "verify directly"; it never says a road is safe/okay to travel and never answers yes/no. Asserted: `test_alert_text_refuses_safety_and_points_to_verify`, `test_build_official_unavailable_blocks_never_asserts_safety`, and the info-need test checks the combined block+context text for "safe to travel"/"okay to travel". The `_OFFICIAL_UNAVAILABLE_CONTEXT_NOTE` explicitly instructs the model "Do NOT assert that any road or travel is safe."
3. **Every item is sourced and timestamped.** Unchanged for live items (per-feed cards still carry feed/fetched-at + verify). The degraded alert is not a data item (it asserts no status), so it carries the verify note rather than a fabricated source — honest absence, not invented sourcing.
4. **Degraded states are explicit.** This is the core of Part C: a wholesale read failure or all-relevant-feeds-down now renders a loud, plain user-facing alert in BOTH the blocks and the llm_context, instead of silence or an implied-complete answer. The per-feed "feed unavailable" cards still render too. Part B reinforces it: a flaky MCP source degrades (retry without it) rather than crashing the reply; the official cards come from the direct `read_situation` path so they still render. Never invents/guesses to fill the gap (`_OFFICIAL_UNAVAILABLE_CONTEXT_NOTE`: "do NOT invent or guess any status").

**Evidence**
```
$ make pre-commit
... 532 passed in 1.89s
$ make integration-tests
... 5 passed, 1 skipped in 0.92s   (+ new test_server_http.py: 1 passed)
$ make test            # full suite, double-run stable
... 538 passed, 1 skipped in 2.80s   /   538 passed, 1 skipped in 2.29s
$ shellcheck deploy/entrypoint.sh
SHELLCHECK CLEAN
$ MOCK_MCP_HTTP_PORT=8804 deploy/entrypoint.sh   (exec swapped to a stand-in app)
>> Starting persistent mock MCP server over HTTP on 127.0.0.1:8804
>> Waiting for the mock MCP server to bind…
>> Mock MCP server is up; agent will connect to http://127.0.0.1:8804/mcp
>> Starting the agent (socket mode) — exec app.py
APP SEES MOCK_MCP_URL = http://127.0.0.1:8804/mcp
# live MCPServerStreamableHTTP connect → TOOLS: get_evac_centres, get_official_advice, get_road_closures; get_road_closures call OK
```

**Notes**
- pydantic-ai 1.x deprecates `MCPServerStdio` / `MCPServerStreamableHTTP` in favour of `MCPToolset` (a v2 change). Both are the classes in use today (agent.py) and the task pins them, so I kept them. Tests that instantiate them directly suppress the `DeprecationWarning` via a scoped `warnings.catch_warnings()` fixture (mirrors `agent.agent._vertex_model`'s existing targeted suppression) so `filterwarnings=error` stays satisfied. Migrating to `MCPToolset` is a separate, out-of-scope change.
- The entrypoint uses `#!/usr/bin/env bash` + `set -euo pipefail` (Debian slim ships `/bin/bash`); port-bind wait uses a Python socket probe (no curl/nc dependency in the slim image).
- `MOCK_MCP_HTTP_PORT` / `MOCK_MCP_URL` are set by the entrypoint inside the container; operators do not set them in `deploy/.env.deploy` (documented). Local `slack run` sets neither → stdio path, unchanged.
- Behavioural change to a pre-existing test: `test_info_need_situation_read_failure_yields_no_blocks` (which asserted empty blocks on a wholesale read failure for an info need) was renamed/rewritten to `test_info_need_situation_read_failure_renders_explicit_alert` — the new Part C contract requires a loud alert there, not silence. Resource-need read-failure behaviour is unchanged (workspace matches stand, no official section), preserving `test_situation_read_failure_does_not_break_the_need_reply`.
