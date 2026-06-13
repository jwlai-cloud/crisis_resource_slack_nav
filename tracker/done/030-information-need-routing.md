# 030 — Information needs answer from official sources only (no offer-recall / Connect)

Task 029 made crisis-relevant information/safety questions ("Is the road to Learmonth
safe to drive?") parse as a **Need** so passive listening answers them. Verified live
2026-06-13: the agent now answers with the official road-closure info — GOOD. But
because it's a generic Need, it ALSO ran the full resource pipeline: workspace
offer-recall + a Connect button. The live reply surfaced "An elderly couple in
Learmonth needs a gas cooker" as a "prior offer that might be relevant" with
"Confirm … connect you with the person who posted the offer" — two defects:

1. **Offer-recall ran for an information question.** There is no "offer" that satisfies
   "is the road safe" — workspace offer-matching + Connect are meaningless for an
   information need. They add noise and a nonsensical action.
2. **A foreign NEED was surfaced as a connectable OFFER.** The gas-cooker item is a
   *need*, not an offer (task 014's documented limitation: RTS recall can't tell a
   foreign need from an offer). It slipped the resource-overlap gate partly because 029
   embeds the location in `need_type` ("road safety: Learmonth"), so "Learmonth"
   overlapped the gas-cooker message's location token.

Fix: distinguish **information needs** from **resource needs** and route them
differently. An information need is answered from official feeds (the LLM already has
the road-closure/evac MCP tools; task 028 will render structured official cards). It
does NOT run workspace offer-recall and shows NO Connect button.

## Design decisions (locked)

- **The distinction is "can a workspace OFFER satisfy it?", not "is it a question."**
  - **Information need** (`is_information=True`) = answerable ONLY by official sources;
    no tangible resource a neighbour could offer: **road/travel safety + status**
    ("is the road to X safe?", "can I drive to X?", "is X road open?"), **evacuation
    locations** ("where do we evacuate / shelter?" — evac centres are an *official*
    directory, not workspace offers), **official warnings/advice status**. → official
    feeds only, NO offer-recall, NO Connect.
  - **Resource need** (`is_information=False`) = a tangible resource a neighbour could
    offer, whether phrased as a statement OR a question: "need water", "**where can I
    get water/fuel/a generator/baby formula?**", "anyone got a spare bed?". → UNCHANGED:
    offer-recall + Connect (+ official points where relevant). A "where can I get
    <resource>" question is a RESOURCE need — do NOT suppress its offer-recall.
  The line: evac centres / road status / official warnings = official-only
  (information); a thing someone could hand you = resource.
- **Add the flag at parse.** Add `is_information: bool = False` to `ParsedNeed`/`Need`,
  set by the parsing model per the rule above. (Alternative: a 4th parse category
  `InformationNeed`; SWE's call, but a flag keeps the entity surface + route minimal
  and is preferred unless it forces awkward conditionals.) Keep
  `need_type`/`location`/`urgency`/`household_size`.
- **Route information needs to an official-only answer.** In
  `listeners/recall_reply.py::route_message`, when the parsed Need is informational:
  do NOT call `recall_offers` (RTS) or the offer-index lookup; do NOT build recall
  match blocks or Connect/Not-relevant buttons. Compose the reply from the LLM (which
  consults the official-directory MCP tools and refuses to assert safety — guardrail 2)
  plus, once task 028 lands, the structured official cards. The `NeedRecall` for an
  info need carries no offer matches (empty/î„ official-only).
- **Resource needs unchanged.** Water/generator/shelter/etc. still run offer-recall +
  Connect exactly as today. Only the information branch changes.
- **Stop embedding location in need_type for info needs** (minor, prevents the
  location-overlap false match): keep `location` in the `location` field; `need_type`
  for an info need names the *information sought* without repeating the place
  (e.g. "road safety" not "road safety: Learmonth"). Update the 029 prompt wording +
  its tests accordingly.
- **Guardrails intact.** Information answers still: never assert safety (refuse +
  point to official sources), every official item sourced + UTC-stamped + verify note,
  degraded feeds explicit, human-in-the-loop preserved (there's simply no auto-action
  to confirm for an info answer). System prompt / parsing prompt are product code →
  guardrail recheck + live-verify.

## Implementation sketch
- `agent/parsing.py`: add `is_information` to `ParsedNeed`; PARSING_PROMPT sets it true
  for the info/safety/situational questions 029 introduced (and keeps `need_type` to
  the info sought, no embedded location). `parse_message` carries it onto the `Need`
  entity.
- `entities/models.py`: add `is_information: bool = False` to `Need` (default keeps all
  existing call-sites + resource needs unchanged).
- `listeners/recall_reply.py::route_message`: branch on `need.is_information` — skip
  `recall_offers` + index lookup + recall/Connect blocks; return a `NeedRecall` (or a
  thinner result) that carries no offer matches and an `llm_context` telling the model
  to answer from official directories only, no invented offers. The single composed
  reply still renders (prose + — after 028 — official cards).
- Tests: parse sets the flag for info questions, false for resource needs; route_message
  for an info need does NOT call recall_offers/index and produces no Connect blocks;
  resource need path unchanged (still recalls + Connect). Update 029's parsing tests
  for the no-embedded-location need_type.
- ADR? A short note in ADR-0004/0006 lineage or a new ADR-0007-adjacent — SWE's call;
  at minimum document the info-vs-resource routing in the recall_reply module docstring.

## Acceptance criteria
1. [x] `ParsedNeed`/`Need` carry `is_information`; PARSING_PROMPT sets it TRUE for
   official-only questions (road safety/status, evacuation locations, official
   warnings) and FALSE for resource requests INCLUDING "where can I get <resource>"
   questions (water/fuel/formula/bed). — parametrized unit tests covering both, incl.
   "where can I get water?" → resource (is_information False).
2. [x] `route_message` for an information need does NOT call `recall_offers` or the
   offer-index lookup and produces NO Connect / Not-relevant buttons. — unit test
   (mock recall_offers; assert not called; assert no action blocks).
3. [x] Resource needs (water/generator/shelter) are UNCHANGED: still recall offers +
   render Connect. — regression unit test.
4. [x] `need_type` for an info need no longer embeds the location (no "road safety:
   Learmonth"); location stays in `location`. — unit test.
5. [x] Guardrails rechecked: info answer never asserts safety, official items sourced +
   verify note, degraded explicit; no auto-action. A PASS skipping this is a FAIL.
6. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
7. [ ] [HUMAN] Live: "Is the road to Learmonth safe to drive?" → reply gives the
   official road-closure info + refusal + verify note, and NO irrelevant offer / Connect
   button. A resource need (e.g. "need water in North Exmouth") still shows offers +
   Connect.

## BDD scenarios
- Given "Is the road to Learmonth safe to drive?", When routed, Then no offer-recall
  runs and the reply has no Connect button (official road info only).
- Given "We need water in North Exmouth", When routed, Then offer-recall runs and
  matches render with Connect (unchanged).
- Given "Where can I get drinking water?", When routed, Then is_information is FALSE
  and offer-recall RUNS (a water offer is a valid match) — NOT suppressed.
- Given "Where do we evacuate?", When routed, Then is_information is TRUE, no
  offer-recall, official evac-centre info only.
- Given an info need, When parsed, Then need_type names the info sought without the
  location embedded.

## Out of scope
- Official-card *rendering* polish (task 028 — this task only decides info needs render
  official-only; 028 makes those official items structured cards).
- Fixing the general "foreign need surfaced as offer" recall-quality limitation for
  RESOURCE needs (task 014's documented limit) — separate; 030 only removes offer-recall
  from the INFORMATION path.

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `entities/models.py` — added `is_information: bool = False` to `Need` (default
  keeps every existing call-site + every resource need unchanged); docstring explains
  the info-vs-resource distinction.
- `agent/parsing.py` — added `is_information: bool = False` to `ParsedNeed`; broadened
  `PARSING_PROMPT` to set it TRUE for official-only questions (road safety/status,
  evac locations, official-warning status) and FALSE for resource requests including
  "where can I get <resource>"; stopped embedding the place in `need_type` for info
  needs (need_type = info sought, place stays in `location`); `parse_message` carries
  the flag onto the `Need`.
- `listeners/recall_reply.py` — `route_message` now branches on `need.is_information`:
  an info need skips `recall_offers` (no RTS call) and the offer-index lookup, returns
  a `NeedRecall` with empty `result`, NO blocks (no recall cards, no Connect/Not-relevant
  buttons), and an official-only `_INFORMATION_NEED_CONTEXT` llm_context. Resource path
  unchanged. Module docstring + `route_message` docstring document the info-vs-resource
  routing (chose the docstring route the spec allows over a new ADR — the flag is a
  thin, local routing branch that fits ADR-0004's passive-listening lineage, not a new
  architectural fork).
- `tests/unit/agent/test_parsing.py` — updated 029's info-question cases to assert
  `is_information=True`, no embedded location in `need_type`, place in `location`; added
  `RESOURCE_QUESTION_CASES` (incl. "where can I get water/fuel?") asserting
  `is_information=False`; added a default-False test.
- `tests/unit/listeners/test_recall_reply.py` — added `_info_need()` and four tests:
  info need does not call recall_offers/index, info need produces no blocks, info
  context is official-only, and a resource-need regression (still recalls + renders
  Connect actions).

**Tests**
- Unit: 449 passing, 0 failing, ZERO warnings (`filterwarnings=["error"]`). Double-run
  stable (ran `make pre-commit` and `make unit-tests` back to back — both 449 passed).
- Integration: 5 passed, 1 skipped (live-provider parse test, gated on an API key).

**Acceptance criteria → proving tests**
- [x] AC1 — `test_parse_info_question_returns_information_need` (is_information True for
  road safety/status + evac), `test_parse_where_can_i_get_resource_stays_resource_need`
  (is_information False incl. "where can I get water/fuel/formula/bed"),
  `test_parse_resource_need_defaults_is_information_false`.
- [x] AC2 — `test_information_need_does_not_recall_offers_or_index` (recall_offers +
  `offer_index.keyword_lookup` both assert-not-called),
  `test_information_need_produces_no_connect_blocks` (blocks == []),
  `test_information_need_context_is_official_only`.
- [x] AC3 — `test_resource_need_still_recalls_and_renders_connect` (recall_offers called
  once, `actions` block present); plus existing `test_need_returns_recall_without_posting`
  / `test_need_merges_index_and_rts_hits` unchanged and still green.
- [x] AC4 — `test_parse_info_question_returns_information_need` asserts the place is not
  in `need_type` and `result.location == location` (e.g. "road safety" / "Learmonth").
- [x] AC5 — guardrail recheck below.
- [x] AC6 — see Tests above.
- [ ] AC7 — [HUMAN] live verification (left unchecked).

**Evidence (e2e route_message smoke, real Need, Slack/RTS boundary mocked)**
```
=== Is the road to Learmonth safe to drive? (is_information=True) ===
  recall_offers called : False
  result               : []
  block types          : []
  has Connect/actions  : False
  llm_context (head)   : 'This is an INFORMATION need: it asks for official/situational information (road or travel '

=== need water in North Exmouth (is_information=False) ===
  recall_offers called : True
  result               : []         # zero matches in this mock -> "no offers" path
  block types          : ['section', 'section']
  has Connect/actions  : False      # no matches to render; Connect proven by AC3 unit test
  llm_context (head)   : 'No prior offers were found in the workspace for this need. Say so plainly; do not invent m'
```

**Guardrail recheck (AC5 — mandatory)**
1. *Never assert safety.* The info path runs no offer-recall and hands the LLM the
   `_INFORMATION_NEED_CONTEXT`, which explicitly says "Never assert that travel or a
   road is safe; surface the official information with its source and timestamp and
   tell the resident to verify before relying on it." The system prompt's standing
   refusal is untouched. PASS.
2. *Every official item sourced + UTC-stamped + verify note.* Sourcing/timestamping
   of official MCP items is the system prompt + (task 028) official-card rendering;
   this task does not weaken it. The info context reinforces "with its source and
   timestamp" and "verify before relying on it". No workspace match cards are rendered
   for an info need, so there is nothing unsourced added. PASS.
3. *Degraded states explicit.* The info path makes no RTS call, so there is no recall
   degradation to hide; the context tells the model "If an official feed is unavailable,
   say so plainly rather than guessing", and the MCP layer still returns structured
   errors. PASS.
4. *Human-in-the-loop / no auto-action.* The info path renders NO action buttons at all
   (blocks == []) — there is simply no auto-action to confirm for an information answer,
   and nothing fires automatically. The resource path's Connect confirmation step is
   unchanged. PASS.

**Notes**
- Did NOT touch `recall/blocks.py` rendering, `agent/agent.py` SYSTEM_PROMPT behavior,
  or `coordinator/` (per out-of-scope). The info path simply hands back empty `blocks`,
  which `listeners/reply.py::compose_reply` already extends harmlessly.
- The `tracker/` tree is untracked in git, so the file rename used `mv` (git mv failed —
  not under version control); flagging so the orchestrator stages it correctly at commit.
- AC7 live verification needs `slack run` + a provider key; left for the [HUMAN] gate.
- Not committed — handing off to the Tester for review of uncommitted work.

### [Tester] 2026-06-13 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` green; no warning/error/deprecation lines)
- Unit tests: 449 passed / 0 failed (double-run stable: 449 both runs)
- Integration tests: 5 passed / 0 failed, 1 skipped (`test_parsing_live` — gated on a live
  provider key, documented; double-run stable)
- Warnings: 0 (`filterwarnings=["error"]` in effect — zero warnings to pass: confirmed)

**E2E adversarial pass** (real `route_message` driven; Slack/RTS + offer-index mocked,
`parse_message` stubbed at the LLM boundary — LLM classification is the AC7 [HUMAN] gate)
- Happy path / Break path 1 (real INFORMATION Need, "Is the road to Learmonth safe to drive?",
  is_information=True): `route_message` → `recall_offers` NOT called, offer-index lookup NOT
  called, `result == []`, `blocks == []` (NO action/Connect block), `say()` not called,
  llm_context official-only (mentions "official", forbids inventing offers, forbids asserting
  safety, names degraded-feed handling). PASS
- Break path 2 (regression — real RESOURCE Need "need water in North Exmouth",
  is_information=False): `recall_offers` called once, `result == [match]`, rendered block types
  `[section, header, context, section, context, actions]` — Connect/actions row present. PASS
- Break path 3 (boundary / the load-bearing line — "where can I get drinking water?" as a
  RESOURCE Need, is_information=False): `recall_offers` called, `actions` block rendered — the
  water question is NOT suppressed, stays a resource need. PASS
- Break path 4 (failure mode — best-effort isolation on the RESOURCE path): `recall_offers`
  returns a `RecallError` (its real contract — `recall/client.py:68` "Never raises"); route
  degrades EXPLICITLY → `result` is `RecallError`, "couldn't search the workspace" section
  rendered, llm_context says "unavailable". Did NOT raise. Unchanged by 030. PASS
  (Note: an earlier probe injected a raw `RuntimeError` into `recall_offers`; that bypasses its
  documented contract — `recall_offers` catches `Exception` and returns `RecallError`
  [`recall/client.py:97-99`] — so it was a test-modelling artifact, not a defect.
  `test_need_with_degraded_recall_returns_unavailable` covers the real path and passes.)
- Borderline observation (judgment, final call = live model @ AC7): "is it safe to go to the
  evac centre?" blends road/travel-safety (→info) with an evac-centre reference (→info per the
  locked spec). Either classification routes official-only, so the routing layer is correct
  whichever the model picks; the flag itself is the LLM boundary's call. The load-bearing
  "where can I get water?" (resource) vs "is the road safe?" (info) line is pinned by
  `RESOURCE_QUESTION_CASES` + `INFO_QUESTION_CASES`.

**Acceptance criteria**
- [x] PASS — AC1 classification: info questions → is_information TRUE; resource needs incl.
      "where can I get <resource>?" → is_information FALSE.
      Evidence: `test_parse_info_question_returns_information_need` (road safety/status, evac →
      True), `test_parse_where_can_i_get_resource_stays_resource_need` (water/fuel/formula/bed →
      False), `test_parse_resource_need_defaults_is_information_false`; all 13 pass. PARSING_PROMPT
      `agent/parsing.py:38-49` encodes the rule; `is_information` carried onto the Need at
      `agent/parsing.py:141`. Tests mock the LLM via `FunctionModel` (the AC7 gate verifies live).
- [x] PASS — AC2 info-need routing: no `recall_offers`, no offer-index lookup, no Connect/
      Not-relevant blocks, official-only llm_context.
      Evidence: `listeners/recall_reply.py:404-415` returns early `NeedRecall(result=[], blocks=[],
      llm_context=_INFORMATION_NEED_CONTEXT)` before any recall; unit tests
      `test_information_need_does_not_recall_offers_or_index` (recall_offers + keyword_lookup both
      assert-not-called), `test_information_need_produces_no_connect_blocks` (`blocks == []`),
      `test_information_need_context_is_official_only`; plus my real-route Break path 1.
- [x] PASS — AC3 regression: resource needs ("need water", "where can I get water?") STILL run
      recall_offers + render Connect.
      Evidence: `test_resource_need_still_recalls_and_renders_connect` (recall_offers called once,
      `actions` block present); my real-route Break paths 2 + 3; resource branch
      `listeners/recall_reply.py:417-428` unchanged.
- [x] PASS — AC4 need_type for an info need does not embed the location; location stays in the
      location field.
      Evidence: `test_parse_info_question_returns_information_need` asserts `location not in
      result.need_type` and `result.location == location` (e.g. "road safety" / "Learmonth");
      PARSING_PROMPT `agent/parsing.py:51-55` instructs need_type "WITHOUT repeating the place".
- [x] PASS — AC5 guardrail recheck (4 explicit statements below).
- [x] PASS — AC6 pre-commit + unit + integration green, zero warnings, double-run stable.
      Evidence: see Test summary above.
- [ ] [HUMAN] AC7 — Awaiting human verification (live `slack run` + provider key). Routing
      contract that makes AC7 achievable is verified above; the LLM classification + official-card
      content is the live gate.

**Guardrail recheck (AC5 — mandatory, all 4 stated explicitly)**
1. Never assert safety — PASS. The info path injects `_INFORMATION_NEED_CONTEXT`
   (`listeners/recall_reply.py:78-92`): "Never assert that travel or a road is safe; surface the
   official information with its source and timestamp and tell the resident to verify before
   relying on it." The main SYSTEM_PROMPT refusal is untouched (`agent/agent.py` not in diff;
   "### Never assert safety." + "verify before relying on this" still present, lines 54/57/145).
2. Every official item sourced + UTC-stamped + verify note — PASS. The info context reinforces
   "with its source and timestamp" and "verify before relying on it". No workspace match cards
   are rendered for an info need (`blocks == []`), so nothing unsourced is added; official-card
   sourcing is the SYSTEM_PROMPT + task 028, not weakened here.
3. Degraded states explicit — PASS. The info path makes no RTS call, so there is no recall
   degradation to hide; the context says "If an official feed is unavailable, say so plainly
   rather than guessing." The MCP layer still returns structured errors. The resource path's
   degraded-recall behavior (`RecallError` → "couldn't search the workspace") is intact (Break
   path 4 + `test_need_with_degraded_recall_returns_unavailable`).
4. Human-in-the-loop / no auto-action — PASS. The info path renders ZERO action buttons
   (`blocks == []`) — there is no auto-action to confirm for an information answer, and nothing
   fires automatically. The resource path's Connect confirmation step is unchanged (Break paths
   2/3 render the `actions` row).

**Evidence**
```
$ make unit-tests        # run 1 and run 2
============================= 449 passed in 1.85s ==============================
============================= 449 passed in 1.89s ==============================
$ make integration-tests # run 1 and run 2
========================= 5 passed, 1 skipped in 0.97s =========================
========================= 5 passed, 1 skipped in 0.96s =========================
$ make pre-commit
============================= 449 passed in 2.43s ==============================
(no warning/error/deprecation lines in output)
```

**Scope check**
- `git diff --name-only` = exactly the 5 listed files (agent/parsing.py, entities/models.py,
  listeners/recall_reply.py, tests/unit/agent/test_parsing.py,
  tests/unit/listeners/test_recall_reply.py).
- NOT touched: `recall/blocks.py` rendering, `agent/agent.py` SYSTEM_PROMPT, `coordinator/`
  (all confirmed absent from the diff). No `print()` in changed library code. Types annotated
  (incl. `-> None` on tests). No `git add -A` stray files in the diff.

**Other issues found**
- None blocking. The SWE's evidence block (lines 188-193) noted "has Connect/actions: False" for
  the resource smoke because that mock returned zero matches; my Break path 2 supplied a match and
  confirmed the `actions` row renders — Connect is genuinely intact, not just "proven by unit
  test". No action needed.
- Untracked-tracker `mv`-rename note (SWE log) is an orchestrator staging concern, not a code
  defect; flagged, no impact on QA.

**VERDICT: PASS**
