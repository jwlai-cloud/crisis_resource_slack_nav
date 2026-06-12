# 010 — Action buttons: Connect / Mark resolved / Not relevant

Demo script beats 1:20–1:45: tap **Connect me** → DM to the offerer fires; tap **Mark resolved** → state change. The bounded-autonomy confirmation step (guardrail 1) becomes real UI.

## Acceptance criteria

1. Workspace match cards gain buttons: **Connect me** (primary) and **Not relevant**. After a connect, the connected card gains **Mark resolved**.
2. Connect me → opens/posts a group DM (requester + offerer) with a short sourced intro ("X needs …, Y offered … (posted <ts>) — connecting you both; verify details together"). Requires `mpim:write`/`im:write` (bot has im:write; check mpim — add scope to manifest if needed, note re-install requirement in the log).
3. Mark resolved → offer index `mark_resolved` (and need status when tracked) + visible confirmation (✅ on the card / short threaded ack). Resolved offers stop matching (004 behavior, now reachable via UI).
4. Not relevant → acknowledges + (for now) just visual dismissal state on the card; log the signal for future rank tuning.
5. Handlers in `listeners/actions/` following the template's action-handler pattern (feedback_buttons.py as reference); button `action_id`s carry the offer/need ids via `value` (JSON payload, typed parse on receipt).
6. Concurrency note from 004's Tester: mark_matched/mark_resolved are non-atomic get→copy→set — add the minimal lock (threading.Lock in OfferIndex) since button handlers now mutate from Bolt's thread pool. ADR-0003's revisit trigger fires; update the ADR status note.
7. Every button action appends to an in-memory audit trail (actor, action, target ids, ts) — thin precursor to W4's audit log; surface count in logs only for now.
8. Unit tests: handler routing (mocked ack/say/client), payload round-trip, index transitions via the handlers, lock behavior smoke. Zero warnings.
9. [HUMAN] live verification: full demo beat — need → match card → Connect me → DM fires → Mark resolved → card updates; screenshot evidence.

## Out of scope
Escalate (W4 coordinator flow), Canvas (W4), card colors/fields (008).

## Log
