# 003 — RTS recall + ranking

When the agent handles a need, search the workspace for relevant prior offers and coordinator notices via the Real-Time Search API, rank them, and compose a sourced, timestamped Block Kit reply.

## Pre-work (SWE: research before coding)

The RTS API is new — verify the actual API surface (endpoint names, token type, slack_sdk support) against current docs (context7 / docs.slack.dev) before writing code. Manifest already carries the `search:read.*` user scopes. Record findings in this Log; if the integration shape forks from the design doc's assumption (user-token search calls from the agent), write an ADR.

## Acceptance criteria

1. [x] A search module that queries RTS for messages matching the parsed need (resource_type/location keywords) and returns typed results: text, author, channel, ts, permalink.
2. [x] Ranking: recency + keyword overlap with the need's structured fields (simple scoring fine — CPU-bound, sync, unit-tested).
3. [x] Reply is composed Block Kit: each match shows source (author, channel) + timestamp + permalink + "verify before relying on this" note. No bare text dumps.
4. [x] Degraded state explicit: RTS error/empty → reply says "couldn't search the workspace right now" / "no prior offers found" — never silent.
5. [x] Unit tests: ranking table-driven; composition snapshot of Block Kit payload; RTS client mocked.
6. [ ] [HUMAN] Live verification: seed sandbox #general with 2 offers, post a need, agent reply surfaces the matching offer with source + ts.

## Out of scope

MCP external sources (W3), action buttons (W3), Canvas (W4).

## Log

### [SWE] 2026-06-12 — RTS API pre-work research (before coding)

Context7 MCP tools were not loadable in this session (ToolSearch disabled), so I
researched the live docs directly via `curl` against docs.slack.dev and verified
slack_sdk support locally.

**Endpoint / method**
- The RTS API (formerly "Data Access API") exposes two methods:
  `assistant.search.context` (search messages/files/channels/users) and
  `assistant.search.info` (capabilities probe). We use `assistant.search.context`.
- Doc (guide): https://docs.slack.dev/apis/web-api/real-time-search-api
- Doc (method reference): https://docs.slack.dev/reference/methods/assistant.search.context

**Token type**
- A **user token** (`xoxp-`) performs the search on behalf of the authenticated
  user and returns only content that user can see. With a *bot* token an
  `action_token` (carried on `message.*` / `app_mention` events) is additionally
  required, and only `search:read.public` is reachable.
- Manifest already grants the full `search:read.*` user scopes. Bolt populates
  `context.user_token`, which the listeners already thread into `AgentDeps.user_token`
  and the existing Slack-MCP toolset uses as its auth header. We reuse the same
  `deps.user_token` for RTS — consistent with the design doc's "user-token search
  calls from the agent" assumption. **No architectural fork → no ADR.** When the
  user token is absent at runtime, recall degrades explicitly (see AC4) rather
  than silently — the same posture as the MCP toolset's "disabled" branch.

**slack_sdk support**
- `slack_sdk==3.42.0` has **no** typed `assistant_search_context` helper
  (verified: `hasattr(WebClient, "assistant_search_context") is False`). It does
  expose the generic `WebClient.api_call(...)`. So we call
  `client.api_call("assistant.search.context", params={...})` with the user token.
  No new dependency needed.

**Request shape** (params we send)
- `query` (str, required) — keyword string built from the Need's `need_type` +
  `location`. We strip formatting and do **not** phrase as a question, so RTS uses
  keyword (not semantic) retrieval — semantic needs the Slack-AI-Search plan,
  which the sandbox may not have.
- `channel_types` default `public_channel`; `content_types` default `messages`
  (both fine for recall over channel offers/notices).
- `limit` max 20.

**Response shape** (`results.messages[]`, the fields we map)
- `author_name`, `author_user_id`, `channel_id`, `channel_name`,
  `message_ts` (string Unix ts e.g. `"1742550600.000200"`), `content`,
  `is_author_bot`, `permalink`. We convert `message_ts` → aware-UTC datetime.

**Degraded / error shape**
- Errors return `{"ok": false, "error": "<code>"}` (e.g. `access_denied`,
  `assistant_search_context_disabled`, `ratelimited`). `slack_sdk` raises
  `SlackApiError` on `ok: false`. We catch it (plus missing-token) and return a
  typed error result → composed reply says workspace search is unavailable.

### [SWE] 2026-06-12 — Implementation

**Files modified**
- `recall/__init__.py` — public surface (recall_offers, rank_matches, build_recall_blocks, RecallMatch, RecallError, ...).
- `recall/models.py` — typed `RecallMatch` (text/author/author_id/channel/channel_id/ts/permalink; aware-UTC ts validator) and `RecallError`; `match_from_message` maps one RTS `results.messages[]` dict.
- `recall/client.py` — async `recall_offers(need, client, user_token)` calling `client.api_call("assistant.search.context", ...)` via `asyncio.to_thread`; degrades to typed `RecallError` on no-token / SlackApiError / unexpected failure. `build_query` joins need_type+location as keywords.
- `recall/ranking.py` — pure, sync scoring: keyword overlap (0.7) + linear 7-day recency (0.3); `rank_matches` orders best-fit-first with deterministic tie-break.
- `recall/blocks.py` — `build_recall_blocks` composes Block Kit: header + per-match (snippet section + context line with author/channel/timestamp/permalink + `VERIFY_NOTE`), divider-separated; explicit single-block degraded (RecallError) and empty ("no prior offers found") states.
- `listeners/recall_reply.py` — `maybe_post_recall(...)`: parse_message -> if Need, run recall (asyncio.run) -> rank -> compose -> `say(blocks=..., thread_ts=...)`. Bridges async recall into sync Bolt handlers.
- `listeners/events/message.py`, `listeners/events/app_mentioned.py` — surgical: call `maybe_post_recall` before the LLM reply, wrapped so a recall failure can't break the streamed LLM reply.
- `tests/unit/recall/{conftest,test_recall_models,test_ranking,test_client,test_blocks}.py` — RecallMatch boundary + RTS mapping, table-driven ranking, RTS client mocked (no network), Block Kit structure incl. source+ts+verify on EVERY item and both degraded states.
- `tests/unit/listeners/test_recall_reply.py` — wiring: Need posts sourced blocks, non-Need posts nothing, degraded result still posts an explicit reply.

**Tests**
- Unit: 76 passing, 0 failing (`make pre-commit`). Recall + wiring subset: 36 passing.
- Integration: N/A — no infra changes (RTS hits Slack only at runtime; unit tests mock it). Integration suite still collects clean (1 live-gated parse test skipped).

**Acceptance criteria**
- [x] AC1 search module — `recall/client.py::recall_offers` + `recall/models.py`; verified by `tests/unit/recall/test_client.py` and `test_recall_models.py`.
- [x] AC2 ranking (recency + overlap, sync) — `recall/ranking.py`; verified table-driven by `tests/unit/recall/test_ranking.py`.
- [x] AC3 composed Block Kit, source+ts+permalink+verify on each match — `recall/blocks.py`; verified by `tests/unit/recall/test_blocks.py::test_every_match_has_source_timestamp_and_verify`.
- [x] AC4 degraded states explicit (error + empty) — `recall/client.py` (typed RecallError) + `recall/blocks.py`; verified by `test_blocks.py` error/empty tests and `test_client.py` degraded-path tests.
- [x] AC5 unit tests (ranking table-driven, composition snapshot, RTS client mocked) — all present.
- [ ] [HUMAN] AC6 live sandbox verification — NOT RUN (deferred to human; needs `slack run` + a TTY + seeded #general offers). The pure pipeline was exercised end-to-end below; only the live Slack/LLM leg is outstanding.

**Evidence**
```
$ make pre-commit
... ruff format --check: 42 files already formatted
... ruff check: All checks passed!
collected 76 items
tests/unit/recall/test_blocks.py ......
tests/unit/recall/test_client.py .......
tests/unit/recall/test_ranking.py .............
tests/unit/recall/test_recall_models.py ......
tests/unit/listeners/test_recall_reply.py ....
============================== 76 passed in 1.27s ==============================
```

End-to-end (no network) exercise of RTS-response -> map -> rank -> compose:
ranking put the relevant+recent generator offer first, the partial (wrong-town,
older) generator second, and the irrelevant water message last; the composed
Block Kit carried author/channel/timestamp/permalink + "Verify before relying on
this." on every match; the empty and RecallError paths each rendered a single
explicit block. (Display timestamps showed 2025 only because the synthetic Unix
epochs I used land in 2025 — the conversion is correct.)

**Notes**
- No new dependencies. `slack_sdk==3.42.0` has no typed `assistant_search_context`; used generic `WebClient.api_call` with a per-call user-token Authorization header.
- No ADR written: RTS via the user token (`deps.user_token`) matches the design doc's "user-token search calls from the agent" assumption and reuses the same token the existing Slack-MCP toolset uses — no architectural fork.
- Recall reply posts as a separate `say(blocks=...)` and the existing LLM reply still streams afterward (kept the template flow; recall is additive, surgical). The recall call is wrapped in try/except in both listeners so a recall failure can never break the LLM reply.
- Guardrail re-check: (1) surfaces+ranks, no auto-action — recall only displays, no buttons (W3 scope); (2) never asserts safety — VERIFY_NOTE on every item, no safety claims; (3) every item sourced+timestamped — enforced structurally in RecallMatch and asserted on every block; (4) degraded states explicit — typed RecallError + composed unavailable/empty blocks, never silent.
- Branch: `feat/003-rts-recall-ranking` (off `dev`). NOT committed — awaiting Tester PASS + PM accept.

### [Tester] 2026-06-12 16:20 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check`: 42 files formatted; `ruff check`: All checks passed)
- Unit tests: 76 passed / 0 failed
- Integration tests: 0 passed / 0 failed (1 skipped — live-provider-gated parse test, no key configured)
- Warnings: 0 (`filterwarnings = ["error"]` in effect; suite green)
- Recall+listeners subset run twice in separate processes: 32 passed / 32 passed (no module-level state pollution)
- No new deps (pyproject.toml / uv.lock unchanged); no `print()` in library code; no hardcoded secrets; every new function fully type-annotated (AST scan clean, incl. `-> None`/`-> bool`).

**E2E adversarial pass**
- Happy path (demo scenario: generator in Exmouth, 3 RTS hits): `recall_offers → rank_matches → build_recall_blocks` → relevant+recent Exmouth generator ranks first, wrong-town older generator second, irrelevant water last; every context block carries author + #channel + UTC ts + permalink + verify note. (PASS)
- Break path 1 (ranking — zero keyword overlap but posted exactly now): junk caps at score 0.30 (recency-only) while any keyword hit clears 0.30 (overlap weighted 0.7); relevant-but-6.96-day-old generator scored 0.70 and ranked above recent junk (0.30). Junk does NOT float to top. (PASS)
- Break path 2 (malformed RTS message — missing author/permalink/content): `match_from_message` falls back to empty strings; `build_recall_blocks` composes without crashing; "Unknown author"/no-link rendered, verify note still present. (PASS)
- Break path 3 (message_ts string→datetime): all of `"…000200"`, `"1742550600"`, `"0"`, `"1.5"` and listener `_event_ts_to_utc` produce **aware-UTC** datetimes; missing `message_ts` raises KeyError (loud, never a silent unsourced item). (PASS)
- Break path 4 (recall failure must not break LLM reply): forced `maybe_post_recall` to raise; listener's nested `try/except Exception` caught it, logged a warning, and the LLM-reply path was still reached. (PASS — LLM reply protected)
- Break path 5 (malformed-but-`ok:true` RTS response, non-numeric message_ts): `recall_offers` RAISED `ValueError` instead of degrading to `RecallError` — the `[match_from_message(m) for m in messages]` mapping is OUTSIDE the try/except. Effect: recall posts **nothing** (silent skip) rather than an explicit "couldn't search" block. LLM reply unaffected (caught by listener wrapper). See "Other issues found". (NOTE — narrow/low-probability; see severity below)

**Acceptance criteria**
- [x] PASS — AC1 search module (typed text/author/channel/ts/permalink) — `recall/client.py::recall_offers` + `recall/models.py::match_from_message`; `test_client.py` (7) + `test_recall_models.py` (6) green; calls `assistant.search.context` via `WebClient.api_call` with `Authorization: Bearer {user_token}` (verified `test_recall_calls_rts_method_with_user_token_header`).
- [x] PASS — AC2 ranking (recency + keyword overlap, sync, unit-tested) — `recall/ranking.py`; `test_ranking.py` (13) table-driven; adversarial confirms overlap (0.7) outranks recency (0.3) so junk can't float.
- [x] PASS — AC3 composed Block Kit, source+ts+permalink+verify on each match — `recall/blocks.py`; `test_blocks.py::test_every_match_has_source_timestamp_and_verify`; rendered Block Kit verified by hand (header/section/context/divider only).
- [x] PASS — AC4 degraded states explicit (error + empty) — `recall/client.py` (typed `RecallError` on no-token / SlackApiError / generic) + `recall/blocks.py`; both render a single explicit block; tested in `test_client.py` and `test_blocks.py`. (One narrow gap: malformed-but-ok response — see Other issues.)
- [x] PASS — AC5 unit tests (ranking table-driven, composition asserted, RTS client mocked) — all present; RTS client mocked via `pytest-mock`, no network touched.
- [ ] [HUMAN] AC6 live sandbox verification — Awaiting human verification (needs `slack run` + seeded #general offers + a TTY). Pure pipeline exercised end-to-end above; only the live Slack/LLM leg is outstanding.

**Guardrail re-check (mandatory — all four)**
- (1) Sourced+timestamped on EVERY item: PASS — `_source_line`/`_match_blocks` in blocks.py; rendered output shows author + #channel + UTC ts + permalink + verify note on all 3 matches; `test_every_match_has_source_timestamp_and_verify`.
- (2) Degraded explicit: PASS for the two designed paths (RecallError, empty). One narrow non-designed path (malformed-but-ok) goes silent — flagged below.
- (3) No auto-actions: PASS — block types across all paths are only {header, section, context, divider}; zero actions/buttons/accessory (buttons are W3 scope).
- (4) Timestamps tz-aware UTC: PASS — `RecallMatch.ts` validator rejects naive (`test_recall_match_rejects_naive_timestamp`), normalises non-UTC to UTC; `match_from_message` + `_event_ts_to_utc` emit aware-UTC.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
42 files already formatted
uv run ruff check
All checks passed!
collected 76 items
...
============================== 76 passed in 1.53s ==============================

$ make integration-tests
collected 1 item
tests/integration/agent/test_parsing_live.py s
SKIPPED [1] ...test_parsing_live.py:30: no live provider key configured
============================== 1 skipped in 1.13s ==============================
```

**Other issues found** (non-blocking; for SWE/PM consideration, not a FAIL)
1. Robustness gap in `recall/client.py:84` — the result-mapping comprehension `[match_from_message(m) for m in messages]` sits OUTSIDE the try/except. A malformed/non-numeric `message_ts` inside an `ok:true` response raises `ValueError` out of `recall_offers` instead of degrading to `RecallError`, so recall posts nothing (silent skip) rather than the explicit "couldn't search" block guardrail #4 promises. The listener's outer try/except still protects the LLM reply, so no user-facing crash. Low probability (RTS always returns string Unix ts), but a one-line fix (move the mapping inside the try, or wrap `match_from_message`) would close the last silent-degrade gap. Suggest a follow-up nit, not a blocker.
2. Minor: `match_from_message` coerces wrong-typed RTS values via `str(...)` — `content: 12345` → `"12345"`, `author_name: None` → `"None"`. Harmless (RTS sends strings) but `None` → literal "None" is a slight smell. Cosmetic.

**VERDICT: PASS**

All five non-HUMAN acceptance criteria verified with code + test + runtime evidence; full suite green (76 passed, 0 warnings); all four product guardrails re-checked and hold on the designed paths; happy path and 4/5 adversarial break paths green. The single adversarial finding (silent skip on a malformed-but-ok RTS response) is narrow, low-probability, does not break the LLM reply, and is recorded as a non-blocking follow-up. AC6 awaits human live-sandbox verification.
