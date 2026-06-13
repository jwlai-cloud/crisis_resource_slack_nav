# 012 — Need-reply relevance pruning (official items)

(The context-cap + observability half of the original 012 shipped in the recall
round. The situation-board-on-Canvas half is now its own task 020. This task is the
remaining reply-brevity fix.)

Live finding (009): a need reply dumped the FULL official picture (every road
closure + water point + all evac centres) at one resident — too long, and most of
it irrelevant to their specific need.

## Acceptance criteria
1. SYSTEM_PROMPT rule (the OFFICIAL DIRECTORIES section): when answering a need,
   include only official items DIRECTLY relevant to the parsed need —
   - a water/supply need → the water point(s), not the road list;
   - an explicit travel/road mention (or a "can I get to X" need) → the relevant
     closure(s);
   - a shelter need → evac centre(s).
   Cap the official items to ~2-3 lines. The model still states a degraded feed
   explicitly (guardrail 4 unchanged) and still never asserts safety.
2. Add regression anchors to tests/unit/test_system_prompt.py pinning the pruning
   rule (so a future prompt edit that drops it fails CI), following the existing
   anchor pattern. All existing guardrail anchors must still pass.
3. The road-safety refusal flow (demo "is the road safe?") is unaffected — that
   path surfaces the relevant advisory with source + verify note, which is exactly
   the relevant-item behaviour.
4. [HUMAN] live: a water need reply shows the water point but NOT the full road
   list; a "can I drive to Learmonth" need shows the Learmonth/Yannarie closures.

## Out of scope
The situation board section on the Canvas (task 020). Any code change to the MCP
tools (they already return everything; pruning is the model's compose-step job).

## Log
