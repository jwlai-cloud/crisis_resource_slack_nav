# 022 — Slack-native UX: crisis suggested prompts + branded App Home dashboard

Targets the Design / Best-UX prize. Two surfaces are still the generic starter
template and are the FIRST things a user/judge sees. Make them distinctly
crisis-domain and well-crafted Slack-native UX.

## Part A — Crisis suggested prompts (assistant surface)
`listeners/events/assistant_thread_started.py` currently sets the template trio
("Write a Message" / "Summarize" / "Brainstorm"). Replace with scenario-relevant
prompts that teach the agent's value in one glance, e.g.:
- "Family of 4, North Exmouth, no power — need water and a generator"
- "I can offer a spare room in Exmouth town"
- "Is the road to Learmonth open?"
- (one more: a resolved-case / coordinator angle if a 4th fits)
Update the greeting title to something calm + on-brand (e.g. "What do you need? Tell
me in plain language."). Keep it warm but crisis-appropriate (matches the system
prompt persona).

## Part B — Branded App Home dashboard
`listeners/views/app_home_builder.py` is the generic "I'm your Slack assistant" home.
Rebuild it as a Crisis Resource Navigator dashboard:
1. Branded header + one-line what-it-does.
2. "How to use" — post a need or an offer in plain language; tap to connect; a human
   always confirms (the bounded-autonomy guardrail stated as a feature).
3. A "Current situation" summary — reuse `coordinator.situation.read_situation()`
   (best-effort) to show a compact road/water/evac snapshot, feed-stamped + verify
   note. Degraded feed named, never silent (guardrail 4).
4. A link to the live **coordinator board** — best-effort read of the canvas id via
   `coordinator.canvas_store.load_canvas_id()`; render an "Open the cases board"
   link when present, omit cleanly when not.
5. Drop / reframe the template's MCP-connection status block (it assumes OAuth mode;
   in socket-mode it's noise). Keep the home useful, not a status dump.
Every external/situation item keeps source + verify framing (guardrails hold on the
Home tab too).

## Acceptance criteria
- [x] 1. Crisis suggested prompts + greeting title (Part A); the generic trio is gone.
- [x] 2. App Home renders the branded dashboard (Part B) with how-to, the human-confirms
   note, a best-effort situation summary, and a best-effort board link. Pure
   block-builder where possible; the situation/canvas reads happen in the
   app_home_opened handler (the impure boundary) and degrade silently on failure —
   a Home render must never crash (it's the first impression).
- [x] 3. manifest assistant_description stays crisis-framed (already is) — tweak only if it
   improves clarity. If suggested_prompts static fallback in manifest helps, set it
   too (the dynamic listener is the live path).
- [x] 4. Tests: suggested-prompts content; app-home block structure (header + how-to +
   human-confirms + situation section present/degraded + board-link present/absent),
   situation + canvas reads mocked. Existing app-home tests updated. filterwarnings
   =error, zero warnings.
- [ ] 5. [HUMAN] live: open the app's Home tab → branded dashboard; open a new assistant
   thread → crisis prompts shown.

## Out of scope
Match-card colored-bar restyle (separate; streaming-API constrained). Canvas visual
restyle (020 covers content). Any model/prompt change.

## Grounding for SWE (current code)
- **Part A** — `listeners/events/assistant_thread_started.py`: replace `SUGGESTED_PROMPTS`
  (currently Write a Message/Summarize/Brainstorm) + `title`. A prompt's `message` is
  the text SENT when tapped — make them realistic crisis messages (a resident need, a
  volunteer offer, a road/info question; 4th if it fits). Keep the try/except.
- **Part B** — `listeners/views/app_home_builder.py` currently is
  `build_app_home_view(install_url, is_connected) -> dict` (generic home + OAuth/MCP
  status block). Rebuild it as a PURE composer; do the situation + canvas-id I/O in the
  HANDLER (`listeners/events/app_home_opened.py`) and pass results in. Suggested:
  `build_app_home_view(*, situation: SituationSnapshot | None, board_url: str | None)`.
  Drop the socket-mode MCP-status block (Part B item 5). Handler best-effort:
  `read_situation()` + `canvas_store.load_canvas_id()` + `announce.canvas_link(canvas_id,
  team_id=context.team_id, team_url=...)`; omit the board link cleanly if no id; every
  read wrapped so a failure degrades/omits — never crash the publish (first impression).
- **Reuse**: `coordinator.situation.read_situation`/`SituationSnapshot`/`SituationFeed`,
  `coordinator.canvas_store.load_canvas_id`, `coordinator.announce.canvas_link`. Match
  the board's situation rendering (feed-stamped + verify note + degraded named).
- **Tests**: `tests/unit/test_app_home_opened.py` + `tests/unit/test_view_builders.py`
  exist — update for the new signature + branded sections; add a suggested-prompts
  content test; mock the situation/canvas reads. Zero warnings.
- Guardrails on the Home tab: situation items sourced + verify note, degraded feed named
  (g4), human-confirms stated as a feature (g1), no safety assertion. Display-only.

## Log

### [SWE] 2026-06-13 12:25 — Implementation

**Files modified**
- `listeners/events/assistant_thread_started.py` — replaced the starter trio with four crisis-domain `SUGGESTED_PROMPTS` (resident need / volunteer offer / road-info question / situation recap), all Exmouth-grounded; calm `THREAD_TITLE` "What do you need? Tell me in plain language." Kept the try/except.
- `listeners/views/app_home_builder.py` — rebuilt `build_app_home_view(*, situation, board_url) -> dict` as a PURE composer: branded header + tagline, "How to use" (human-confirms as a feature), a sourced+verify Current-situation section (feed-stamped, degraded feed named), an "Open the cases board" link. Dropped the OAuth MCP-status block.
- `listeners/events/app_home_opened.py` — moved the impure reads here: `read_situation()` + `load_canvas_id()` + `auth.test` team_url → `canvas_link(...)`, each wrapped best-effort so a failure degrades/omits; publish never crashes.
- `manifest.json` — set the `suggested_prompts` static fallback to mirror the listener (optional AC3); `assistant_description` left as-is (already crisis-framed).
- `tests/unit/listeners/events/test_assistant_thread_started.py` — new: suggested-prompts content + handler.
- `tests/unit/test_view_builders.py` — rewritten for the new signature + branded sections (header/how-to/human-confirms/situation present+degraded+omitted/board link present+absent/no-safety-assertion).
- `tests/unit/test_app_home_opened.py` — rewritten: mocks the situation + canvas reads; asserts pass-through, board-url construction, and degrade-on-failure for each read + publish.

**Tests**
- Unit: 503 passing, 0 failing, ZERO warnings (`filterwarnings=error`) — `make pre-commit`.
- Integration: 5 passing, 1 skipped (live-provider key absent; unrelated) — `make integration-tests`.

**Acceptance criteria**
- [x] 1 — crisis prompts + calm title, generic trio gone — `tests/unit/listeners/events/test_assistant_thread_started.py::TestSuggestedPromptsContent`.
- [x] 2 — branded dashboard, pure builder + impure handler boundary, degrade-never-crash — `tests/unit/test_view_builders.py::TestAppHome*`, `tests/unit/test_app_home_opened.py::TestAppHomeOpened`.
- [x] 3 — manifest static `suggested_prompts` fallback set, description kept crisis-framed — manifest JSON validated, shape `{title,message}`.
- [x] 4 — content + block-structure tests, reads mocked, existing two files updated, zero warnings.
- [ ] 5 — [HUMAN] live: open Home tab → branded dashboard; open assistant thread → crisis prompts. (Block Kit payload structurally validated below; needs a live `slack run` for visual sign-off.)

**Evidence**
```
$ make pre-commit
... tests/unit/test_app_home_opened.py ........        [ 90%]
    tests/unit/test_view_builders.py ............      [100%]
============================= 503 passed in 1.53s ==============================

$ make integration-tests
========================= 5 passed, 1 skipped in 0.74s =========================
```
End-to-end (handler → live mock feeds → builder → views_publish): a real `read_situation()` rendered the full Exmouth situation, every row `source: <feed> · fetched <UTC>`; None canvas-id cleanly omitted the board link; 11-block `home` view published. Block Kit payload structurally valid (header ≤150, sections ≤3000, ≤100 blocks); 4 suggested prompts within title/message limits.

**Guardrail recheck (display-only; no model/system-prompt change)**
- g1 human-confirms: stated up front in "How to use" as a feature ("A human always confirms … I never make a match … on my own").
- g3 sourced + verify: every situation row carries `source: <feed> · fetched <UTC>`; the section carries a verify-before-relying context note.
- g4 degraded named: a down feed renders an explicit `Feed unavailable: <feed> — <detail>` line, never silently dropped.
- g2 no safety assertion: rows relay the feed's own words (e.g. "OPEN WITH CAUTION"); the Home tab never asserts a road is safe / okay to travel.

**Notes**
- AC5 left unchecked — requires live `slack run` visual sign-off (Home tab + new assistant thread).
- Only caller of `build_app_home_view` was `app_home_opened.py` (updated); no other callers to migrate.

### [Tester] 2026-06-13 14:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 97 files formatted; `ruff check` all passed)
- Unit tests: 503 passed / 0 failed (double-run stable: 503/503 both runs)
- Integration tests: 5 passed / 1 skipped (live-provider key absent; unrelated) — stable both runs
- Warnings: 0 (`filterwarnings = ["error"]` in pyproject.toml:75 — any warning would fail the run; none did)

**E2E adversarial pass**
- Happy path: `build_app_home_view(situation=full, board_url=...)` → 11-block valid `home` view; road status relayed verbatim ("OPEN WITH CAUTION"), `fetched 2026-03-14 06:30 UTC` stamp, verify note, "Open the cases board" link present. (PASS)
- Break path 1 (state edge: every handler read raises): drove `handle_app_home_opened` with `read_situation`/`load_canvas_id`/`auth_test` each raising, then ALL three simultaneously → `views_publish` still called every time, no exception escaped (PASS). `views_publish` itself raising → swallowed, no crash (PASS).
- Break path 2 (boundary: situation=None / board_url=None): Current-situation section and board link omitted cleanly; minimal 5-block branded view, valid Block Kit (PASS).
- Break path 3 (degraded feed, g4): down `road_closures` feed → explicit `Feed unavailable: road_closures — …` line, feed named, never silently dropped (PASS).
- Block Kit structural validation: all 4 permutations JSON-serializable, ≤100 blocks, header plain_text ≤150 chars, sections ≤3000 chars. Suggested-prompts payload: 4 prompts, all `{title,message}`, non-empty, title<100; manifest static fallback 3 prompts (subset mirror of listener), valid JSON (PASS).
- Defensive note: a non-`SituationSnapshot` garbage object from `read_situation` is caught by the handler's outer guard (no crash; publish skipped). `read_situation` always returns a typed snapshot, so this path is unreachable in practice — outer guard correct.

**Acceptance criteria**
- [x] PASS — AC1: crisis prompts + calm title; generic trio gone. Evidence: `assistant_thread_started.py:11-32` — 4 Exmouth-grounded prompts (need/offer/road-info/situation-recap, all real agent capabilities), `THREAD_TITLE = "What do you need? Tell me in plain language."`; old "Write a Message/Summarize/Brainstorm" removed (diff). Covered by `tests/unit/listeners/events/test_assistant_thread_started.py::TestSuggestedPromptsContent`.
- [x] PASS — AC2: pure composer + impure boundary + branded dashboard. Evidence: `app_home_builder.py:152` `build_app_home_view(*, situation, board_url)` does zero I/O; reads live in `app_home_opened.py:12-51`. Dashboard has header+tagline (`:166-168`), "How to use" with human-confirms (`:38-49`), sourced+verify+degraded-named situation section (`:111-131`), board link present/absent (`:134-149,177-178`). MCP-status block gone (`test_view_builders.py::test_drops_the_mcp_status_block`). CRITICAL never-crash verified live: each read raising → publish still happens (adversarial pass + `test_app_home_opened.py::test_situation_read_failure_degrades_to_none`, `::test_canvas_read_failure_degrades_to_no_board_link`, `::test_team_url_resolution_failure_still_links_with_team_id`, `::test_views_publish_exception_is_swallowed`).
- [x] PASS — AC3: manifest valid JSON; static `suggested_prompts` fallback mirrors listener (`{title,message}` subset of 3 core prompts); `assistant_description` crisis-framed ("plain language" + "confirm every match"). Evidence: `manifest.json:5-21`, validated via `json.load`.
- [x] PASS — AC4: content + block-structure tests present; situation/canvas reads mocked; both existing test files rewritten; new prompts test added; zero warnings. Evidence: `test_view_builders.py` (TestAppHomeBranding/Situation/BoardLink), `test_app_home_opened.py` (9 tests, reads mocked via `mocker.patch`), `test_assistant_thread_started.py` (new).
- [ ] [HUMAN] — AC5: live `slack run` Home-tab + assistant-thread visual sign-off. Awaiting human verification. Block Kit payloads structurally validated above.

**GUARDRAIL RECHECK (display-only change; Home tab surfaces official situation data)**
- g1 (human-confirms as a feature): PASS — "How to use" states ":white_check_mark: *A human always confirms* — … I never make a match, a placement, or any action on my own. You decide" (`app_home_builder.py:46-48`); tagline "a human confirms every match" (`:34`).
- g2 (never assert safety): PASS — situation rows relay the feed's own status word verbatim (`_row_for`, `:75-92`); live build relayed "OPEN WITH CAUTION" unchanged; the tab never emits "safe to travel"/"it is safe"/"okay to travel" (`test_never_asserts_safety` + adversarial check, all clean).
- g3 (sourced + verify): PASS — every row carries `source: <feed> · fetched <UTC>` (`_feed_stamp`, `:68-72`); section carries standing verify note "Always verify … before relying on it" (`:53-56,127-130`).
- g4 (degraded named, never silent): PASS — an unavailable feed renders `Feed unavailable: <feed> — <detail>` (`_feed_lines`, `:103-105`); verified live for a down road_closures feed; also enforced upstream in `coordinator/situation.py` (unexpected raise → `available=False`).

**Evidence**
```
$ make pre-commit
... tests/unit/test_app_home_opened.py ........        [ 90%]
    tests/unit/test_view_builders.py ............      [100%]
============================= 503 passed in 1.69s ==============================
$ make integration-tests
========================= 5 passed, 1 skipped in 0.82s =========================
(double-run: 503 passed / 5 passed+1 skipped, identical)
```

**Other issues found**
- None blocking. Note: manifest static fallback carries 3 of the 4 listener prompts (the situation-recap is dynamic-only). The dynamic listener is the live path; the static fallback covering the three core capabilities is sufficient per AC3 ("if it helps"). PASS with note.

**Scope check:** diff touches only `listeners/events/{app_home_opened,assistant_thread_started}.py`, `listeners/views/app_home_builder.py`, `manifest.json`, and the 3 test files. No `agent/`, `recall/`, or `coordinator/canvas.py` changes. Clean.

**VERDICT: PASS**
