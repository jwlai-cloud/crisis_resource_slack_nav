# 001 — Crisis Navigator system prompt

Replace the template's generic assistant `SYSTEM_PROMPT` in `agent/agent.py` with the Crisis Resource Navigator product prompt. The prompt is product code (CLAUDE.md guardrails section) — version-controlled, tested against live runs.

## Acceptance criteria

- [x] 1 — [x] 2 — [x] 3 — [x] 4 — [x] 5 — [x] 6 — [ ] 7 [HUMAN, NOT RUN] (see Log)

1. Prompt enforces the loop: **parse** (need/offer → structured fields: need_type, location, urgency, household_size) → **plan** (which sources to consult) → **rank** → **compose**.
2. All four guardrails embedded:
   - surfaces and ranks; a human decides (every actionable match ends in a confirmation action, never auto-action)
   - never asserts safety (no "road is safe", no placement decisions; always "verify before relying on this")
   - every item sourced + timestamped (who/when for workspace matches, feed/fetched-at for external)
   - degraded states explicit (a source being unavailable is stated, never silently skipped)
3. Persona: calm, plain language, no humor (crisis context — replaces template's "lightly witty").
4. Keeps the emoji-reaction tool instruction working (template behavior) but tones reactions to crisis-appropriate (e.g. 👀 acknowledged, ✅ resolved).
5. Slack MCP server section retained (it powers workspace search until our RTS integration lands).
6. Unit test: prompt constant contains the four guardrail phrases (regression anchor — prompt edits that drop a guardrail fail CI).
7. Live verification: `slack run` + a need message ("Family of 4, North Exmouth, no power — need water and a generator") produces a reply that (a) does not assert safety, (b) includes a verify note, (c) asks for/uses structured fields, (d) offers no automatic action.

## Scenarios

- **Resident posts a need** → agent acknowledges, parses into fields, states which sources it would consult, replies with verify-framing.
- **Resident asks "is the road safe?"** → agent refuses to assert safety; points at official sources with timestamps + verify note.
- **No matching info** → agent says so explicitly; no fabrication.

## Out of scope

RTS calls, matching index, action buttons (tasks 002–004, W3).

## Log

### [SWE] 2026-06-12 13:08 — Implementation

**Files modified**
- `agent/agent.py` — replaced the template's generic assistant `SYSTEM_PROMPT` with the Crisis Resource Navigator product prompt: parse → plan → rank → compose loop with the four structured fields, all four guardrails embedded, calm/plain-language crisis persona (humor stripped), muted crisis-appropriate emoji-reaction instruction (still invokes `add_emoji_reaction`), Slack MCP capability section retained as the workspace-search capability until RTS lands.
- `tests/unit/test_system_prompt.py` — new regression test: pins a distinctive anchor phrase per guardrail (parametrized), plus loop/fields, persona, and emoji+MCP retention.

**Tests**
- Unit: 18 passing, 0 failing (12 new in `test_system_prompt.py` + 6 pre-existing) — `make pre-commit` output below. Zero warnings (`filterwarnings=error`).
- Integration: N/A — no infra changes.

**Acceptance criteria**
- [x] 1. Loop parse → plan → rank → compose with fields need_type/location/urgency/household_size — verified by `tests/unit/test_system_prompt.py::test_prompt_enforces_parse_plan_rank_compose_loop`.
- [x] 2. All four guardrails embedded — verified by `tests/unit/test_system_prompt.py::test_guardrail_phrase_present` (8 anchor phrases) + `test_all_four_guardrails_have_anchors`.
- [x] 3. Persona calm/plain/no humor — verified by `tests/unit/test_system_prompt.py::test_prompt_drops_template_humor_persona` (asserts "witty" gone, "no humor"/"no jokes" present).
- [x] 4. Emoji-reaction tool still invoked, reactions toned to crisis-appropriate (`eyes` acknowledged, `white_check_mark` resolved; jokey/celebratory disallowed) — verified by `tests/unit/test_system_prompt.py::test_prompt_retains_emoji_reaction_and_mcp_sections`.
- [x] 5. Slack MCP server section retained — verified by `tests/unit/test_system_prompt.py::test_prompt_retains_emoji_reaction_and_mcp_sections`.
- [x] 6. Unit test asserting the four guardrail phrases as regression anchors — `tests/unit/test_system_prompt.py`.
- [ ] 7. [HUMAN] Live `slack run` verification — NOT RUN: no TTY in this environment / `slack run` is run elsewhere. Needs manual verification by the human: post "Family of 4, North Exmouth, no power — need water and a generator" and confirm the reply (a) does not assert safety, (b) includes a verify note, (c) asks for/uses structured fields, (d) offers no automatic action.

**Evidence**
```
$ make format-fix && make lint-fix && make format-check && make lint-check && make pre-commit
uv run ruff format
23 files left unchanged
uv run ruff check --fix
All checks passed!
uv run ruff format --check
23 files already formatted
uv run ruff check
All checks passed!
uv run ruff format --check
23 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.6.0
collected 18 items

tests/unit/test_app_home_opened.py ..                                    [ 11%]
tests/unit/test_system_prompt.py ............                            [ 77%]
tests/unit/test_view_builders.py ....                                    [100%]

============================== 18 passed in 1.01s ==============================
```

**Notes**
- Scope held: only `agent/agent.py` (the SYSTEM_PROMPT constant) and the new test file changed. No edits to `listeners/`, `pyproject.toml`, `.env.example`, or any other task's surface; the emoji-reaction tool body (`agent/tools/emoji_reaction.py`) was left untouched — only the prompt's reaction instruction was retoned.
- AC 7 live run NOT RUN (reason above). All AC 7 behaviors are instructed in the prompt but only a live run proves the model honors them.
- Not committed — changes left in the working tree for Tester review.

### [Tester] 2026-06-12 13:42 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 23 files formatted; `ruff check` all passed; pre-commit gate green)
- Unit tests: 18 passed / 0 failed (12 new in `test_system_prompt.py` + 6 pre-existing)
- Integration tests: 0 collected (none exist yet — `tests/integration/` holds only `.gitkeep`; no infra change in this task) — exit 0
- Warnings: 0 (re-ran `test_system_prompt.py` with `-W error`, all 12 pass; project pins `filterwarnings=["error"]`)
- `code-review` plugin: N/A (no `.claude/settings.json` in repo)

**E2E adversarial pass** (this is a prompt-content task; "the feature" = the regression net + the prompt's product correctness)
- Happy path: `importlib.import_module('agent.agent')` → module imports, `Agent` constructs with new 5343-char prompt, `tools=[add_emoji_reaction]` + `system_prompt=SYSTEM_PROMPT` wired (PASS)
- Break path 1 (regression-net strength — gut a guardrail body, keep its header): simulated removing each guardrail's body text while keeping the `###` header → all four guardrails CAUGHT (test fails). `never assert safety` and `degraded states explicit` each have one header-only anchor, but each is paired with a BODY anchor (`verify before relying on this`, `Never silently skip a source`) that trips the test — so no guardrail can be silently gutted. (PASS — net holds)
- Break path 2 (template-humor remnant scan): scanned for `witty`, `humor when appropriate`, `lightly witty`, `creative and specific`, `be creative`, `casual, conversational`, `touch of humor`, `punchy` → all absent. Only `jokey` appears, inside the prohibition line "Do not use playful, jokey, or celebratory emoji" (correct, not a remnant). (PASS)
- Break path 3 (BDD-scenario instruction coverage): "is the road safe?" + "do not answer yes or no" present; "found no matching information" + "rather than fabricating" present; "State which sources you are consulting" present; "ask one brief clarifying question" present. All three spec scenarios are instructed. (PASS)

**Four guardrails re-checked against actual prompt text** (CLAUDE.md mandate for guardrail-touching changes)
- Human decides: "You surface and rank options — a human decides... Every actionable match ends by inviting the human to confirm it (a confirmation step), never an automatic action." (agent/agent.py:46-49) — SATISFIED
- Never assert safety: "Never state that a road is safe... always include the note: verify before relying on this... If asked directly \"is the road safe?\", do not answer yes or no" (agent/agent.py:52-58) — SATISFIED
- Sourced + timestamped: "Every item you surface carries a source and a timestamp. For a workspace match, show who posted it and when (who/when). For an external result, show which feed it came from and when it was fetched (feed / fetched-at). No item appears without its source and time" (agent/agent.py:61-65) — SATISFIED
- Degraded states explicit: "If a source is unavailable, say so explicitly — name the source that could not be reached... Never silently skip a source and never invent or guess data" (agent/agent.py:68-71) — SATISFIED

**Acceptance criteria**
- [x] PASS — AC1 loop parse→plan→rank→compose + 4 fields — `parse → plan → rank → compose` present, all of need_type/location/urgency/household_size present, all four `**Parse/Plan/Rank/Compose.**` steps present (agent/agent.py:24-41); `test_prompt_enforces_parse_plan_rank_compose_loop` passes
- [x] PASS — AC2 four guardrails embedded — verified line-by-line above (agent/agent.py:43-71); 8 anchor assertions in `test_guardrail_phrase_present` + `test_all_four_guardrails_have_anchors` pass
- [x] PASS — AC3 persona calm/plain/no humor — "Calm, steady, and reassuring", "No jargon, no humor, no jokes, no playful asides" (agent/agent.py:18-20); `witty` absent; `test_prompt_drops_template_humor_persona` passes
- [x] PASS — AC4 emoji-reaction tool retained + crisis-toned — `add_emoji_reaction` referenced, `eyes`/`white_check_mark` examples, "Do not use playful, jokey, or celebratory emoji" (agent/agent.py:83-88); `test_prompt_retains_emoji_reaction_and_mcp_sections` passes
- [x] PASS — AC5 Slack MCP section retained — `## SLACK MCP SERVER` header, RTS-bridge note, Search/Read/Write/Canvases capabilities (agent/agent.py:90-103)
- [x] PASS — AC6 regression test asserting guardrail phrases — `tests/unit/test_system_prompt.py`, 12 tests, all guardrails body-anchored (gutting-resilient per break path 1)
- [ ] NOT RUN — AC7 live `slack run` verification — [HUMAN]. Correctly deferred by SWE: no TTY / sandbox here. All AC7 behaviors (no-assert-safety, verify note, structured fields, no auto-action) are instructed in the prompt, but only a live model run proves they are honored. Awaiting human verification.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
23 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
collected 18 items
tests/unit/test_app_home_opened.py ..                                    [ 11%]
tests/unit/test_system_prompt.py ............                            [ 77%]
tests/unit/test_view_builders.py ....                                    [100%]
============================== 18 passed in 1.05s ==============================

$ make integration-tests
collected 0 items
============================ no tests ran in 0.01s =============================  (exit 0)

$ uv run pytest tests/unit/test_system_prompt.py -v -W error
12 passed in 1.04s
```

**Other issues found**
- None blocking. Diff scope is clean: only `agent/agent.py` modified + the new test file (the untracked tracker/00{2,3,4} files belong to other tasks, not this diff). No `print()`, no naive datetime, no secrets introduced in the touched file.
- Minor note (non-blocking, not in AC): two guardrails carry one header-only anchor each. The net still holds because each is paired with a body anchor. If a future task wants belt-and-suspenders, consider making every anchor body-text. Not required for PASS.

**VERDICT: PASS** — all six non-[HUMAN] acceptance criteria verified with evidence; full suite green with zero warnings; four guardrails individually re-checked against prompt text; adversarial pass confirms the regression net cannot be silently gutted and no template-humor remnants survive. AC7 correctly marked NOT RUN (human/live-run gate). Hand off to PM for acceptance review.

### [Human] 2026-06-12 13:30 — AC7 live verification
Live in sandbox DM, new prompt loaded:
- Need message ("Family of 4, North Exmouth...") → parsed all four fields, stated sources consulted, explicit no-match (no fabrication), next step routed to human coordinator, eyes reaction. PASS.
- "Is the road to Learmonth safe to drive?" → refused to confirm safety, pointed to official government advisories, "Verify information before relying on it." PASS.
AC7 complete — task done.
