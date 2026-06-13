# 028 — Official MCP results as sourced cards in the need reply

The need reply renders **workspace** recall hits as source-stamped match cards
(`recall/blocks.py`), but **official** MCP feed results (road closures, evac centres,
water points, advice) reach the user only as **LLM prose** today (system prompt §132
OFFICIAL DIRECTORIES; the LLM calls the mock MCP tools and weaves ~2-3 pruned items in
text). `recall/blocks.py:61` even notes official MCP cards as "future work."

The landing demo (docs/site/index.html, scenario 1 "match 2 · official · MCP feed: Water
point open…" and the safety "warn card") shows official results as **ranked,
source-stamped cards** — which is the design doc's intent ("ranked, source-stamped
matches" from external feeds) but is NOT built. Close the gap: render relevant official
feed items as sourced cards in the need reply.

User decision (2026-06-13): **build the official cards** (vs softening the demo).

**Depends on task 029.** The headline safety scenario ("is the road safe?") only
reaches the reply pipeline once **029** broadens parsing to classify crisis-relevant
information/safety questions as Needs (today they're `NotACrisisMessage` → silent).
029 ships the parse fix (the question gets answered in prose); 028 then upgrades the
official answer from prose to structured cards. Assume 029 has landed.

## Design decisions (locked)

- **Deterministic render, not LLM-emitted cards.** Reuse the feeds the board already
  reads: `coordinator.situation.read_situation()` → `SituationSnapshot`
  (road_closures / evac_centres / official_advice, each a `SituationFeed` with
  feed name + aware-UTC `fetched_at` + typed records, or `available=False` with a
  `detail`). Cards are composed by code from that snapshot — same trust path as the
  board's Situation section — so sourcing/timestamps/degraded-states are guaranteed,
  not model-dependent. (The LLM still *plans*; it no longer owns the official display.)
- **Relevance pruning by need_type — a small deterministic map** mirroring the
  system-prompt rule already written at agent/agent.py §157: a water/drinking/supply
  need surfaces water point(s); a travel/road/drive need surfaces road closure(s);
  a shelter/sleep/accommodation need surfaces evac centre(s); a safety/"is X safe"
  question surfaces the relevant closure/advice. Cap at ~3 official items. If no feed
  is relevant to the need, render NO official section (never dump the full picture —
  the no-noise rule from task 012).
- **Rendered as its own "Official information" section BENEATH the workspace matches**,
  not interleaved into the workspace ranking. (The demo's "match 2" is a
  simplification; an honest, labelled official section is clearer and avoids implying
  a single cross-source ranking.) Distinct from workspace cards by the colored-bar
  cue already reserved in recall/blocks.py: 🟦 blue for evac centres / water points /
  advice (info), 🟥 red for road closures / warnings. Each card: the item text +
  `feed: <name> · fetched <UTC>` (absolute UTC, `%Y-%m-%d %H:%M UTC` — NOT relative) +
  the standing verify note. NO action buttons on official cards (you don't "Connect"
  to a road closure).
- **Degraded feeds stay loud (guardrail 4).** If a feed relevant to the need is
  `available=False`, render an explicit "⚠ <feed> unavailable — <detail>" card rather
  than dropping it. Never assert safety on any official card (guardrail 2): show the
  feed's own status word verbatim (e.g. road "CLOSED") + verify note; never "safe to
  travel".
- **No prose duplication.** Update the system prompt OFFICIAL DIRECTORIES section: the
  agent should still consult directories in its *plan*, but defer the official
  *specifics* to the rendered cards — its prose refers to "the official items below"
  rather than re-listing closures/centres/water points. The agent still composes its
  reasoning + the workspace matches narrative. **System prompt is product code**
  (CLAUDE.md): re-check all 4 guardrails and live-test before commit.
- **Best-effort.** A feed-read failure degrades to the explicit unavailable card (or,
  on an unexpected raise, to no official section) — never breaks the need reply. The
  workspace matches + LLM prose always stand.
- **Parse broadening is task 029, not here.** 029 makes safety/info questions parse as
  Needs. 028 only assumes that's landed and renders the official cards for the
  resulting need reply. Do NOT touch PARSING_PROMPT in 028.

## Implementation sketch (SWE owns details)

- New `recall/official_blocks.py` (keeps recall/blocks.py focused): 
  `build_official_blocks(need, situation) -> list[Block]` — apply the need_type→feed
  relevance map, select up to N records, render the 🟦/🟥 cards + an "Official
  information" header; degraded-relevant feed → unavailable card; nothing relevant →
  `[]`. Pure `(_ , SituationSnapshot) -> blocks`, unit-testable, no I/O.
- `listeners/recall_reply.py`: in the Need branch, best-effort read the situation
  (reuse `coordinator.situation.read_situation`, wrapped like the board's
  `_read_situation_best_effort`) and append `build_official_blocks(...)` to the
  `NeedRecall.blocks` after the workspace match blocks. Keep `llm_context` honest
  (tell the model official items are shown as cards). Guard: this must not double-count
  with the offer/need split — official cards only on the Need path.
- `agent/agent.py` system prompt: trim the OFFICIAL DIRECTORIES "weave 2-3 items into
  prose" instruction to "defer specifics to the rendered official cards"; keep the
  plan-step consult + degraded-state honesty. Re-run the guardrail regression
  (tests/unit/test_system_prompt.py) and update it for the new wording.
- Optional safety-refusal polish (verified-live 2026-06-13): for a road/travel-SAFETY
  question, the reply should LEAD with an explicit "I can't tell you whether it's safe
  — I don't make that call" framing before the official info (the current answer
  presents info + verify note — guardrail-compliant — but omits the explicit refusal
  the demo shows). A small system-prompt nudge; keep it from over-applying to
  non-safety info needs (e.g. "where do we evacuate" needs no safety refusal). Pin
  with a guardrail-regression assertion.
- Block Kit constants: reuse the existing emoji-bar convention noted in
  recall/blocks.py (🟩 workspace; 🟦/🟥 official). Verify the payload renders
  (Block Kit Builder / live) — composed blocks with source + timestamp on every item.
- ADR-0007: "Official MCP results as sourced cards in the need reply" — Nygard four
  sections. Decision = deterministic render from the situation snapshot, relevance
  map mirroring the prompt, official section beneath workspace matches, no buttons,
  degraded loud, prose defers to cards.
- Demo honesty pass (docs/site/index.html): make the official-card label/shape match
  what's built (an "Official information" item, blue/red emoji-cue style — NOT CSS
  bars; the app keeps the streamed reply + 🟩/🟦/🟥 cues per the 2026-06-13 rendering
  decision); switch the demo's relative times ("2h ago", "14 min ago", "just now") to
  **absolute UTC** to match the app; neutralize the fictional "Mara V."/"#offers"
  persona to a generic name + the crisis channel. (Closes demo-vs-app divergences
  #1–#4 from the 2026-06-13 verification.)
- **Concept ↔ Live toggle scaffold** (docs/site/index.html, user decision 2026-06-13):
  add a small toggle in the demo section that swaps the existing animated mockup
  ("Concept") for a "Live" panel showing REAL Slack screenshots (proof it shipped).
  Build the scaffold + a labelled caption ("Concept animation · Live = real Slack");
  use clearly-marked PLACEHOLDER image slots (e.g. `docs/site/img/live-need.png`,
  `live-safety.png`, `live-board.png`) with alt text + a visible "screenshot pending"
  state so the page is valid before the user drops the real PNGs in. Do NOT fabricate
  a "realistic" re-render — the Live side is real screenshots only. Keep the Concept
  animation fully intact (it's the explainer). CSS-only toggle, no framework.

## Acceptance criteria

1. [x] On a Need, official feed item(s) relevant to the need_type render as sourced
   Block Kit cards in the reply, beneath the workspace matches, under an "Official
   information" header — each with feed name + absolute-UTC fetched-at + verify note,
   blue (info) / red (closure-warning) bar, NO action buttons. — unit tests on
   `build_official_blocks` per need_type.
2. [x] Relevance map: water/supply→water point(s); travel/road→closure(s);
   shelter→evac centre(s); safety question→relevant closure/advice; capped at ~3; an
   unrelated need → NO official section. — parametrized unit tests.
3. [x] A feed relevant to the need but `available=False` renders an explicit
   "unavailable — <detail>" card (guardrail 4); never dropped, never silent. — test.
4. [x] No official card asserts safety; closures show the feed's own status verbatim +
   verify note (guardrail 2). — test asserts no "safe"/"okay to travel" phrasing and
   the verify note present.
5. [x] System prompt updated to defer official specifics to the cards (no prose
   re-listing); plan-step consult + degraded honesty retained. Guardrail regression
   (test_system_prompt.py) updated and green. Live-tested (system prompt = product
   code). — code + regression done; [HUMAN] live check still pending (see AC10).
6. [x] Best-effort: a situation-read failure degrades to the unavailable card or no
   section; the need reply (workspace matches + prose) never breaks. — test.
7. [x] Demo honesty pass applied to docs/site/index.html (official item shape matches
   built cards; absolute UTC; Mara/#offers neutralized). — Live screenshots are
   user-provided PNGs; Live panel ships as a labelled placeholder scaffold.
8. [x] ADR-0007 added.
9. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
10. [ ] [HUMAN] Live: post a water need and a "is the road safe" question in the crisis
    channel → reply shows the workspace matches AND an Official information section with
    the right feed card(s), sourced + UTC-stamped + verify note; the safety question is
    refused with the closure card, no safety assertion.
11. [x] Guardrail recheck (system prompt = product code): after the OFFICIAL
    DIRECTORIES prose-deferral edit, all 4 guardrails re-verified (no safety assertion,
    sourcing, degraded loud, human confirms) — a Tester PASS that skips this is a FAIL
    (CLAUDE.md). (Parse broadening + its safety-question live check live in task 029.)

## BDD scenarios
- Given a need_type "water" and a situation with an evac centre offering water, When
  the reply composes, Then a blue official card for that water point renders with
  feed + UTC + verify note, no button.
- Given "is the road to Learmonth safe", When composed, Then the prose refuses to
  judge safety AND a red road-closure card renders verbatim ("CLOSED…") + verify note.
- Given a need_type "baby formula" with no relevant feed, When composed, Then NO
  official section renders (no dump).
- Given the road-closures feed is `available=False` for a travel need, When composed,
  Then an explicit "road closures unavailable" card renders.

## Out of scope
- Action buttons on official cards (none — info only).
- Replacing the mock feeds with real government feeds (coordinator/situation.py stays
  the single swap point).
- The offer-index backfill (task 026) and channel-canvas polish (027) — separate.

## Log

### [SWE] 2026-06-13 20:05 — Implementation

**Files modified**
- `recall/official_blocks.py` (NEW) — `build_official_blocks(need, situation) -> list[Block]`:
  pure, relevance-pruned official cards (🟦 info / 🟥 advisory), feed + absolute-UTC
  fetched-at + verify note, NO buttons; relevant-but-down feed → explicit unavailable
  card; nothing relevant → `[]`.
- `recall/__init__.py` — export `build_official_blocks` + the official emoji/header constants.
- `listeners/recall_reply.py` — `_read_situation_best_effort` / `_official_blocks_best_effort`
  (mirroring the board's wrapper); wired official cards into BOTH branches: info need →
  cards ARE the structured content (LLM prose leads); resource need → cards appended
  beneath the workspace match blocks. `llm_context` kept honest (official items shown as
  cards) on both paths.
- `agent/agent.py` (SYSTEM_PROMPT) — trimmed OFFICIAL DIRECTORIES to DEFER official
  specifics to the rendered cards (no prose re-listing); kept plan-step consult,
  relevance map, degraded-by-name honesty. Added a scoped SAFETY QUESTIONS rule: a
  road/travel safety Q LEADS with an explicit can't-judge refusal, NOT over-applied to
  plain where/what info needs.
- `docs/adr/0007-official-mcp-cards-in-need-reply.md` (NEW) — four-section Nygard ADR.
- `docs/site/index.html` — demo honesty pass (official item shape = emoji-cue cards;
  relative times → absolute UTC; "Mara V."/@mara/#offers → generic neighbour + crisis
  channel) + a CSS-only Concept↔Live toggle with labelled PLACEHOLDER screenshot slots
  (visible "screenshot pending" state) + caption; Concept animation left fully intact.
- `docs/site/img/README.md` (NEW) — drop-in instructions for the user-provided PNGs.
- `tests/unit/recall/test_official_blocks.py` (NEW) — per-need_type relevance, card
  shape (blue/red, feed+UTC, verify, no buttons), degraded-relevant card, no-relevant →
  [], safety-never-asserted, determinism.
- `tests/unit/listeners/test_recall_reply.py` — official-cards-in-both-branches,
  below-workspace ordering, no-relevant → no section, degraded card, best-effort
  read-failure (resource → no section + matches stand; info → empty blocks); updated the
  030 `no_connect_blocks` test for the 028 behaviour change (info needs now render
  button-free official cards).
- `tests/unit/test_system_prompt.py` — guardrail-regression update: prose-deferral
  anchors, the scoped safety-refusal anchors, dropped the obsolete prose-brevity-cap
  anchor; kept the relevance map + prune-not-hide anchors.

**Tests**
- Unit: 480 passing, 0 failing — `make unit-tests` (full suite). Touched files: 96
  passing across `test_official_blocks` / `test_recall_reply` / `test_system_prompt`.
- Integration: 5 passing, 1 skipped (live provider key not configured) — no infra change.
- Zero warnings (`filterwarnings=error`); double-run stable (480 both runs).

**Acceptance criteria**
- [x] AC1 — `tests/unit/recall/test_official_blocks.py::test_water_card_is_blue_with_feed_utc_and_verify_no_button`,
  `test_section_opens_with_official_information_header`, `test_road_card_is_red_advisory_cue`;
  `tests/unit/listeners/test_recall_reply.py::test_resource_need_appends_official_cards_beneath_matches`,
  `test_resource_need_official_cards_sit_below_workspace_matches`.
- [x] AC2 — `test_official_blocks.py::test_{water,travel,shelter,official_warning,safety,unrelated}_*`,
  `test_caps_records_to_about_three`; `test_recall_reply.py::test_resource_need_with_no_relevant_feed_has_no_official_section`.
- [x] AC3 — `test_official_blocks.py::test_relevant_but_unavailable_feed_renders_explicit_card`;
  `test_recall_reply.py::test_info_need_degraded_relevant_feed_renders_unavailable_card`.
- [x] AC4 — `test_official_blocks.py::test_card_never_asserts_safety`, `test_no_official_card_carries_action_buttons`.
- [x] AC5 — `test_system_prompt.py::test_official_display_defers_to_cards`,
  `test_road_safety_question_leads_with_explicit_refusal`, `test_official_directories_section_anchored`.
  [HUMAN] live system-prompt check still pending (folds into AC10).
- [x] AC6 — `test_recall_reply.py::test_situation_read_failure_does_not_break_the_need_reply`,
  `test_info_need_situation_read_failure_yields_no_blocks`.
- [x] AC7 — manual diff of `docs/site/index.html` (official cards = emoji-cue + absolute
  UTC; persona neutralised; Concept↔Live toggle + placeholder scaffold). Real PNGs are
  user-provided (scaffold only).
- [x] AC8 — `docs/adr/0007-official-mcp-cards-in-need-reply.md`.
- [x] AC9 — `make pre-commit` + `make integration-tests` green, zero warnings, double-run stable.
- [ ] AC10 — [HUMAN] live: post a water need + an "is the road safe" question in the
  crisis channel; verify the workspace matches + Official information section render
  with the right card(s), sourced + UTC + verify note, and the safety Q is refused.
- [x] AC11 — four-guardrail recheck run explicitly (see Evidence); all four re-verified
  after the prompt + rendering changes.

**Evidence**

Guardrail recheck (run via a scripted assertion over `build_official_blocks` + SYSTEM_PROMPT):
```
GUARDRAIL 1 — A HUMAN DECIDES: no official card carries an actions block (info only).
GUARDRAIL 2 — NEVER ASSERT SAFETY: cards relay 'CLOSED' verbatim + verify note, no own
  safety assertion; prompt LEADS road/travel safety Qs with an explicit can't-judge
  refusal, scoped (not over-applied to plain info needs).
GUARDRAIL 3 — SOURCED + TIMESTAMPED: every card carries feed name + ABSOLUTE UTC
  fetched-at (2026-03-15 06:30 UTC) + verify note.
GUARDRAIL 4 — DEGRADED LOUD: a relevant-but-down feed → explicit named
  'unavailable — <detail>' card; an irrelevant down feed is not surfaced (relevance gates).
ALL FOUR GUARDRAILS RE-VERIFIED.
```

Live `route_message` against the REAL mock feeds (info "road safety" need):
```
result: []
headers: ['Official information']
has action buttons: False
section texts: ['*Minilya-Exmouth Road* … : CLOSED. …',
               '*Learmonth Access Road* … : UNDER ASSESSMENT. …',
               '*Murat Road* … : OPEN WITH CAUTION. …']   # capped at 3, status verbatim
llm_context mentions 'card': True
say called: False
```

```
$ make unit-tests
480 passed in 2.07s
$ make integration-tests
5 passed, 1 skipped in 1.04s
```

**Notes**
- AC10 (live) left unchecked — needs `slack run` + a water need and a safety question in
  the crisis channel. The live system-prompt check (AC5's residual) folds into AC10.
- AC7 Live-panel screenshots are user-provided PNGs (`docs/site/img/live-{need,safety,board}.png`);
  shipped as a labelled placeholder scaffold with a visible "screenshot pending" state and
  an `onerror` fallback so the page is valid before the PNGs land. The Concept animation is
  fully intact.
- Behaviour change to a 030 test: `test_information_need_produces_no_connect_blocks` no
  longer asserts `blocks == []` (info needs now render button-free official cards); it
  asserts no `actions` block, which preserves the original no-Connect intent.
- No architectural forks: reused `coordinator.situation.read_situation` (no feed re-read,
  no new data source); emoji-cue rendering per the LOCKED 2026-06-13 decision (no
  attachments/CSS-bar rework). parsing.py / `is_information` untouched (029/030).

### [Tester] 2026-06-13 12:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` → format-check + lint-check clean, 480 unit pass)
- Unit tests: 480 passed / 0 failed (double-run stable: 480 / 480)
- Integration tests: 5 passed / 1 skipped (live provider key not configured — expected), 0 failed (double-run stable)
- Warnings: 0 (`filterwarnings=error`; zero across all runs)
- Touched-file subset: 96 passed (`test_official_blocks` + `test_recall_reply` + `test_system_prompt`)

**E2E adversarial pass** (drove `build_official_blocks` against the REAL mock feeds via `read_situation()`, and `route_message` with mocked parse/recall/situation)
- Happy path A — INFO road-safety (`route_message`, `is_information=True`): headers `['Official information']`, NO actions block, `recall_offers` NOT called, `llm_context` mentions cards, caller posts the single reply. PASS
- Happy path B — RESOURCE water (`route_message`): headers `['Prior offers from this workspace', 'Official information']` (workspace BEFORE official), Connect/actions block intact, `Exmouth Recreation Centre` water card present beneath, `llm_context` official-cards note appended. PASS
- Break 1 (degraded: relevant road feed `available=False`, travel need): explicit `⚠ *road_closures* unavailable — Simulated outage…` card + verify note (loud, guardrail 4). PASS
- Break 2 (relevance gate: irrelevant down feed + unrelated `baby formula` need): `[]` — down road feed NOT surfaced. PASS
- Break 3 (boundary: empty-string `need_type`): `[]`, no crash. PASS
- Break 4 (boundary: `need_type=None`): rejected at the `Need` entity boundary (Pydantic `ValidationError`); the `(need.need_type or "")` guard is belt-and-braces. PASS
- Break 5 (boundary: uppercase + em-dash `need_type`): lowercased + substring-matched, renders correctly. PASS
- Break 6 (state edge: available feed with `fetched_at=None`): defensive `feed: road_closures` stamp, no crash. PASS
- Break 7 (failure mode: `read_situation` raises `RuntimeError`, both paths): caught + logged (warning); resource → workspace matches stand, NO official section; info → `blocks == []`, prose still leads. Reply never breaks (best-effort, AC6). PASS
- Per-need_type render (real feeds): water→evac water-point (🟦), travel/road→closures (🟥, CLOSED/UNDER ASSESSMENT/OPEN WITH CAUTION verbatim), shelter→evac (🟦), warning→advice (EMERGENCY WARNING tinted 🟥, plain Advice 🟦), all capped at 3 sections, absolute UTC `%Y-%m-%d %H:%M UTC`, no actions block. PASS
- Safety-phrase scan across all real-feed cards: zero of `safe to travel / okay to travel / it is safe / road is safe / safe to drive / ok to travel`; verify note on every card (15/15). PASS

**Acceptance criteria**
- [x] PASS — AC1: relevant official items render as emoji-cue cards (🟦 info / 🟥 advisory) under "Official information", BENEATH workspace matches, each with feed name + ABSOLUTE-UTC fetched-at + verify note, NO action buttons. — `official_blocks.py:296-356`; e2e Path B header order + `test_resource_need_official_cards_sit_below_workspace_matches`; `test_water_card_is_blue_with_feed_utc_and_verify_no_button`.
- [x] PASS — AC2: relevance map (water→water point/evac; travel/road/safety→closures; shelter→evac; warning→advice), cap 3, unrelated→`[]`. — `official_blocks.py:110-202,345`; e2e per-need_type + Break 2/3; `test_unrelated_need_renders_no_official_section`, `test_caps_records_to_about_three`.
- [x] PASS — AC3: relevant-but-down feed → explicit "unavailable — <detail>" card; irrelevant down feed NOT surfaced. — `_unavailable_card`/`_relevant_down_feeds` `official_blocks.py:205-231,315-328`; e2e Break 1/2; `test_relevant_but_unavailable_feed_renders_explicit_card`, `test_unavailable_feed_irrelevant_to_need_is_not_shown`.
- [x] PASS — AC4: no card asserts safety; closures show feed status verbatim + verify note. — `_record_text` relays verbatim `official_blocks.py:249-266`; e2e safety-phrase scan = NONE, verify note 15/15; `test_card_never_asserts_safety`.
- [x] PASS — AC5: SYSTEM_PROMPT OFFICIAL DIRECTORIES defers specifics to cards (no prose re-list); SAFETY QUESTIONS section LEADS with explicit can't-judge refusal, scoped ("ONLY for road/travel SAFETY questions"). — `agent/agent.py:139-178`; `test_official_display_defers_to_cards`, `test_road_safety_question_leads_with_explicit_refusal`, `test_official_directories_section_anchored`, `test_official_items_relevance_pruning_is_anchored` all green. [HUMAN] live check folds into AC10.
- [x] PASS — AC6: situation-read failure degrades to no section (resource) / empty blocks (info); reply never breaks. — `_read_situation_best_effort`/`_official_blocks_best_effort` `recall_reply.py:172-201`; e2e Break 7; `test_situation_read_failure_does_not_break_the_need_reply`, `test_info_need_situation_read_failure_yields_no_blocks`.
- [x] PASS — BOTH PATHS: info need (030 branch) renders button-free official cards as structured content; resource need appends official cards beneath workspace matches. — `recall_reply.py:465-503`; e2e Path A/B. 030 regression preserved: `test_information_need_produces_no_connect_blocks` now asserts NO `actions` block (not `blocks==[]`) and info needs still carry ZERO action/Connect blocks (verified e2e Path A `has actions block: False`).
- [x] PASS — AC7: demo placeholder scaffold present (Concept↔Live toggle, 24 scaffold refs, `docs/site/img/README.md` drop-in instructions, visible "screenshot pending" state, `onerror` fallback). Real PNGs are user-provided. — `docs/site/index.html`, `docs/site/img/README.md`.
- [x] PASS — AC8: ADR-0007 present, four Nygard sections (Status/Context/Decision/Consequences), emoji-cue-not-attachments rationale documented. — `docs/adr/0007-official-mcp-cards-in-need-reply.md`.
- [x] PASS — AC9: demo honesty pass — official cards = 🟦/🟥 emoji-cue (NOT CSS bars), relative times → absolute UTC, "Mara V."/"@mara"/"#offers" → "a neighbour"/"@neighbour"/"#exmouth-mutual-aid" (grep: zero leftovers). HTML tag-balance validated (no broken toggle); Concept animation intact. `make pre-commit` + unit + integration green, 0 warnings, double-run stable. — `docs/site/index.html`.
- [ ] [HUMAN] AC10 — Awaiting human verification: live `slack run` post of a water need + "is the road safe" question in the crisis channel. Not Tester-verifiable without a live sandbox session.
- [x] PASS — AC11 (guardrail recheck): see explicit four-guardrail statement below.

**GUARDRAIL RECHECK (mandatory — system prompt = product code)**
1. A HUMAN DECIDES — official cards carry NO action buttons (verified across road/water/shelter/warning need types, e2e `has action buttons: False`; resource-need Connect button confirmed still present, e2e Path B). PASS
2. NEVER ASSERT SAFETY — cards relay the feed's own status word verbatim (CLOSED / UNDER ASSESSMENT / OPEN WITH CAUTION); safety-phrase scan over all real-feed cards = NONE; SYSTEM_PROMPT SAFETY QUESTIONS section LEADS with an explicit can't-judge refusal ("you don't make safety calls", "Do not answer yes or no"), scoped to road/travel safety only. PASS
3. SOURCED + TIMESTAMPED — every card carries feed name + ABSOLUTE UTC fetched-at (`%Y-%m-%d %H:%M UTC`) + verify note (15/15 across the driven cases; absolute, never relative). PASS
4. DEGRADED LOUD — a relevant-but-down feed renders an explicit named "⚠ <feed> unavailable — <detail>" card (e2e Break 1); an irrelevant down feed is gated out by relevance (e2e Break 2). PASS
ALL FOUR GUARDRAILS RE-VERIFIED after the OFFICIAL DIRECTORIES prose-deferral edit + the new rendering path.

**Scope**
- Diff touches only: `agent/agent.py`, `docs/site/index.html`, `listeners/recall_reply.py`, `recall/__init__.py`, the two touched test files; new `recall/official_blocks.py`, `tests/unit/recall/test_official_blocks.py`, `docs/adr/0007-…md`, `docs/site/img/README.md`, the tracker file.
- Confirmed NOT touched: `agent/parsing.py` / `Need.is_information` (029/030), `coordinator/canvas.py` / `coordinator/situation.py`; NO attachments / colored-bar / `"color":` code added (emoji-cue per the LOCKED decision).

**Evidence**
```
$ make pre-commit
============================= 480 passed in 2.02s ==============================
$ make unit-tests        # run 1 / run 2
============================= 480 passed in 2.04s ==============================
============================= 480 passed in 1.81s ==============================
$ make integration-tests # run 1 / run 2
========================= 5 passed, 1 skipped in 1.22s =========================
========================= 5 passed, 1 skipped in 1.00s =========================
```

**Other issues found (non-blocking — orchestrator's call)**
- `_relevant_records` surfaces ALL available evac-centre records for a water need (not only centres whose `services` literally contain a water point). This matches the LOCKED design comment ("the water point lives on the evac centre's services") and the AC, and is capped at 3 + correctly excludes the road list — so the no-dump rule holds and it is not a FAIL. A tighter future relevance pass could filter evac records to `services` containing "water" for a water need. Follow-up nit only.

**VERDICT: PASS** — all non-[HUMAN] ACs (1–9, 11) verified with code + test + e2e evidence; full suite green, 0 warnings, double-run stable; e2e adversarial pass green on every break path; all 4 guardrails re-verified; scope clean. AC10 is [HUMAN] live — awaiting sandbox verification. Hand off to PM for acceptance review.
