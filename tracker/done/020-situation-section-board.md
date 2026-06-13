# 020 — Situation section on the coordinator board

The coordinator Canvas (017) shows community cases + audit log. Add a "Situation"
section rendering the current official picture (road closures / water points / evac
centres) from the mock MCP feeds, each feed-stamped (feed + fetched-at) with the
verify note — the shared official-info artifact the design doc's coordinator beat
implies, so residents' replies can point to it instead of repeating the full dump.

Direction:
1. The board composer gains a situation section sourced from the official feeds.
   The feeds live in mocks/ (road_closures/evac_centres/official_advice JSON via the
   FastMCP tools). The board reads them directly (the JSON loader, not an MCP round
   trip) at compose time — keep board.py pure by passing the situation data in from
   the canvas.py boundary (mirrors the names dict pattern from 019).
2. Every situation row carries feed + fetched-at + verify note (guardrail 3/4).
3. Optional: replies end with a one-line pointer to the board for the full picture
   (pairs with 012's pruning).
4. Tests: situation composition (feed-stamped rows, empty/degraded feed), board
   stays pure. Mock the feed loader. Zero warnings.
5. [HUMAN] live: board shows a Situation section with the Narelle road/water/evac
   data, feed-stamped.

Depends on 017 (board) + 012 (pruning makes the pointer meaningful). W4/W5 polish.

## Log

### [SWE] 2026-06-13 06:00 — Implementation

**Situation-reader design**
- New `coordinator/situation.py`: `read_situation() -> SituationSnapshot`, the
  impure fetch boundary that mirrors the 019 `coordinator/names.py` pattern (best-
  effort helper feeding the pure composer).
- It calls the three mock feed functions (`get_road_closures` /
  `get_evac_centres` / `get_official_advice`) directly and normalizes each into a
  frozen `SituationFeed` dataclass: `feed`, `available`, `fetched_at | None`,
  `records: tuple[...]`, `detail`. A feed that *returned* a `FeedError` (expected
  outage) and a feed that *raised* unexpectedly both degrade to
  `available=False` with a human `detail` — never silence, never a raise. The
  three feeds bundle into a `SituationSnapshot` (one feed per source, all always
  present). Per-feed isolation: one down feed doesn't touch the others.

**coordinator -> mocks coupling note (documented in the module docstring)**
- For the demo the *mock* feeds ARE the official data source. The reader calls the
  feed functions directly — the JSON loader, not an MCP round trip — because the
  board composes synchronously (the stdio MCP session is the agent's path, not the
  board's). That coupling is deliberate and named in one place: **when real MCP
  feeds replace the mocks, `coordinator/situation.py` is the single module that
  changes** (repoint it at the MCP toolset / a feed client). Everything downstream
  only sees the normalized `SituationSnapshot`, so the pure composer and canvas
  publisher are untouched by the swap. Not abstracted behind an interface today
  (no premature abstraction, per CLAUDE.md).

**Files modified**
- `coordinator/situation.py` — NEW: official-feed read boundary + `SituationFeed`
  / `SituationSnapshot` types.
- `coordinator/board.py` — `compose_board_markdown` gains an optional
  `situation: SituationSnapshot | None = None` param (default `None` keeps every
  017/019 caller + test unchanged) and renders a "## Situation — official sources"
  section after the cases + activity log: road closures / evac centres (water point
  in services) / official advice (water-point notice). Each row feed-stamped
  (`_source: <feed> · fetched <ts>`); the section carries its own verify note; a
  down feed renders an explicit named "Feed unavailable: <feed> — ..." line. Stays
  PURE — relays the feed's own status words, never asserts safety.
- `coordinator/canvas.py` — the publish path (`_compose_with_names`) now best-effort
  reads the situation via `_read_situation_best_effort()` and threads it into the
  composer alongside the names dict. A situation-read failure degrades to no
  Situation section (returns `None`), never breaks the board update.
- `coordinator/__init__.py` — export `read_situation` / `SituationSnapshot` /
  `SituationFeed`.
- `tests/unit/coordinator/test_situation.py` — NEW: reader unit tests.
- `tests/unit/coordinator/test_board.py` — added Situation-section composer tests.
- `tests/unit/coordinator/test_canvas.py` — added situation-wiring publish tests.

**Tests**
- Unit: 367 passing, 0 failing (was 348 baseline; +19 new). Zero warnings
  (`filterwarnings=["error"]`).
- Coordinator subset: 91 passing (72 baseline + 6 situation reader + 9 board + 4
  canvas wiring/wiring-overlap).
- Integration: N/A — no infra changes (the reader calls in-process feed functions;
  no Slack / MCP session touched).

**Acceptance criteria** (task uses a numbered Direction list, not `- [ ]` boxes)
- [x] 1. Situation reader returns a typed/normalized structure per feed (name,
  fetched_at, records, or a degraded marker on FeedError); never raises; coupling
  documented — `tests/unit/coordinator/test_situation.py`.
- [x] 2. Every situation row carries feed + fetched-at + verify note (guardrail
  3/4) — `test_situation_rows_carry_feed_and_fetched_at_stamp`,
  `test_situation_section_carries_a_verify_note`.
- [~] 3. Optional reply pointer to the board — NOT IMPLEMENTED. Marked optional in
  the task; it lives in the reply-composition path (recall/listeners), which this
  task is constrained not to touch. Left for a follow-up so this stays scoped to
  the board.
- [x] 4. Tests: feed-stamped rows, empty/degraded feed, board stays pure, feed
  loader mocked, zero warnings — `test_situation.py` + the Situation-section block
  in `test_board.py`.
- [ ] [HUMAN] 5. live: board shows a Situation section with the Narelle
  road/water/evac data, feed-stamped — NOT RUN (needs `slack run` + a real Canvas;
  composed output verified locally below).

**Guardrails re-checked**
- Sourcing (3): every present row ends with `_source: <feed> · fetched <ts>_`.
- Degraded explicit (4): a down feed renders `_Feed unavailable: <feed> — <detail>_`,
  named, never silence. Verified live via `MOCK_FEED_DOWN=road_closures`.
- Never assert safety (2): rows relay the feed's own status word (CLOSED / OPEN
  WITH CAUTION / advice line) verbatim; `test_situation_section_never_asserts_safety`
  pins that "is safe" / "safe to travel" / "okay to travel" never appear.
- Human-decides (1): N/A — the Situation section is a read-only official-info panel,
  no action buttons.

**Evidence**
```
$ make pre-commit
... (tail)
tests/unit/test_view_builders.py ....                                    [100%]
============================= 367 passed in 1.36s ==============================

$ uv run python -c "from coordinator.situation import read_situation; ..."
=== HAPPY PATH: all three Narelle feeds live ===
## Situation — official sources

_Relayed from official feeds, not advice. Always verify the current situation with the official source before relying on it._

### Road closures
- *Minilya-Exmouth Road* — Yannarie River crossing: CLOSED. Floodwater over road; ... _source: road_closures · fetched 2026-06-13 05:46 UTC_
... (Learmonth Access Road UNDER ASSESSMENT, Murat Road OPEN WITH CAUTION) ...

### Evacuation centres
- *Exmouth Recreation Centre* (Murat Road, Exmouth WA 6707) — OPEN, 168/250. Services: Emergency water point, ... _source: evac_centres · fetched ...
... (District High School Hall, Learmonth Community Hall FULL 60/60) ...

### Official advice
- *EMERGENCY WARNING — Exmouth and surrounds* (Emergency Warning) — Stay sheltered. ... _source: official_advice · fetched ...
- *Emergency water point now open — Exmouth Recreation Centre* (Advice) — ... Collect drinking water from the Recreation Centre water point. _source: official_advice · ...

$ MOCK_FEED_DOWN="road_closures" uv run python -c "..."
=== DEGRADED: road_closures feed forced down ===
### Road closures
- _Feed unavailable: road_closures — The road_closures feed is unavailable (simulated outage)._
### Evacuation centres
- *Exmouth Recreation Centre* ... (still rendered) ...
```

**Notes**
- Direction item 3 (reply pointer) deliberately deferred — it is in the reply path
  (recall/listeners), out of this task's allowed file set, and was marked optional.
  Recommend a small follow-up task to add the one-line board pointer once 012's
  pruning is in.
- The composer's `_row_for` dispatches by record type (`isinstance`) so each feed
  renders its own fields; `OfficialAdvice` is the narrowed fall-through branch.
- `fetched_at` shown is the feed's *lookup* time (aware UTC, stamped at call), per
  `FeedResult.fetched_at`; each record additionally carries its own `updated_at`
  (not separately surfaced on the board row to keep it scannable — the lookup
  stamp is the freshness signal a coordinator needs for "is this current").
- DO NOT COMMIT — handing to Tester.

### [Tester] 2026-06-13 07:10 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`88 files already formatted`; `All checks passed!`; pre-commit unit run `367 passed`)
- Unit tests: 367 passed / 0 failed (double-run: 367 both times, stable)
- Integration tests: 5 passed / 1 skipped (live-provider key not configured) — both runs identical
- Warnings: 0 (`filterwarnings=["error"]` in effect)
- `code-review` plugin: not enabled (no `.claude/settings.json`) — manual checklist only.

**E2E adversarial pass** (ran the publisher's real read→compose path, then attacked it)
- Happy path: `read_situation()` over the real Narelle JSON + `compose_board_markdown([], [], situation=snap)` → full Situation section, all 3 feeds, every row feed-stamped (feed + `fetched 2026-06-13 05:49 UTC`), section verify note present, statuses relayed verbatim (CLOSED / UNDER ASSESSMENT / OPEN WITH CAUTION / OPEN / FULL). (PASS)
- Break 1 (degraded: single feed FeedError): `MOCK_FEED_DOWN=road_closures` → `### Road closures` renders `- _Feed unavailable: road_closures — ... (simulated outage)._`; evac + advice still render (per-feed isolation). NAMED, not silent. (PASS)
- Break 2 (degraded: all three down): `MOCK_FEED_DOWN=road_closures,evac_centres,official_advice` → all 3 named-unavailable lines, verify note still present, `unavailable` count 6. (PASS)
- Break 3 (mixed up/empty/down): crafted snapshot road=UP / evac=available-empty / advice=down → UP shows stamped row, EMPTY shows `_No current entries._`, DOWN shows `Feed unavailable: official_advice` — three states render distinctly. (PASS)
- Break 4 (canvas best-effort): `read_situation` patched to raise → `_read_situation_best_effort()` returns `None`; full `_compose_with_names` with offers + situation raising → board still renders the case (`## Open (1)`, resource) + `## Activity log`, NO `## Situation` section. Board update never breaks. (PASS)
- Break 5a (empty real feed JSON): road_closures.json = `[]` via patched DATA_DIR → feed `available=True`, 0 records, renders `_No current entries._`, NOT "unavailable" (empty ≠ down distinction). (PASS)
- Break 5b (`fetched_at` None branch): down feed has `fetched_at=None`; `_feed_stamp` None-fallback emits `_source: road_closures_` (name still carried). (PASS)
- Break 5c (corrupt JSON file): evac_centres.json = garbage via patched DATA_DIR → loader returns `FeedError(feed_unavailable)`, reader degrades evac to `available=False` with a human detail, road stays up; never raises. (PASS)
- Double-run pollution: unit + integration each run twice, identical counts, no order dependence. (PASS)
- Ordering: with offers + situation, top verify note < `## Open` < `## Activity log` < `## Situation`; single trailing newline; section's own verify note also present. (PASS)

**Acceptance criteria** (task uses a numbered Direction list)
- [x] PASS — 1. Situation reader returns a typed/normalized structure per feed; never raises; coupling documented.
      Evidence: `coordinator/situation.py:55-133` (`SituationFeed`/`SituationSnapshot` frozen dataclasses, `_read_feed` try/except + FeedError branch); coupling/MCP-swap note in module docstring `situation.py:9-31`; `tests/unit/coordinator/test_situation.py` 6 tests pass incl. `test_read_situation_never_raises_when_all_feeds_explode`; live probes Break 1/2/5c confirm never-raise + per-feed isolation.
- [x] PASS — 2. Every situation row carries feed + fetched-at + verify note (guardrail 3/4).
      Evidence: `board.py:_feed_stamp` (`_source: <feed> · fetched <ts>_`), `_SITUATION_VERIFY_NOTE`; `test_situation_rows_carry_feed_and_fetched_at_stamp`, `test_situation_section_carries_a_verify_note`; live happy-path shows `_source: road_closures · fetched 2026-06-13 05:49 UTC_` on every row.
- [~] N/A — 3. Optional reply pointer to the board — NOT IMPLEMENTED, explicitly marked optional and deferred (lives in the reply/listeners path, outside this task's file set). Not an AC failure; SWE recommends a follow-up. Acceptable per spec wording "Optional".
- [x] PASS — 4. Tests: feed-stamped rows, empty/degraded feed, board stays pure, feed loader mocked, zero warnings.
      Evidence: `test_situation.py` mocks the three feed fns (`coordinator.situation.get_*`); board purity verified — `board.py` imports only types from situation/mocks, no `read_situation`/loader/IO call (grep clean, sole reference is a docstring); `read_situation()` invoked ONLY at `canvas.py:96`; 367 unit passed, 0 warnings.
- [ ] [HUMAN] 5. live: board shows a Situation section with the Narelle road/water/evac data, feed-stamped — NOT RUN (requires `slack run` + a real Canvas). Awaiting human verification. Composed output verified locally (happy path above) as the strongest available proxy.

**Guardrail re-check (CLAUDE.md — mandatory for guardrail-touching changes)**
- Sourcing (3): PASS — every present row feed-stamped; live + `test_situation_rows_carry_feed_and_fetched_at_stamp`.
- Degraded explicit + NAMED (4): PASS — single-down and all-down both render `_Feed unavailable: <feed> — <detail>_` by name; empty-but-up is a distinct `_No current entries._`; never silence (Break 1/2/5a, `test_down_feed_renders_explicit_unavailable_line_not_silence`, `test_all_feeds_down_renders_three_unavailable_lines`).
- Never assert safety (2): PASS — rows relay the feed's own status words verbatim (CLOSED / OPEN WITH CAUTION / advice line); `test_situation_section_never_asserts_safety` pins "is safe"/"safe to travel"/"okay to travel" absent; no composer-authored safety language.
- Human-decides (1): N/A — read-only official-info panel, no action buttons.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
88 files already formatted
uv run ruff check
All checks passed!
============================= 367 passed in 1.47s ==============================

$ make integration-tests
========================= 5 passed, 1 skipped in 1.02s =========================

$ MOCK_FEED_DOWN="road_closures,evac_centres,official_advice" <compose>
### Road closures
- _Feed unavailable: road_closures — The road_closures feed is unavailable (simulated outage)._
### Evacuation centres
- _Feed unavailable: evac_centres — The evac_centres feed is unavailable (simulated outage)._
### Official advice
- _Feed unavailable: official_advice — The official_advice feed is unavailable (simulated outage)._
```

**Other issues found** (non-blocking, PASS-with-note)
- `_row_for` (`board.py:214`) dispatches by `isinstance` with `OfficialAdvice` as the implicit `else` fall-through. Sound for the 3 wired feeds; if a 4th `FeedRecord` type is ever added without its own branch it would silently render through the advice path. Maintenance smell only — not a defect today. Worth a follow-up if the feed set grows.
- Direction item 3 (reply pointer) deferred — already filed as a SWE follow-up recommendation; orchestrator/PM to decide whether to spin a task.

**VERDICT: PASS**
- Every non-`[HUMAN]` AC verified with evidence; full suite green (367 unit / 5 integration), 0 warnings; e2e adversarial pass green on all 8 break paths incl. the critical degraded-state guardrail; board composer confirmed pure; canvas wiring best-effort; no 017/018/019 regressions; no security/convention violations.
- AC5 [HUMAN] live remains NOT RUN — awaiting human `slack run` verification.
