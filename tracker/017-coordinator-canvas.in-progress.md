# 017 — Coordinator Canvas: live case board + audit log

W4 anchor (design doc §5 "Coordinator oversight"; demo beat 1:45–2:10). A Slack
Canvas shows coordinators a live board of community cases by status, plus the audit
trail of every human-confirmed action. The Canvas is Slack-persisted, so it doubles
as the durable board — it survives an agent restart even though the in-memory index
does not (this is the W4 answer to the ADR-0003 persistence gap for the *board*; the
matching index stays in-memory for speed and is the fast path, the Canvas is the
record of truth coordinators read).

## Pre-work (SWE: research the Canvas API first)
Slack Canvas APIs are new. Before coding, verify via context7 / docs.slack.dev:
- `canvases.create` / `canvases.edit` (or `conversations.canvases.create` for a
  channel canvas) — exact method names, the markdown/section payload shape, whether
  a standalone canvas or a channel-tab canvas fits a coordinator board best.
- Which token: the manifest grants `canvases:read`/`canvases:write` as USER scopes —
  confirm the bot can write a canvas with the user token we already have
  (SLACK_USER_TOKEN), or whether a bot scope is needed (add to manifest + note the
  re-install).
Record findings in the task log before implementing. If the API can't support a
live-updating canvas the way the design assumes, write an ADR documenting the
fork and the fallback (e.g. a pinned Block Kit "board message" updated via
chat_update).

## Acceptance criteria
1. A `canvas/` (or `coordinator/`) module that builds and updates the board from
   existing state — `offer_index.all_offers()` grouped by `Status`
   (open / matched / resolved) + `audit_trail.list_events()` as a dated activity
   log. Pure board-composition functions are unit-testable without Slack.
2. The board is created once (idempotent — find-or-create, keyed by a stored canvas
   id or a known title) and updated on every button action (Connect / Mark resolved
   / Not relevant) so it stays live. Update is best-effort: a Canvas API failure
   logs and never breaks the button handler (degraded-state guardrail).
3. Every case row is sourced + timestamped (offerer, channel/origin, when) and every
   audit line carries actor + action + target + time — same sourcing guardrail as
   the cards.
4. The board never asserts safety and never shows an auto-action — it is a record of
   human-confirmed actions only (it reads from the audit trail, which only the
   buttons write).
5. A `make`/script entry-point or a slash trigger to (re)create the board on demand
   for the demo, plus auto-create on first relevant action. Document how a
   coordinator opens it.
6. Persistence note: on restart the in-memory index is empty but the Canvas still
   holds the last board; document that the board is the durable artifact and the
   index rehydration question (RTS reseed) is deferred / its own task if needed.
   Update ADR-0003's revisit note and/or add ADR-0005 (Canvas as durable board).
7. Tests: board composition (status grouping, sourcing on every row, empty state),
   Canvas client mocked (no live API in unit tests); integration test only if the
   FastMCP-style test client pattern applies. Zero warnings.
8. [HUMAN] live: trigger the board in the sandbox; perform a Connect + Mark resolved;
   confirm the Canvas reflects the case moving open → matched → resolved and the
   audit log gains the lines. (Demo beat 1:45–2:10.)

## Out of scope
Situation board / official-info section (task 012 — can be a second Canvas section
later). SQLite persistence of the index (separate decision if rehydration proves
needed). Escalate button (W4 follow-on).

## Log
