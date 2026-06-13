# 0006. Backfill the offer index from channel history on startup

**Status:** Accepted
**Date:** 2026-06-13

## Context

The coordinator board (ADR-0005) renders its "Open / Connected / Resolved" sections
from the **in-memory** `offer_index` (`matching/index.py`). That index is a
process-local `dict` that is populated *only* by offers the live agent parses as they
arrive, and it is **wiped on every restart** (ADR-0003 — no persistence by design).

Two consequences fall out of that posture, and both surface on the board:

- **Seeded / prior offers never reach the board.** `make seed-demo` posts believable
  offers into `CRISIS_CHANNEL`, and offers may be posted while the agent is down.
  Those messages exist in the workspace (and so are found by RTS *recall*, which
  feeds the need reply), but they were never parsed by a running agent, so they are
  absent from the index and therefore from the board. Verified live 2026-06-13: RTS
  returns the seeded offers, but the canvas shows `Open(0)` because the agent
  restarted after seeding.
- **A latent post-restart wipe.** After a restart the index is empty. The board's
  durable canvas (ADR-0005) still holds the last good board until something
  republishes it; the *first* Connect / Resolve after the restart republishes from
  the empty index and overwrites that good canvas with an empty one. So a single
  click silently erases the visible board.

ADR-0003 explicitly **deferred** index rehydration on restart, calling an
empty-status board after a restart "honest". Task 026 revisits that deferral for the
board's sake: an empty board after a seed is technically honest but demo-breaking,
and the post-restart wipe is an outright bug.

The candidate sources for a startup rehydration were:

- **(A) RTS (`assistant.search.context`).** The user's original request said "backfill
  from RTS". But RTS is *keyword search*: it cannot enumerate a channel's messages,
  only those matching a query, and it lags ~60s behind a post. There is no query that
  reliably means "every offer in this channel", so RTS cannot drive a complete
  backfill.
- **(B) `conversations.history`.** A complete, immediate, deterministic dump of a
  channel's recent messages. The bot token already holds `channels:history` (no new
  scope), and each message's `(text, user, ts)` maps one-to-one onto
  `parse_message`'s inputs.

## Decision

Add an **opt-in startup sweep of `conversations.history`** (option B), in the agent
process, that parses each eligible message and adds every parsed `Offer` to the
existing in-memory `offer_index`, then publishes the board once.

`listeners/backfill.py` owns it:

- `backfill_offer_index(client, *, channel_id, user_token, limit=100) -> int` —
  fetches one page of `conversations.history`, skips bot posts / message subtypes /
  message-less events (mirroring `handle_message`'s guards so the agent's own acks and
  system join posts are not re-parsed), parses the rest with `parse_message`, adds
  every `Offer` to `offer_index`, and returns the count.
- `maybe_backfill_on_start(client, *, user_token, team_id=None)` — the gate: a no-op
  (logged) unless `BACKFILL_ON_START` is truthy AND `CRISIS_CHANNEL` is set; otherwise
  it spawns a background **daemon** thread that runs the sweep and then
  `coordinator.update_board`. Wired into `app.py` after `register_listeners`, before
  `SocketModeHandler.start()`.

Four properties make this safe to bolt onto startup:

- **History, not RTS** — for the completeness/immediacy/determinism reasons above. RTS
  stays the *recall* path (the need reply); history is the *backfill* path. They do
  not compete.
- **Opt-in via `BACKFILL_ON_START`** (default off). The dev file-watcher restarts the
  agent on every `.py` save; an always-on backfill would fire an LLM parse per history
  message on every save (a parse storm). Default off; the demo operator sets it `true`
  and restarts. Additionally gated on `CRISIS_CHANNEL` (no channel -> nothing to
  back-fill). Same env-at-call-time, one-flag posture as `CRISIS_CHANNEL` (ADR-0004);
  widening is a future fork.
- **Best-effort, never raises.** A history-fetch failure returns `0`; a parse failure
  on any single message is logged and skips only that message. Backfill is a
  convenience and must never break agent startup or the socket connection (the
  degraded-state guardrail).
- **Idempotent.** `offer_index.add` overwrites by `offer.id =
  deterministic_id(author, source_ts)`, so re-parsing a message the live agent later
  also sees produces the SAME id — no duplicate row. Re-running the sweep is a no-op.

The sweep runs in a daemon thread so it never delays the socket-mode connection.

## Consequences

- **The board reflects prior/seeded offers, and survives a restart.** After a restart
  with the flag on, the index is rehydrated from history and the board shows the
  seeded offers under "Open". Because the index is no longer empty at the first
  Connect/Resolve, that click republishes a populated board rather than wiping the
  durable canvas — the latent post-restart wipe is fixed as a side effect.
- **This does NOT change the in-memory posture of ADR-0003.** The index stays a
  process-local `dict` with no persistence and no second source of truth. The board's
  durable store remains the Canvas (ADR-0005); the workspace (via RTS) remains the
  durable record of offers. Backfill is *re-derivation on boot from the workspace*,
  not a durability store: the index is rebuilt each boot, never persisted to disk.
  ADR-0003's "no persistence / single-process" decision is unchanged; this is the
  rehydration ADR-0003 deferred, scoped to the board and gated off by default.
- **Cost is N LLM parses at boot**, where N is one page of channel history (≤100,
  default `limit=100`). Gated off by default precisely so dev restarts pay nothing;
  the demo operator pays it once when arming the demo. One page is the whole demo
  channel; this is not a paginating crawler.
- **Offers only.** Needs and chatter are parsed and ignored — the board renders Offer
  status sections, and Need/chatter rehydration has no board surface. Backfilling
  Needs (or rendering them) is out of scope.
- **No new scope.** The bot token's existing `channels:history` covers the fetch; no
  manifest change.
