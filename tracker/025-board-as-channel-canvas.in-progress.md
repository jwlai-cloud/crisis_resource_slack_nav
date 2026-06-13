# 025 — Board as the channel canvas (permanent top-bar tab)

UX, third iteration (user-driven): the board is a STANDALONE canvas, so it only
appears under "Files" and needs a bookmark (buried in the Bookmarks dropdown) or a
manual pin to reach. The native "always-visible top-bar tab" is a **channel canvas**.
Switch the board to the channel canvas of CRISIS_CHANNEL so it's a permanent tab —
no bookmark, no Files hunt, no manual add. Supersedes the 018 announce + 023 bookmark
as the discovery mechanism.

## Pre-work (SWE: research)
- `conversations_canvases_create(channel_id, document_content)` creates the channel's
  canvas (appears as a tab). Verify: what does it return (canvas_id)? Editing still
  uses `canvases_edit` (replace) — confirm.
- A channel has ONE canvas. Determine find-or-create: does conversations.info /
  conversations.canvases expose an existing channel-canvas id so we reattach instead
  of erroring on a second create? Check `conversations.info` (a `properties.canvas`
  field) or the create's behavior when one exists. The persisted canvas_id store
  (coordinator/canvas_store) still bridges processes; reattach to it first.
- Token/scope: confirm canvases:write (have it) covers channel-canvas create, or note
  any extra scope (+ re-install).

## Acceptance criteria
1. The board is created as CRISIS_CHANNEL's channel canvas via
   conversations_canvases_create (find-or-create: reattach to the persisted/known
   channel-canvas id, else create). It appears as a permanent channel tab.
2. Updates still use canvases_edit replace (full re-render) — unchanged composer.
3. The bookmark (023) becomes redundant — REMOVE the bookmark upsert from the create
   path (and the announce can stay as a one-time "board is live" note OR be dropped;
   keep it minimal). Leave bookmarks:* scope in the manifest (harmless) or remove —
   SWE's call, documented.
4. Best-effort + durable posture preserved: channel-canvas create/edit failures log
   and never break a button handler; the canvas is Slack-persisted (ADR-0005).
5. Update ADR-0005 (now: channel canvas, not standalone) — supersede the relevant
   consequence; note 018/023 discovery mechanisms are obsoleted by the tab.
6. Tests: channel-canvas create-vs-reattach, edit path unchanged, bookmark removal,
   best-effort. Existing coordinator tests updated. Zero warnings.
7. [HUMAN] live: after make board, #exmouth-mutual-aid shows a "Community Cases" tab
   in the top bar (no manual add); clicking it opens the board in-app; buttons still
   update it.

## Out of scope
Resident-vs-coordinator canvas separation (the channel canvas is shared — fine for
the demo). Multi-channel boards.

## Log
