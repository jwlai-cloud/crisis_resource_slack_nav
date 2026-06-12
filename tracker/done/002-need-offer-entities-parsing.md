# 002 — Need/Offer entities + structured parsing

Create the typed core from design doc §6 and a parsing path from free text to those types using pydantic-ai structured output.

## Acceptance criteria

1. `entities/` package with Pydantic models:
   - `Need`: id, requester, need_type, location, urgency, household_size, status (open/matched/resolved), source_ts
   - `Offer`: id, offerer, resource_type, location, availability, status, source_ts
   - `Resolution`: need_id, offer_id, confirmed_by, timestamp
2. Enums for status + urgency; `source_ts` timezone-aware UTC (naive datetimes rejected by validator — guardrail: timestamps are product requirements).
3. Deterministic ids (UUID5 from requester+ts or similar), not bare uuid4.
4. `agent/parsing.py` (or equivalent): `parse_message(text, author, ts) -> Need | Offer | NotACrisisMessage` using pydantic-ai with `output_type` — typed result, no JSON scraping.
5. Unit tests: model validation (incl. naive-datetime rejection), parametrized parse cases mocked via pydantic-ai `TestModel`/`FunctionModel` — no live LLM in unit tests.
6. Integration test (optional, marked): one live parse against the configured model.

## Out of scope

Indexing/storage (003), wiring into listeners (003/004).

## Log

### [SWE] 2026-06-12 13:23 — Implementation

**Files created**
- `entities/__init__.py` — package re-exports (Need, Offer, Resolution, Status, Urgency, deterministic_id, PROJECT_NAMESPACE).
- `entities/models.py` — the typed core from design doc §6: `Need`, `Offer`, `Resolution`; `Status`/`Urgency` StrEnums; `_ensure_aware_utc` field validator (rejects naive datetimes, normalises aware ones to UTC); `deterministic_id()` (UUID5 over a pinned project namespace + author|source_ts.isoformat()).
- `agent/parsing.py` — `parse_message(text, author, ts) -> Need | Offer | NotACrisisMessage` via a dedicated pydantic-ai `Agent` (`parsing_agent`) with a union `output_type` and a small focused parsing prompt (NOT the big system prompt). `ParsedNeed`/`ParsedOffer`/`NotACrisisMessage` are the model's output models; author/ts/id are threaded in by us (trust-critical source fields), not extracted by the model.
- `tests/unit/entities/test_models.py` — model validation + naive-datetime rejection + deterministic-id stability/uniqueness/zone-collision.
- `tests/unit/agent/test_parsing.py` — parse cases (need / offer / chit-chat→NotACrisisMessage / naive-ts rejection / deterministic-id stability) driven by `FunctionModel` under `parsing_agent.override(...)` — no live LLM.
- `tests/unit/agent/conftest.py` — autouse fixtures: dummy provider key (so `get_model()` resolves; override still wins so no real call) + a current-event-loop fixture (pydantic-ai `run_sync` calls `asyncio.get_event_loop()`, which warns on 3.12+; our `filterwarnings=["error"]` would otherwise escalate it).
- `tests/integration/agent/test_parsing_live.py` — AC #6 optional live parse, `@pytest.mark.live`, skips unless a provider key is present.

**Files modified**
- `pyproject.toml` — registered the `live` pytest marker (required by `--strict-markers`).

**Design notes**
- **Naive-datetime rejection** is a `field_validator` shared by all three models (`source_ts` / `timestamp`); aware non-UTC values are normalised to UTC rather than rejected, so all stored timestamps are comparable. This is the "every item sourced and timestamped" guardrail enforced structurally.
- **Deterministic ids**: UUID5 from a pinned `PROJECT_NAMESPACE` + `f"{author}|{source_ts-as-UTC-isoformat}"`. Re-parsing the same Slack message yields the same id → idempotent re-parsing, no duplicate Needs/Offers in the matching index. `source_ts` is normalised to UTC first, so two zone representations of the same instant collide on purpose. Documented in the module/function docstrings.
- **Parsing agent** is intentionally separate from `agent.agent.agent` and uses its own tight prompt + constrained union output type. `agent/agent.py` was not touched. `parse_message` selects the model via the existing `get_model()`; pydantic-ai `override(model=...)` takes precedence in tests, so unit tests never hit a provider.
- **No new runtime deps** — `pydantic-ai[anthropic]` and `pydantic` were already present.

**Tests**
- Unit: 40 passing, 0 failing (`make pre-commit` / `make unit-tests`).
- Integration: 1 (`test_parsing_live`), skipped without a provider key — runs locally with a real key.

**Acceptance criteria**
- [x] AC1 — `entities/` package with Need/Offer/Resolution and the exact fields — `tests/unit/entities/test_models.py`.
- [x] AC2 — Status/Urgency enums + naive-datetime rejecting validator — `test_need_rejects_naive_source_ts`, `test_offer_rejects_naive_source_ts`, `test_resolution_rejects_naive_timestamp`, `test_aware_non_utc_source_ts_normalised_to_utc`.
- [x] AC3 — deterministic UUID5 ids, not uuid4 — `test_deterministic_id_is_uuid5_in_project_namespace`, `test_deterministic_id_is_stable_across_calls`, plus uniqueness/zone-collision tests.
- [x] AC4 — `agent/parsing.py` `parse_message(...) -> Need | Offer | NotACrisisMessage` via pydantic-ai `output_type`, typed result, no JSON scraping — `tests/unit/agent/test_parsing.py`.
- [x] AC5 — unit tests incl. naive-datetime rejection, parametrized parse cases mocked via `FunctionModel` — no live LLM — `tests/unit/agent/test_parsing.py`.
- [x] AC6 (optional) — one live parse, marked `live` — `tests/integration/agent/test_parsing_live.py`.

**Evidence**
```
$ make test   # CI-style, no provider keys
collected 41 items
tests/unit/agent/test_parsing.py .....                                   [ 12%]
tests/unit/entities/test_models.py .................                     [ 53%]
tests/unit/test_app_home_opened.py ..                                    [ 58%]
tests/unit/test_system_prompt.py ............                            [ 87%]
tests/unit/test_view_builders.py ....                                    [ 97%]
tests/integration/agent/test_parsing_live.py s                           [100%]
======================== 40 passed, 1 skipped in 1.70s =========================

$ make format-check && make lint-check
30 files already formatted
All checks passed!

# End-to-end (live model, key from environment) — parse three real messages:
U_RESIDENT "We are out of drinking water in Exmouth, 4 of us, baby needs formula, urgent"
  -> Need(need_type='drinking water, baby formula', location='Exmouth', urgency=HIGH, household_size=5, status=open, source_ts=2026-03-14T09:30:00+00:00)
U_VOLUNTEER "I have a spare petrol generator in Learmonth, can drop it off this afternoon"
  -> Offer(resource_type='petrol generator', location='Learmonth', availability='this afternoon', status=open)
U_CHATTER "morning all, hope everyone stayed safe through the night"
  -> NotACrisisMessage(reason='Greeting')
```

**Notes**
- Did NOT touch `agent/agent.py`, `listeners/`, the manifest, or other tasks' scope. Indexing/storage and listener wiring are out of scope (003/004).
- Test layout: my tests mirror the source tree under `tests/unit/entities/` and `tests/unit/agent/`; existing flat unit tests (`test_system_prompt.py`, etc.) left where they are.
- The `live` marker was added to `pyproject.toml` purely to satisfy `--strict-markers` for the optional integration test; no other config changed.
- Not committed — left in the working tree for Tester review.

### [Tester] 2026-06-12 14:10 — QA

**Test summary** (all runs with `env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_API_KEY`)
- Format / lint / pre-commit: PASS (`30 files already formatted`, `All checks passed!`)
- Unit tests: 40 passed / 0 failed
- Integration tests: 0 passed / 0 failed / 1 skipped (live test correctly skips with no provider key)
- Warnings: 0 (`filterwarnings=["error"]` active; clean)

**E2E adversarial pass**
- Happy path (need): `FunctionModel` emits `ParsedNeed` → `parse_message` returns `Need(requester=U, source_ts=TS, id=uuid5, urgency=CRITICAL, status=OPEN)` (PASS)
- Happy path (offer / chit-chat): emit `ParsedOffer`→`Offer`, emit `NotACrisisMessage`→marker (PASS)
- Break path 1 (enum: invalid values): `urgency="apocalyptic"` and `status="cancelled"` → `ValidationError` rejected (PASS)
- Break path 2 (boundary: empty text): model returns `NotACrisisMessage` → handled, no crash (PASS)
- Break path 3 (malformed model output: invalid urgency from the LLM): `Need(...)` wrap raises `ValidationError` that propagates to the caller — fail-closed, never fabricates an enum (PASS; see Other issues for the listener-layer note)
- Break path 4 (datetime guardrail): naive `ts` into `parse_message` and into all three models → rejected with "timezone-aware" message (PASS); aware non-UTC (Perth +08) normalised to UTC, not rejected (PASS)
- Break path 5 (conftest state pollution): full unit suite run twice in one invocation, and agent-module-then-flat-module ordering → 40 passed, no leakage; agent autouse fixtures (dummy key + event loop) are dir-scoped and invisible to `tests/unit/entities/` (verified: entities-only run never sees `ANTHROPIC_API_KEY`) (PASS)

**Acceptance criteria**
- [x] AC1 PASS — `entities/` package with `Need`/`Offer`/`Resolution` and the exact §6 fields. Verified field-by-field against design doc §6 (lines 83-85) in `entities/models.py:68-109`: Need(id, requester, need_type, location, urgency, household_size, status, source_ts); Offer(id, offerer, resource_type, location, availability, status, source_ts); Resolution(need_id, offer_id, confirmed_by, timestamp). All typed (UUID/str/enum/int/datetime). `tests/unit/entities/test_models.py` 17 passing.
- [x] AC2 PASS — `Status`/`Urgency` `StrEnum`s (`models.py:26-40`); `_ensure_aware_utc` field validator rejects naive datetimes on Need.source_ts, Offer.source_ts, Resolution.timestamp. Proven via direct snippet: all three raise `ValidationError` containing "timezone-aware"; aware non-UTC normalised to UTC. Tests: `test_need/offer_rejects_naive_source_ts`, `test_resolution_rejects_naive_timestamp`, `test_aware_non_utc_source_ts_normalised_to_utc`.
- [x] AC3 PASS — `deterministic_id` is UUID5 over pinned `PROJECT_NAMESPACE` + `f"{author}|{utc-isoformat}"` (`models.py:56-65`), not uuid4. Proven: same (author, ts) twice → same id; `.version == 5`; differs by author/ts; same instant in different zones → same id; rejects naive ts.
- [x] AC4 PASS — `agent/parsing.py:72` `parse_message(text: str, author: str, ts: datetime) -> Need | Offer | NotACrisisMessage` via dedicated `parsing_agent` with union `output_type=[ParsedNeed, ParsedOffer, NotACrisisMessage]` (`parsing.py:66-69`). Typed result, no JSON/regex scraping. author/ts/id threaded in by us, not model-extracted.
- [x] AC5 PASS — unit tests incl. naive-datetime rejection and parametrized parse cases driven by `FunctionModel` under `parsing_agent.override(...)`. No live LLM: full suite passes with ALL provider keys unset; `get_model()` resolved via dummy key in dir-scoped conftest, override takes precedence.
- [x] AC6 PASS (optional) — `tests/integration/agent/test_parsing_live.py`, `@pytest.mark.live`, skips without a provider key (confirmed: `SKIPPED ... no live provider key configured`). `live` marker registered in `pyproject.toml` for `--strict-markers`.

**Evidence**
```
$ env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_API_KEY make pre-commit
30 files already formatted
All checks passed!
collected 40 items
tests/unit/agent/test_parsing.py .....                                   [ 12%]
tests/unit/entities/test_models.py .................                     [ 55%]
tests/unit/test_app_home_opened.py ..                                    [ 60%]
tests/unit/test_system_prompt.py ............                            [ 90%]
tests/unit/test_view_builders.py ....                                    [100%]
============================== 40 passed in 3.20s ==============================

$ env -u ...all keys... make integration-tests
SKIPPED [1] tests/integration/agent/test_parsing_live.py:30: no live provider key configured
============================== 1 skipped in 1.18s ==============================
```
Guardrail snippet (no keys): Need/Offer/Resolution all reject naive → "timezone-aware" True; deterministic_id stable + version=5; zone collision True; non-UTC normalised to UTC True.

**Other issues found** (none blocking — all outside this task's ACs)
- `entities/models.py`: `household_size: int` has no lower bound — accepts `-5` and `0`; `need_type`/`location` accept empty strings. Not in ACs (parser prompt defaults household_size to 1). Suggest a `Field(ge=1)` / non-empty constraint when storage lands (003).
- `agent/parsing.py`: a hallucinated invalid enum from the model surfaces as an uncaught `ValidationError` from the `Need(...)` wrap. Correct fail-closed behaviour here, but the listener layer (003/004) must catch it so a model hallucination can't crash a Slack event handler. Flag for that task, not this one.
- Untracked `.slack/apps.json` (`{}`) is present in the working tree and is NOT gitignored — not part of this task. The SWE must commit only the task files (never `git add -A`); recommend gitignoring `.slack/` or excluding it from the commit.

**VERDICT: PASS**
