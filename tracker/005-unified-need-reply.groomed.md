# 005 — Unified need reply (kill the dual-reply UX)

Live testing (2026-06-12) exposed UX problems with the additive reply design from 003: the structured recall block and the LLM prose reply both answer the need, and the LLM — blind to the real RTS results — invents sources ("Source: User offer, posted [timestamp]" with a literal placeholder). User feedback: no real timestamp visible in the prose, no clear contact, and replies should name the user they're for.

## Acceptance criteria

1. ONE reply per need. Recall results (typed RecallMatch list or RecallError) are passed into the LLM call as context; the LLM composes around the real data. The structured match blocks remain the authoritative source display (LLM text must not restate sources).
2. Every rendered match carries a `Contact: <@author_id>` element (real mention, tappable) in addition to source/timestamp/permalink/verify note.
3. Channel replies open with a real mention of the requester (`<@user_id>`); DM replies may omit it.
4. System prompt addition (guardrail-adjacent, regression-anchored): never emit placeholder text (e.g. "[timestamp]"); if a value is unknown, omit the claim — covered by the degraded-states rule.
5. Unit tests: composition includes contact mention; prompt anchor test for the no-placeholder rule; listener flow posts exactly one reply for a need message.
6. Live verification: need message in DM and in #general — single reply, real timestamps, tappable contact, requester mentioned in the channel case.

## Depends on: 004 (need flow should consult the index + RTS together before this lands)

## Log
