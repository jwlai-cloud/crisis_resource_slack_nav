# 0005. Slack Canvas as the durable coordinator board

**Status:** Accepted
**Date:** 2026-06-13
**Amended:** 2026-06-13 (task 025) — the board is now the **channel canvas** of
`CRISIS_CHANNEL`, a permanent top-bar tab, superseding the original *standalone*
canvas. See the "Amendment — channel canvas (task 025)" section at the end; the
core decision (Slack Canvas as the durable, full-replace board on the user token)
stands.

## Context

W4's coordinator-oversight surface (task 017; design doc §5) is a board a
coordinator reads to see every community case grouped by lifecycle status, plus
the dated audit log of every human-confirmed action. The two state sources that
feed it — the matching index (`matching/index.py`) and the audit trail
(`matching/audit.py`) — are both **process-local and in-memory** by deliberate
decision (ADR-0003 and its sibling note for the trail): they die with the socket-
mode process.

That leaves a gap ADR-0003 explicitly deferred to a "future fork with its own ADR":
> If a future requirement needs durable matching state (e.g. the coordinator
> Canvas surviving restarts, W4), that is a new fork with its own ADR.

This is that fork. The coordinator needs a board that:

- survives an agent restart (a coordinator on shift should not lose the board when
  the process bounces), and
- is a record coordinators can open and read in Slack, not just an in-memory
  structure the agent holds.

The forces:

- **Durability of the *record*.** What a coordinator reads must not vanish with the
  process. But the matching *index* is a latency optimisation, not the system of
  record (ADR-0003) — we do not want to promote it to a durable store and take on a
  schema + migration + reconciliation burden the demo scope rejects.
- **Live updates.** The board should reflect a case moving open -> connected ->
  resolved as the buttons are pressed, without a coordinator re-running anything.
- **No second datastore.** ADR-0003 chose "the cheapest thing that works" and kept
  the workspace (via RTS) as the only durable store. A new SQLite/Redis just for the
  board would re-introduce exactly the second source of truth ADR-0003 avoided.

Candidates: (A) a Slack **Canvas** authored via the Canvas API, kept current by
re-rendering on every button action; (B) a pinned Block Kit "board message" in a
coordinator channel updated via `chat_update`; (C) a small embedded datastore
(SQLite/JSON) the agent reads/writes and renders on demand.

Canvas API research (recorded in the task-017 log, 2026-06-13): the installed
`slack_sdk` 3.42 exposes `canvases_create` and `canvases_edit`. `canvases.edit`
with a single `replace` operation and **no** `section_id` overwrites the entire
canvas document — so a board can be re-rendered wholesale from current state on
every update, no per-section diffing. `canvases:write` works on the user token the
app already holds (`SLACK_USER_TOKEN`), so no new bot scope or re-install is needed.
Slack persists the canvas, so option A is durable *for free* — Slack is the store.

## Decision

Use a **Slack Canvas as the durable coordinator board** (option A).

- `coordinator/board.py` is a pure `state -> markdown` composer: it groups
  `offer_index.all_offers()` by `Status` (open / connected / resolved) and renders
  `audit_trail.list_events()` as a dated activity log. No Slack, fully unit-tested.
- `coordinator/canvas.py` is the publisher: it find-or-creates the canvas
  (`canvases.create` once, storing the returned `canvas_id` in a process-local
  field) and on every later update **replaces the whole document**
  (`canvases.edit` `replace`, no `section_id`) with a freshly composed board. The
  write authenticates as the acting user via a per-call `Authorization` header
  override of `SLACK_USER_TOKEN` — the same pattern `recall.client` uses for the
  user-scoped search call.
- The three button handlers (`listeners/actions/crisis_buttons.py`) call
  `update_board` **after** their own work, isolated: `update_board` /
  `CoordinatorBoard.publish` are best-effort and **never raise** (a Canvas failure
  is logged and swallowed), so a board problem can never break Connect / Resolve /
  Dismiss (degraded-state guardrail).
- An on-demand entry point (`scripts/open_board.py`, `make board`) (re)creates the
  board for the demo.

The **in-memory index stays the fast path** (ADR-0003 unchanged): the index is
still the latency optimisation for matching, the Canvas is the durable record the
coordinator reads. The two are not the same artifact and do not need to be kept
consistent across processes — the Canvas is rendered *from* the index + trail, it
does not feed them back.

## Consequences

- **The board's content is durable; the canvas handle is not.** Slack persists the
  canvas document across an agent restart. But the `canvas_id` lives in a
  process-local field, so after a restart that handle is lost: the next
  demand-trigger creates a *fresh* canvas rather than re-attaching to the prior
  one. The last board's *content* survives in Slack; reattaching to it across
  restarts (e.g. persisting the id, or looking the canvas up by title) is a
  deferred follow-on, out of W4 scope. For the demo the coordinator opens the board
  on demand.
- **Index rehydration is still deferred.** On restart the in-memory index is empty,
  so a freshly created board renders empty status groups (with explicit empty-state
  lines) until new offers come in. Reseeding the index from the workspace via RTS on
  startup is a separate decision (its own task if rehydration proves needed) — this
  ADR does not take it on. The board honestly shows what the live index holds.
- **No second datastore.** Slack is the durable store for the board, exactly as the
  workspace (via RTS) is the durable store for offers (ADR-0003). No schema, no
  migration, no reconciliation — consistent with ADR-0003's "cheapest thing that
  works".
- **Best-effort, never blocking.** A Canvas API outage degrades to "the board is
  stale / not created" and is logged; it never blocks or breaks a human-confirmed
  button action. This is the degraded-state guardrail applied at the board layer.
- **User-token dependency.** The board needs `SLACK_USER_TOKEN` (user
  `canvases:write`). Without it the update is skipped and logged — never falls back
  to the bot token (which the manifest does not grant `canvases:write`). If we later
  want the *bot* to own the canvas, that is a manifest scope addition + re-install,
  noted but not done here since the user token already works.
- **Whole-document replace.** Each update re-renders and overwrites the full canvas.
  For a demo-scale board this is simplest and avoids section-id bookkeeping; a very
  large board would want incremental section edits (`canvases.sections.lookup` +
  targeted ops), which is a future optimisation, not a v1 need.

## Amendment — channel canvas (task 025)

The original decision made the board a **standalone** canvas (`canvases.create`).
That works, but a standalone canvas only surfaces under the channel's "Files" list,
so reaching it needed a discoverability scaffold: a one-time link announce (task
018) and a top-of-channel bookmark (task 023). Both are indirection around a canvas
that is not *natively* placed.

Slack's native always-visible placement for a board is the **channel canvas**: every
channel may have exactly one, and it renders as a permanent tab in the channel's top
bar. Access is tied to channel access — no share step, no bookmark, no Files hunt.

**Amended decision.** The board is the channel canvas of `CRISIS_CHANNEL` (the same
channel the passive-listening gate uses, ADR-0004; read via
`listeners.channel_gate.designated_channel_id`, not a duplicated env read).
`coordinator/canvas.py` now:

- **Find-or-creates** the channel canvas: reattach to the persisted id
  (`coordinator/canvas_store.py`, the cross-process bridge) → else discover the
  channel's already-attached canvas via `conversations.info`
  (`channel.properties.canvas.file_id`) and reattach → else
  `conversations.canvases.create(channel_id=…, document_content=…)`, which flips on
  the tab. A `channel_canvas_already_exists` race on create re-discovers and
  reattaches rather than erroring (a channel has only one canvas).
- **Edits unchanged.** A channel canvas is edited by the *same* `canvases.edit`
  (`replace`, no `section_id`); there is no separate channel-canvas edit. The
  whole-document recompose model is untouched.
- **Scope unchanged.** `conversations.canvases.create` uses the same
  `canvases:write` user scope the standalone create used — no new scope, no
  re-install. The only added requirement is channel *membership* (public channel,
  or the user invited to a private one), which the demo already satisfies.

**Discovery mechanisms obsoleted.** The tab is the discovery now:

- The task-023 **bookmark** is removed from the create path — the permanent tab
  supersedes it. The `bookmarks:*` manifest scope and the `coordinator/bookmark.py`
  module are left in place (harmless, no cost) rather than ripped out.
- The task-018 **announce** is kept as a *minimal* one-time "the Community Cases
  board tab is live" courtesy note on create only (never on edits) — it costs
  nothing and nudges a coordinator not yet looking at the channel. It is no longer
  the discovery mechanism, just a convenience; dropping it entirely would also have
  been acceptable.

**Restart reattach is now solved, not deferred.** The original ADR deferred
re-finding the prior canvas across a restart (the `canvas_id` lived only in a
process-local field). As a channel canvas the board is re-findable from Slack
itself: when the persisted id file is gone, the create path discovers the channel's
existing canvas via `conversations.info` and reattaches. So a restart no longer
mints a fresh canvas — it reattaches to the channel's one canvas. (The persisted
store remains the primary, faster reattach key; `conversations.info` is the
fallback.) The first consequence above — "the board's content is durable; the canvas
handle is not" — is superseded by this for the channel-canvas case.

**Best-effort posture preserved.** Create / discover / edit failures (and an unset
`CRISIS_CHANNEL`) are logged and swallowed; the publisher returns `None` and never
raises, so a Canvas problem can never break a Connect / Resolve / Dismiss button
(the degraded-state guardrail), exactly as before.
