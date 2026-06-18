# 029 — Answer crisis-relevant information/safety questions (parse them as Needs)

Verified live (2026-06-13): a resident posted "Is the road to Learmonth safe to drive?"
in the crisis channel. The agent received it, but `parse_message` returned
`NotACrisisMessage` (PARSING_PROMPT explicitly buckets "questions" as not-a-crisis),
so the passive listener logged "nothing to answer" and stayed **silent**. Passive
channel listening only answers **Needs** (resource requests) and acks **Offers**; a
safety/information question is neither → dropped as chatter.

This is the landing demo's headline "hard question" scenario — and it's silent in
reality. Fix: broaden parsing so a crisis-relevant *information* question classifies as
a **Need**, so the existing reply pipeline (recall + the LLM with the road-closure /
evac MCP tools) answers it — refusing to assert safety, pointing to official sources
(guardrail 2). No official-card rendering needed here; the LLM already weaves the MCP
road-closure info into prose. (Task 028 later upgrades that to structured cards.)

## Design decisions (locked)

- **Broaden PARSING_PROMPT, narrowly.** A question seeking crisis-relevant
  official/situational information is a **Need**:
  - road / travel safety ("is the road to X safe?", "can I drive to X?")
  - where to evacuate / shelter
  - where to get water / power / supplies
  - the status of an official warning / closure
  Extract `need_type` = the information sought (e.g. "road safety: Learmonth"),
  `location`, best-effort `urgency`, `household_size` default 1.
- **Keep the noise gate.** Greetings, thanks, social chatter, generic coordinator
  status updates ("power's back in town"), and off-topic questions STAY
  `NotACrisisMessage`. The line: a question an official feed or the workspace could
  answer about the disaster = Need; everything social/off-topic = NotACrisis. Do NOT
  widen to "all questions" — that re-introduces the channel noise ADR-0004 guards
  against (passive listening is one designated channel and must stay quiet on chatter).
- **No safety assertion (guardrail 2).** The reply to a safety question must refuse to
  judge safety and point to official sources with the verify note — this is already
  enforced by the main system prompt (agent/agent.py) and its regression tests; 029
  only changes *whether the question reaches that pipeline*, not how it answers. The
  main agent already has the `get_road_closures` MCP tool.
- **Scope = the parsing prompt + its tests only.** Do NOT touch recall/blocks.py,
  recall_reply wiring, or add official cards (that's 028). Do NOT change the main
  agent system prompt's behavior. PARSING_PROMPT is product code → live-verify.

## Implementation sketch
- `agent/parsing.py` PARSING_PROMPT: add the "information need" clause to the NEED
  definition and tighten the "Anything else … questions …" line so it reads
  "off-topic/social questions" rather than "questions" wholesale. Keep ParsedNeed
  fields unchanged (need_type/location/urgency/household_size).
- Tests: `tests/unit/agent/test_parsing.py` — add parametrized cases (mock the LLM
  boundary the same way the existing parsing tests do) asserting the classification
  CONTRACT the prompt should produce: the four info-question shapes → ParsedNeed with a
  sensible need_type/location; the social/off-topic shapes → NotACrisisMessage. If the
  existing parsing tests stub the model, mirror that; if any are live-gated
  (integration), keep them gated. Update any regression test that asserts a question is
  NotACrisis.
- If a parsing-prompt regression/snapshot test exists (test_system_prompt.py or
  similar), update it for the new wording.

## Acceptance criteria
1. [x] PARSING_PROMPT classifies a crisis-relevant information/safety question
   ("Is the road to Learmonth safe to drive?", "where do we evacuate?", "where can I
   get water?") as a **Need** with need_type = info sought + location extracted. —
   unit tests (LLM boundary mocked the same as existing parsing tests).
2. [x] Greetings / thanks / social / generic status / off-topic questions STILL
   classify as NotACrisisMessage (no new channel noise). — unit tests.
3. [x] No change to recall/blocks.py, recall_reply, or the main agent system prompt's
   answering behavior; the safety reply still refuses to assert safety + cites official
   sources (existing guardrail tests still green). — suite + grep.
4. [x] Parsing-prompt regression test updated; `make pre-commit` + unit + integration
   green, zero warnings, double-run stable.
5. [ ] [HUMAN] Live: post "Is the road to Learmonth safe to drive?" as a top-level
   message in the crisis channel → the agent replies (refusal + official road info from
   the MCP feed, verify note), instead of staying silent. A plain "thanks!" still gets
   no reply.

## BDD scenarios
- Given "Is the road to Learmonth safe to drive?", When parsed, Then ParsedNeed
  (need_type ~ road/travel safety, location ~ Learmonth).
- Given "where can we get drinking water?", When parsed, Then ParsedNeed.
- Given "thanks everyone, stay safe", When parsed, Then NotACrisisMessage.
- Given "anyone know a good podcast?", When parsed, Then NotACrisisMessage.

## Out of scope
- Official MCP cards / structured official rendering (task 028 — depends on this).
- Any change to how the reply is composed once it IS a Need.

## Log

### [SWE] 2026-06-13 14:30 — Implementation

**Files modified**
- `agent/parsing.py` — broadened PARSING_PROMPT: added an "information need" clause
  to the NEED definition (road/travel safety, where-to-evacuate/shelter,
  where-to-get-water/power/supplies, status-of-an-official-warning/closure → Need,
  with need_type = info sought, location, best-effort urgency default medium,
  household_size default 1); tightened the catch-all line from "questions" wholesale
  to "off-topic or social questions" and added an explicit rule that a question is a
  NEED only when an official feed / the workspace could answer it about the disaster,
  everything social/off-topic stays NotACrisisMessage (ADR-0004 noise gate intact).
  ParsedNeed fields unchanged.
- `tests/unit/agent/test_parsing.py` — added two parametrized classification-contract
  tests (LLM boundary mocked via FunctionModel, exactly as the existing parsing tests):
  `test_parse_info_question_returns_typed_need` (4 cases) and
  `test_parse_social_or_off_topic_stays_not_a_crisis` (4 cases).

**Tests**
- Unit: 440 passing, 0 failing, 0 warnings (`make unit-tests` / `make pre-commit`).
  `tests/unit/agent/test_parsing.py` went 5 → 13 tests.
- Integration: 5 passing, 1 skipped (`test_parsing_live` — live-gated, no provider
  key in CI; this is the AC5 live path). 0 warnings.
- Double-run stable: parsing tests run twice, 13 passed each time.

**Acceptance criteria**
- [x] AC1 — info/safety question → Need with need_type + location. Verified by
  `tests/unit/agent/test_parsing.py::test_parse_info_question_returns_typed_need`
  (Learmonth road-safety, "can I drive to Exmouth?", "where do we evacuate?",
  "where can we get drinking water?").
- [x] AC2 — greetings/thanks/social/status/off-topic questions stay NotACrisisMessage.
  Verified by `test_parse_social_or_off_topic_stays_not_a_crisis` (thanks, off-topic
  podcast question, "power's back in town" status, greeting) + existing
  `test_parse_chit_chat_returns_not_a_crisis_message`.
- [x] AC3 — no change to recall/blocks.py, recall_reply, or the main agent system
  prompt. `git diff --stat` shows only `agent/parsing.py` + `tests/unit/agent/
  test_parsing.py`. The guardrail-2 (never-assert-safety) anchors in
  `tests/unit/test_system_prompt.py` (pin SYSTEM_PROMPT) are untouched and still pass.
- [x] AC4 — no PARSING_PROMPT snapshot/regression test exists (it's referenced only in
  parsing.py; test_system_prompt.py pins SYSTEM_PROMPT, not PARSING_PROMPT), so none
  needed updating; pre-commit + unit + integration green, zero warnings, double-run
  stable.
- [ ] AC5 — [HUMAN] live post in the crisis channel. Needs a live `slack run` + a
  real provider key; left unchecked for human verification.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
94 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
...
tests/unit/agent/test_parsing.py .............                           [  2%]
...
============================= 440 passed in 2.19s ==============================

$ make integration-tests
...
SKIPPED [1] tests/integration/agent/test_parsing_live.py:30: no live provider key configured
========================= 5 passed, 1 skipped in 1.09s =========================

$ # end-to-end through parse_message (override prevents a live call; dummy key only
$ #   so get_model() resolves, exactly as the autouse unit conftest does)
LEARMONTH Q  -> Need | need_type= road safety: Learmonth | location= Learmonth | urgency= medium
THANKS       -> NotACrisisMessage
```

**Notes**
- 029 is parsing-prompt-only. NO change to the main agent system prompt
  (`agent/agent.py`), `recall/blocks.py`, `recall_reply`, or any official-card code —
  those are task 028. Confirmed via `git diff --stat`.
- No PARSING_PROMPT snapshot test exists to update; the parsing unit tests assert the
  classification *contract* (mocked LLM boundary), not prompt text — matching the
  existing parsing-test style.
- The genuinely-live LLM check is AC5 (`test_parsing_live` is skipped without a key,
  and the live `slack run` post is the [HUMAN] step). The end-to-end run above uses the
  FunctionModel override to demonstrate the full `parse_message` wrapping under the
  intended classification; it does not call a real provider.

### [Tester] 2026-06-13 16:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`94 files already formatted`, `All checks passed!`, 440 unit passed)
- Unit tests: 440 passed / 0 failed (double-run stable: 440 both runs)
- Integration tests: 5 passed / 1 skipped (`test_parsing_live` — live-gated, AC5 path) / 0 failed (double-run stable)
- Warnings: 0 (`pyproject.toml:75 filterwarnings = ["error"]` is active; any warning would error a test, none did)
- `tests/unit/agent/test_parsing.py`: 5 → 13 tests, all PASS under `-W error`

**E2E adversarial pass** (through `parse_message` under `FunctionModel` override — the model boundary mocked exactly as existing parsing tests; NO live provider)
- Happy path: "Is the road to Learmonth safe to drive?" → `Need` | need_type=`road safety: Learmonth` | loc=`Learmonth` | urgency=`medium` (PASS)
- Break path 1 (boundary: empty string): `""` → `NotACrisisMessage` (PASS — no crash)
- Break path 2 (boundary: empty location on where-question): "where do we evacuate?" → `Need` | loc=`''` (PASS — wraps cleanly with blank location, matches AC1 contract)
- Break path 3 (malformed: invalid urgency "BANANA"): → `ValidationError` raised by `Need` validator vs expected rejection (PASS — broadened parse path inherits entity-level validation; no silent corruption)
- Break path 4 (noise gate: off-topic question "anyone know a good podcast?"): → `NotACrisisMessage` (PASS — ADR-0004 gate held, prompt did NOT over-broaden to "all questions")
- Break path 5 (noise gate: generic status "power's back in town"): → `NotACrisisMessage` (PASS)
- Break path 6 (timestamp guardrail: naive ts on info-need path): "where can I get water?" w/ naive datetime → `ValueError: source_ts must be timezone-aware (UTC)` (PASS — guardrail still applies on the new path)

**Acceptance criteria**
- [x] PASS — AC1: crisis-relevant info/safety question → `Need` w/ need_type + location.
      Evidence: `test_parse_info_question_returns_typed_need` (4 cases: Learmonth road-safety, "can I drive to Exmouth?", "where do we evacuate?", "where can we get drinking water?") all PASS; prompt clause added `agent/parsing.py:29-39`; e2e happy-path run confirms `Need` wrapping w/ trust-critical fields (requester/source_ts/id/Status.OPEN). Model boundary mocked via `FunctionModel`, not live.
- [x] PASS — AC2: greetings/thanks/social/generic status/off-topic questions STILL `NotACrisisMessage`.
      Evidence: `test_parse_social_or_off_topic_stays_not_a_crisis` (4 cases) + existing `test_parse_chit_chat_returns_not_a_crisis_message` all PASS; prompt catch-all tightened to "off-topic or social questions" with explicit "a question is only a NEED when an official feed or the workspace could answer it about the disaster" rule (`agent/parsing.py:42-46`) — noise gate NOT over-broadened.
- [x] PASS — AC3 (SCOPE): no change to recall/blocks.py, recall_reply, or main agent system prompt.
      Evidence: `git diff --name-only` = ONLY `agent/parsing.py` + `tests/unit/agent/test_parsing.py`. `git diff --stat` over agent/agent.py, recall/blocks.py, listeners/, tests/unit/test_system_prompt.py = empty (untouched). Guardrail-2 anchors in `tests/unit/test_system_prompt.py` ("Never assert safety.", "verify before relying on this") unchanged; `test_system_prompt.py` 32 passed standalone.
- [x] PASS — AC4: pre-commit + unit + integration green, zero warnings, double-run stable.
      Evidence: see Test summary above.
- [ ] [HUMAN] — AC5: live post in crisis channel. Awaiting human verification (needs live `slack run` + real provider key). `test_parsing_live` is correctly live-gated/skipped in CI.

**GUARDRAIL RE-CHECK (mandatory — change is in the parse path feeding safety questions)**
029 changes ONLY *whether* a crisis-relevant question reaches the answering pipeline (parse classification), NOT *how* it is answered. The never-assert-safety behavior lives entirely in `agent/agent.py`'s `SYSTEM_PROMPT` (untouched, confirmed via empty `git diff --stat`) and is pinned by `tests/unit/test_system_prompt.py` guardrail anchors (untouched, 32 passed). I confirm all four guardrails remain intact:
1. Human-decides / confirmation step — unaffected (no listener/action change).
2. Never assert safety — anchors "Never assert safety." + "verify before relying on this" present in SYSTEM_PROMPT, regression tests green.
3. Sourced + timestamped — official-directory anchors (feed/fetched-at/verify note) green.
4. Degraded states explicit — feed-error anchor green.
A broadened question now *reaches* the answering LLM, which already refuses to assert safety and cites official sources via the unchanged system prompt + MCP tools.

**Adversarial classification note (non-blocking)**
Tests pin the classification CONTRACT via a mocked model (`FunctionModel`), not the live model's judgment — correct, since final classification is the live model's job (AC5). The tests are NOT tautological: beyond echoing the mocked output, they verify `parse_message` wraps each result into the right entity with the trust-critical source fields (requester/source_ts/deterministic id/Status.OPEN) and cover boundary cases (naive-ts rejection, idempotency). Borderline shapes are covered both ways: "is it safe to go to the evac centre?" maps to the road/travel + where-to-shelter clause → Need; "anyone heard when power's back?" / "power's back in town" are generic status → NotACrisis (tested). The line drawn by the prompt is sensible; any residual ambiguity is the live model's call (AC5), not a blocker.

**Evidence**
```
$ git diff --name-only
agent/parsing.py
tests/unit/agent/test_parsing.py

$ make pre-commit
uv run ruff format --check
94 files already formatted
uv run ruff check
All checks passed!
============================= 440 passed in 1.97s ==============================

$ make integration-tests
SKIPPED [1] tests/integration/agent/test_parsing_live.py:30: no live provider key configured
========================= 5 passed, 1 skipped in 0.99s =========================

$ uv run pytest tests/unit/agent/test_parsing.py -v -W error
============================== 13 passed in 0.95s ==============================
```

**Other issues found**
- None blocking. The untracked tracker files (`tracker/028-official-mcp-cards.groomed.md`, `tracker/029-...in-progress.md`) are spec docs, not code in scope — correct.

**VERDICT: PASS**
