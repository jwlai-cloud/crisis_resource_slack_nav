# 012 — Need-reply relevance pruning (official items)

(The context-cap + observability half of the original 012 shipped in the recall
round. The situation-board-on-Canvas half is now its own task 020. This task is the
remaining reply-brevity fix.)

Live finding (009): a need reply dumped the FULL official picture (every road
closure + water point + all evac centres) at one resident — too long, and most of
it irrelevant to their specific need.

## Acceptance criteria
1. [x] SYSTEM_PROMPT rule (the OFFICIAL DIRECTORIES section): when answering a need,
   include only official items DIRECTLY relevant to the parsed need —
   - a water/supply need → the water point(s), not the road list;
   - an explicit travel/road mention (or a "can I get to X" need) → the relevant
     closure(s);
   - a shelter need → evac centre(s).
   Cap the official items to ~2-3 lines. The model still states a degraded feed
   explicitly (guardrail 4 unchanged) and still never asserts safety.
2. [x] Add regression anchors to tests/unit/test_system_prompt.py pinning the pruning
   rule (so a future prompt edit that drops it fails CI), following the existing
   anchor pattern. All existing guardrail anchors must still pass.
3. [x] The road-safety refusal flow (demo "is the road safe?") is unaffected — that
   path surfaces the relevant advisory with source + verify note, which is exactly
   the relevant-item behaviour.
4. [ ] [HUMAN] live: a water need reply shows the water point but NOT the full road
   list; a "can I drive to Learmonth" need shows the Learmonth/Yannarie closures.

## Out of scope
The situation board section on the Canvas (task 020). Any code change to the MCP
tools (they already return everything; pruning is the model's compose-step job).

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `agent/agent.py` — appended one bullet to the OFFICIAL DIRECTORIES section of
  SYSTEM_PROMPT: the need-relevance pruning + brevity rule (prompt-only).
- `tests/unit/test_system_prompt.py` — added 6 parametrized anchors to
  `OFFICIAL_DIRECTORY_ANCHORS` + a dedicated
  `test_official_items_relevance_pruning_is_anchored` pinning the rule.

**Exact rule added** (final bullet of OFFICIAL DIRECTORIES, after the degraded-feed bullet):
> - Surface only the official items DIRECTLY relevant to the parsed need — do not
>   dump the full official picture. Match the directory to the need: a water,
>   drinking, or supply need surfaces the water point(s), not the whole road list;
>   an explicit travel or road mention (or a "can I get to X / is the road…" need)
>   surfaces the relevant closure(s); a shelter or somewhere-to-stay need surfaces
>   the evacuation centre(s). Keep the official items to roughly two or three
>   lines. Prune by relevance, never by hiding: a feed you consulted but could not
>   reach is still named (the degraded-state rule above is unchanged), and a
>   closure or advisory you surface is still relayed with its source and the
>   verify-before-relying note, never restated as a safety assertion of your own.

**Anchors added** (distinctive single-line substrings of the new text):
- `only the official items DIRECTLY relevant to the parsed need`
- `drinking, or supply need surfaces the water point(s)`
- `surfaces the relevant closure(s)`
- `shelter or somewhere-to-stay need surfaces`
- `Keep the official items to roughly two or three`
- `Prune by relevance, never by hiding`
Mirrored as explicit asserts in `test_official_items_relevance_pruning_is_anchored`.

**Tests**
- Unit: 348 passing, 0 failing (32 in test_system_prompt.py: 25 prior + 7 new).
  Red/green confirmed — new anchors failed on missing phrases before the prompt
  edit, all green after. No existing anchored text reworded.
- Integration: N/A — prompt-only change, no infra touched.

**Acceptance criteria**
- [x] AC1 — pruning + brevity rule added to OFFICIAL DIRECTORIES; need→directory
  mapping (water→water point / travel→closure / shelter→evac), ~2-3 line cap.
  Guardrail 4 (degraded feed named) and guardrail 2 (never assert safety)
  explicitly preserved in the same bullet.
- [x] AC2 — regression anchors added; all prior guardrail/placeholder/official-
  directory anchors still pass (`make pre-commit` → 348 passed).
- [x] AC3 — road-safety refusal flow unaffected: the "is the road safe?" wording
  in the Never-assert-safety guardrail is untouched; pruning rule cross-references
  it ("never restated as a safety assertion of your own") and the
  verify-before-relying note (2 occurrences, unchanged). Verified by printing the
  assembled section (Evidence below).
- [ ] [HUMAN] AC4 — NOT RUN: needs a live `slack run` turn (water need shows only
  the water point, "can I drive to Learmonth" shows Learmonth/Yannarie closures).
  Prompt-only change; behaviour is model-driven and only verifiable live.

**Evidence**
```
$ uv run pytest tests/unit/test_system_prompt.py -q
................................                                         [100%]
32 passed in 1.15s

$ make format-fix && make lint-fix && make format-check && make lint-check && make pre-commit
uv run ruff format        -> 86 files left unchanged
uv run ruff check --fix   -> All checks passed!
uv run ruff format --check-> 86 files already formatted
uv run ruff check         -> All checks passed!
make pre-commit           -> 348 passed in 3.24s   (filterwarnings=error → zero warnings)

$ uv run python -c "from agent.agent import SYSTEM_PROMPT; ..."
# guardrail-2 consistency: 'is the road safe?' present -> True;
# 'verify before relying on this' -> 2 occurrences (unchanged).
# New pruning bullet renders as the last bullet of OFFICIAL DIRECTORIES.
```

**Notes**
- SYSTEM_PROMPT + test_system_prompt.py only; no recall/mocks/coordinator/listeners
  touched (MCP tools still return everything — pruning is the model's compose-step
  job, per task Out-of-scope).
- Anchor phrases are deliberately single-line substrings: the prompt is hard-wrapped,
  so a cross-line phrase wouldn't be a contiguous substring. Anchors picked to stay
  stable under reflow while still being distinctive to the pruning rule.
- DID NOT commit (awaiting Tester PASS + PM ACCEPT).

### [Tester] 2026-06-13 14:50 — QA

Prompt-only change (guardrail-adjacent), so all four guardrails re-checked explicitly
against the post-edit text. Diff confined to `agent/agent.py` (+10) and
`tests/unit/test_system_prompt.py` (+30); the tracker rename
(`012-reply-brevity-situation-board.groomed.md` → `012-reply-pruning.in-progress.md`)
matches the documented task split (situation-board half → task 020). No unrelated files.

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 86 files OK; `ruff check`
  all passed; `make pre-commit` 348 passed)
- Unit tests: 348 passed / 0 failed (double-run, both green); test_system_prompt.py
  32 passed (25 prior + 7 new)
- Integration tests: N/A — prompt-only, no infra touched (correct)
- Warnings: 0 (`filterwarnings=error` in config; any warning would have errored)

**E2E adversarial pass** (the "feature" is the prompt string; exercised via
`from agent.agent import SYSTEM_PROMPT` + substring/section inspection)
- Happy path: all 6 new anchors are live substrings of SYSTEM_PROMPT → all True (PASS)
- Break path 1 (mutation / "do the anchors actually bite"): deleted the pruning bullet
  in-memory, re-checked the 6 new anchors → all flip to False. Confirms a future edit
  that drops the rule fails CI (PASS)
- Break path 2 (section placement): the bullet is contained inside `## OFFICIAL
  DIRECTORIES` (index 8623, after the degraded-feed bullet; OFFICIAL DIRECTORIES is the
  last `## ` section so no later header) (PASS)
- Break path 3 (regression / "did the edit reword anything"): all 20 pre-existing
  anchors — 4 guardrails, no-placeholder rule, parse→plan→rank→compose, the 009
  official-directory tool/sourcing/degraded anchors — still present, 0 missing (PASS)

**Guardrail re-check (mandatory — prune by relevance, NOT by hiding)**
- G1 human-decides: intact — "surface and rank options — a human decides" + "confirmation
  step" still present; pruning is a compose-step brevity rule, adds no auto-action.
- G2 never-assert-safety: NOT weakened — pruning bullet explicitly closes with "a closure
  or advisory you surface is still relayed with its source and the verify-before-relying
  note, never restated as a safety assertion of your own". "is the road safe?" refusal
  wording present; verify-before-relying note count unchanged at 2.
- G3 sourced+timestamped: intact — "Every item you surface carries a source and a
  timestamp." + "feed / fetched-at" + "carries a feed name and a `fetched_at` timestamp"
  untouched; pruning reaffirms a surfaced item still carries its source.
- G4 degraded-states-explicit: NOT weakened — this is the critical one. Pruning bullet
  states "Prune by relevance, never by hiding: a feed you consulted but could not reach
  is still named (the degraded-state rule above is unchanged)". The wording is relevance-
  filtering, never a license to silently drop a degraded feed. "Never silently skip a
  source" + "name the feed that could not" intact. PASS.

**Acceptance criteria**
- [x] PASS — AC1: pruning + brevity rule added to OFFICIAL DIRECTORIES with the full
      need→directory mapping (water/drinking/supply→water point, travel/road or
      "can I get to X / is the road…"→closure, shelter/somewhere-to-stay→evac) and a
      "roughly two or three lines" cap. Evidence: `agent/agent.py:156-165`; degraded
      (G4) + never-assert (G2) cross-refs verified above.
- [x] PASS — AC2: 6 regression anchors added to `OFFICIAL_DIRECTORY_ANCHORS` plus
      `test_official_items_relevance_pruning_is_anchored`; mutation test confirms they
      bite; all prior anchors still pass. Evidence: `tests/unit/test_system_prompt.py:108-116,136-154`;
      32 passed; 20/20 pre-existing anchors present.
- [x] PASS — AC3: road-safety refusal flow unaffected — "is the road safe?" wording
      untouched, verify-before-relying note count unchanged (2), pruning bullet
      cross-references the never-assert rule. Evidence: `agent/agent.py:59-61,147-150,165`.
- [ ] [HUMAN] AC4: Awaiting human verification — requires a live `slack run` turn
      (water need shows only the water point; "can I drive to Learmonth" shows the
      Learmonth/Yannarie closures). Model-driven, only verifiable live. Not a blocker.

**Evidence**
```
$ make pre-commit
uv run ruff format --check  -> 86 files already formatted
uv run ruff check           -> All checks passed!
uv run pytest tests/unit    -> 348 passed in 1.40s
=== PRE-COMMIT EXIT: 0 ===

$ make unit-tests  (re-run)  -> 348 passed in 1.41s   (EXIT 0)
$ uv run pytest tests/unit/test_system_prompt.py -q  (re-run) -> 32 passed (EXIT 0)

# Mutation test (delete pruning bullet in-memory) — 6 new anchors:
True True True True True True   (present in live prompt)
False False False False False False   (absent after deletion → anchors bite)
# Pre-existing anchors: True / 20 anchors, missing: []
# 'is the road safe?' present: True ; verify-before-relying occurrences: 2
```

**Other issues found**
- None. Diff is minimal and scoped; anchor substrings are single-line (resilient to the
  prompt's hard-wrap) — good choice, matches the existing anchor pattern.

**VERDICT: PASS** (AC1–AC3 verified with evidence; AC4 [HUMAN] awaiting live `slack run`,
not a Tester blocker). Hand off to PM for acceptance review.
