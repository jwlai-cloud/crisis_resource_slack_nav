# 026 — Backfill the offer index from channel history on startup

The coordinator board's "Open/Connected/Resolved" sections render the **in-memory**
`offer_index` (matching/index.py), which is populated ONLY by offers the live agent
parses as they arrive and is **wiped on every restart** (ADR-0003). Seeded offers
(`make seed-demo`) and any offer posted while the agent was down therefore never
appear on the board — they live only in Slack's RTS index, which feeds *recall* (the
need reply), not the board. Verified live 2026-06-13: RTS returns the seeded offers,
but the canvas shows `Open(0)` because the agent restarted after seeding.

Backfill the in-memory index from the channel's message **history** at startup so
prior/seeded offers show as "Open" cases and survive restarts.

**Secondary benefit (latent bug fix):** today, after a restart the first
Connect/Resolve republishes the board from an EMPTY index, overwriting the durable
canvas (which still held the last good board) with an empty one. A populated index
removes that wipe.

## Design decisions (locked — do not re-litigate)

- **Source = `conversations.history`, NOT RTS.** The user asked for "backfill from
  RTS", but RTS (`assistant.search.context`) is keyword-search — it cannot list a
  channel's messages, only those matching a query, and lags ~60s. `conversations.history`
  is a complete, immediate, deterministic dump and the bot token already has
  `channels:history`. RTS stays the *recall* path; history is the *backfill* path.
  This is a refinement of the request, not a scope change — flag it in the SWE log.
- **Runs in the AGENT process only** (app.py / a listener-side module), never the
  standalone `make board` script. The board must be published by a process whose
  index holds the offers, so button Connects transition real offers. A standalone
  backfill would populate a throwaway index and the agent's index would stay empty
  (re-introducing the wipe). Startup is the single correct place.
- **Opt-in via a new env flag `BACKFILL_ON_START`** (default OFF). The file-watcher
  restarts the agent on every `.py` save during dev; an always-on backfill would fire
  an LLM parse per history message on every save (a parse storm). Default off; the
  demo operator sets it `true`. Gated additionally on `CRISIS_CHANNEL` being set
  (no channel → nothing to back-fill). Same env-at-call-time, one-flag posture as
  CRISIS_CHANNEL (ADR-0004) — widening is a future fork.
- **Best-effort, never raises.** A history fetch failure, or a parse failure on any
  single message, is logged and skipped — backfill is a convenience and must never
  break agent startup or the socket connection.
- **Idempotent.** `offer_index.add` overwrites by `offer.id` =
  `deterministic_id(author, source_ts)`, so re-parsing a message the agent later
  also sees live produces the SAME id — no duplicate row. Re-running backfill is safe.
- **Offers only.** The board renders Offers (status sections); Needs and chatter are
  parsed and ignored. `parse_message` already returns `Need | Offer | NotACrisisMessage`.
- **Non-blocking.** Run the sweep in a background daemon thread so it never delays the
  socket-mode connection. After the sweep, publish the board once so the canvas
  reflects the backfilled cases.

## Implementation sketch (SWE owns the details)

- New module `listeners/backfill.py` (or `matching/backfill.py` — SWE's call, but it
  imports parse_message + offer_index + the channel gate, so listeners/ fits):
  - `backfill_offer_index(client, *, channel_id, user_token, limit=100) -> int`
    - `conversations_history(channel=channel_id, limit=limit)` (bot token; user_token
      override only if needed — bot has channels:history). Read defensively.
    - For each message: skip if `bot_id`/`subtype`/no `text`/no `user` (mirror the
      `handle_message` guards so the agent's own acks + the announce posts are not
      parsed). Skip the agent's own user id if known.
    - `parse_message(text, author=user, ts=_event_ts_to_utc(ts))` (reuse the existing
      helper from recall_reply for the ts conversion, or a local one). Wrap each parse
      in try/except → skip on failure.
    - If the result is an `Offer`: `offer_index.add(offer)`.
    - Return the count added. Log a one-line summary (scanned N, indexed M).
  - `maybe_backfill_on_start(client, ...)` — the gate: returns early (logged) unless
    `BACKFILL_ON_START` is truthy AND `designated_channel_id()` is set. Spawns the
    daemon thread that runs `backfill_offer_index` then `update_board(...)`.
- Wire into `app.py` after `register_listeners(app)`: call `maybe_backfill_on_start`
  with the app's WebClient + `resolve_user_token(None)` + team id (auth.test or
  leave None — board publish tolerates None team). Must not block `SocketModeHandler.start()`.
- `.env.example`: add `BACKFILL_ON_START=false` with a one-line comment.
- ADR-0006 (new): "Backfill the offer index from channel history on startup."
  Nygard four sections. Context = in-memory index (ADR-0003) is restart-wiped +
  live-only, so seeds never reach the board; the post-restart wipe bug. Decision =
  opt-in startup sweep of conversations.history → parse → index, in-process,
  background, idempotent, best-effort; history NOT RTS and why. Consequences = board
  reflects prior offers + survives restart; cost is N LLM parses at boot (gated off
  by default); RTS remains the recall path; not a durability store (still in-memory,
  re-derived each boot).
- CLAUDE.md: add `BACKFILL_ON_START` to the env var list near CRISIS_CHANNEL.

## Acceptance criteria

1. [x] A new backfill module fetches `conversations.history` for `CRISIS_CHANNEL`,
   parses each eligible message, and adds every parsed **Offer** to `offer_index`
   (Needs/chatter ignored). Bot messages, subtypes, and message-less events are
   skipped (mirrors `handle_message` guards). — unit test with a mocked client +
   mocked `parse_message`.
2. [x] Per-message parse failures and a history-fetch failure are caught and logged;
   backfill returns a count and never raises (best-effort). — unit test: a parse that
   raises skips only that message; `conversations_history` raising → returns 0.
3. [x] Idempotent: backfilling the same history twice yields the same indexed set (no
   duplicate rows) — relies on `deterministic_id`; assert index size stable across two
   runs with a real `OfferIndex` and mocked parse.
4. [x] Gated: `maybe_backfill_on_start` is a no-op (logged, no thread, no history call)
   when `BACKFILL_ON_START` is unset/false OR `CRISIS_CHANNEL` is unset. Runs (spawns
   the sweep) only when both are set. — unit test both gates.
5. [x] Wired into `app.py` after `register_listeners`, non-blocking (daemon thread),
   and publishes the board once after the sweep. — code-evident + a test that
   `maybe_backfill_on_start` invokes the runner and then `update_board` (mock the thread
   to run synchronously, or test the inner runner directly).
6. [x] `.env.example` lists `BACKFILL_ON_START`; CLAUDE.md env section documents it.
7. [x] ADR-0006 added (four sections), explaining history-not-RTS, opt-in, best-effort,
   idempotent, and that it preserves the ADR-0003 in-memory posture.
8. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
9. [ ] [HUMAN] Live: set `BACKFILL_ON_START=true`, ensure seeds present
   (`make seed-demo`), restart the agent → the canvas board shows the seeded offers
   under "Open"; a Connect then moves one to "Connected" + writes the activity log.

## BDD scenarios

- Given a channel history of 6 offers + 2 needs + 3 chatter + the bot's own acks,
  When `backfill_offer_index` runs, Then exactly 6 offers are in the index and the
  return count is 6 (needs/chatter/bot skipped).
- Given `BACKFILL_ON_START=false`, When `maybe_backfill_on_start` is called, Then no
  history fetch happens and it logs the skip.
- Given `BACKFILL_ON_START=true` but `CRISIS_CHANNEL` unset, When called, Then no-op.
- Given a message whose parse raises, When backfill runs over a batch, Then that one
  message is skipped and the rest still index.
- Given the same history swept twice, When both runs complete, Then the index holds
  one row per distinct (author, ts) — no duplicates.

## Out of scope (do NOT do here)
- Disk persistence of the index (separate enhancement).
- Channel-canvas tab polish: the "Untitled" tab label, the orphan "Deleted file" tab,
  announce spam, and the `properties.canvas` vs `properties.tabs` discovery bug — all
  go to task 027. Do not touch coordinator/canvas.py discovery here.
- Backfilling Needs or rendering them on the board.

## Log

### [SWE] 2026-06-13 14:05 — Implementation

**Files modified**
- `listeners/backfill.py` (new) — `backfill_offer_index` (history sweep → parse →
  index Offers; best-effort) + `maybe_backfill_on_start` (two-gate daemon-thread
  spawner that runs the sweep then `update_board`).
- `app.py` — wired `maybe_backfill_on_start(app.client, user_token=resolve_user_token(None))`
  after `register_listeners(app)` and before `SocketModeHandler.start()` (non-blocking).
- `.env.example` — added `BACKFILL_ON_START=false` with a one-line comment, placed
  after the `CRISIS_CHANNEL` block.
- `CLAUDE.md` — documented `BACKFILL_ON_START` in the env-var list, right under
  `CRISIS_CHANNEL`.
- `docs/adr/0006-startup-offer-index-backfill.md` (new) — Nygard four-section ADR:
  history-not-RTS, opt-in, best-effort, idempotent, preserves the ADR-0003 in-memory
  posture + notes the secondary post-restart-wipe fix.
- `tests/unit/listeners/test_backfill.py` (new) — 21 unit tests (mocked WebClient +
  mocked `parse_message`; one real `OfferIndex` for idempotence).

**Refinement flagged (per the design doc's locked decision)**: source is
`conversations.history`, NOT RTS. RTS (`assistant.search.context`) is keyword search
and cannot enumerate a channel's messages; the bot token already holds
`channels:history`. RTS stays the *recall* path; history is the *backfill* path. No
scope change — implemented exactly as the groomed spec directs.

**Tests**
- Unit: 432 passing, 0 failing (21 new in `test_backfill.py`) — `make pre-commit` output below.
- Integration: 5 passing, 1 skipped (live-provider parse test; no AI key — no infra
  change in this task).

**Acceptance criteria**
- [x] AC1 — `tests/unit/listeners/test_backfill.py::test_only_offers_are_indexed`
  (6 offers + 2 needs + 3 chatter + bot/subtype/no-text/no-user → exactly 6 indexed),
  `::test_history_is_fetched_for_the_given_channel`.
- [x] AC2 — `::test_per_message_parse_failure_skips_only_that_message`,
  `::test_history_fetch_failure_returns_zero_and_never_raises`,
  `::test_missing_messages_key_returns_zero`.
- [x] AC3 — `::test_double_run_yields_stable_index_size` (real `OfferIndex`, two sweeps → size 3).
- [x] AC4 — `::test_gate_no_op_when_flag_disabled`, `::test_gate_no_op_when_channel_unset`,
  `::test_gate_open_spawns_a_daemon_thread`, plus the env read
  `::test_backfill_enabled_reads_env` / `::test_backfill_disabled_when_env_unset`.
- [x] AC5 — `::test_runner_indexes_then_publishes_board` (Thread patched to run the
  target synchronously: sweep then `update_board`, in order) + code-evident wiring in
  `app.py` (line 33, after `register_listeners`, before `SocketModeHandler.start()`).
- [x] AC6 — `.env.example` + `CLAUDE.md` env section both list `BACKFILL_ON_START`.
- [x] AC7 — `docs/adr/0006-startup-offer-index-backfill.md` added (four sections).
- [x] AC8 — `make pre-commit` (432 unit, 0 warn), `make integration-tests` (5 pass,
  1 skip), double-run stable (AC3).
- [ ] AC9 — [HUMAN] live verification (set `BACKFILL_ON_START=true`, seed, restart,
  confirm canvas "Open" + a Connect transition). Needs a live `slack run` + sandbox.

**Evidence**

End-to-end runtime exercise of `maybe_backfill_on_start` (flag on, real `OfferIndex`,
fake WebClient with real Slack-shaped history, `parse_message` stubbed only at the LLM
boundary, `update_board` stubbed to observe the post-sweep publish):
```
indexed offers: 1
board published with offers: 1
board user_token: xoxp-demo
history called once: True
OK
```
Both no-op gate paths at runtime (flag off; flag on + channel unset):
```
flag-off: history called: False
channel-unset: history called: False
```
`make pre-commit` (tail):
```
tests/unit/listeners/test_backfill.py .....................              [ 46%]
...
============================= 432 passed in 2.31s ==============================
```
`make integration-tests` (tail):
```
SKIPPED [1] tests/integration/agent/test_parsing_live.py:30: no live provider key configured
========================= 5 passed, 1 skipped in 1.28s =========================
```

**Notes**
- Daemon thread + best-effort: `backfill_offer_index` swallows a history-fetch
  failure (returns 0) and per-message parse failures (skips one); the thread is a
  `daemon` so it never blocks `SocketModeHandler.start()` nor interpreter shutdown.
- Idempotence rides on the existing `deterministic_id(author, source_ts)` →
  `offer_index.add` overwrite, so backfilling a message the agent later sees live
  produces no duplicate row (verified with a real `OfferIndex`).
- `_event_ts_to_utc` is replicated locally (1 line) rather than imported from
  `recall_reply` to avoid coupling the backfill module to the recall wiring; it is
  byte-identical and produces the aware-UTC datetime `parse_message`/`Offer` require.
- AC9 (live) left unchecked — requires a live `slack run` against the sandbox.

### [Tester] 2026-06-13 16:20 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` → 94 files formatted; `ruff check` → all checks passed; pre-commit unit run 432 passed)
- Unit tests: 432 passed / 0 failed (double-run stable: 1.65s then 1.44s)
- Integration tests: 5 passed / 1 skipped / 0 failed (skip = `test_parsing_live.py` no live provider key — environmental, not code) (double-run stable)
- Warnings: 0 (`filterwarnings = ["error"]` in pyproject.toml:75 — any warning would have failed the run; suite is green)
- `test_backfill.py`: 21 passed

**E2E adversarial pass** (drove the REAL `backfill_offer_index` + `maybe_backfill_on_start`
against a fake WebClient with Slack-shaped history; `parse_message` stubbed only at the
LLM boundary; real `OfferIndex`)
- Happy path (AC1): mixed history [1 offer + 1 bad-parse + 1 chatter + 1 bot + 1 subtype +
  1 missing-user + 1 need] → `backfill_offer_index` returned 1, index size 1, the indexed
  row is the offerer `U_OFF1`, `conversations_history` called once. Needs/chatter/bot/
  subtype/empty-user/bad-parse all skipped. (PASS)
- Break path 1 (failure mode: history fetch raises): `conversations_history` raises
  RuntimeError → returns 0, never raises, index untouched. (PASS)
- Break path 2 (state edge: idempotent double-run): same history swept twice → count 1 /
  size 1 both times, no duplicate row (deterministic_id overwrite). (PASS)
- Break path 3 (malformed: missing `messages` key): `{}` response → returns 0, no crash.
  `messages: None` → returns 0 (the `response.get("messages") or []` guard). (PASS)
- Break path 4 (malformed: non-dict elements in messages list): `["str", None, 42, {...}]`
  → junk skipped via `isinstance(message, dict)` guard at backfill.py:118, no crash. (PASS)
- Break path 5 (gate: BACKFILL_ON_START unset) → no-op, logs "disabled", zero history
  calls. (PASS) — also exercised via tripwire client that asserts if history is touched.
- Break path 6 (gate: flag on but CRISIS_CHANNEL unset) → no-op, zero history calls. (PASS)
- Break path 7 (gate: both set) → real daemon thread spawned, sweep ran (history calls=1),
  index populated, `update_board("xoxp-demo","T1")` called AFTER the sweep, main thread
  non-blocking (returned immediately). (PASS)
- Break path 8 (failure isolation: board-publish raises inside the daemon) → injected a
  RAISING board substitute (worst case); the daemon thread isolated it and the main
  process survived (offer still indexed first). In the real wiring `update_board`
  (coordinator/canvas.py:415 → `publish` at :206) wraps its whole body in
  `try/except → log + return None` and genuinely never raises — so the path is doubly
  safe. (PASS)

**Acceptance criteria**
- [x] PASS — AC1: history fetched for given channel, only parsed Offers indexed, guards
      mirror handle_message — backfill.py:122 (`bot_id`/`subtype`), :127 (no text/user/ts),
      :134 (`isinstance(parsed, Offer)`); guards match `listeners/events/message.py:45-47`.
      Evidence: `::test_only_offers_are_indexed`, `::test_history_is_fetched_for_the_given_channel`
      + adversarial happy path (6→6 in test; 1→1 in live drive).
- [x] PASS — AC2: per-message parse failure skips one (backfill.py:129-133), history-fetch
      failure → returns 0 never raises (backfill.py:109-113), missing `messages` → 0
      (backfill.py:115). Evidence: `::test_per_message_parse_failure_skips_only_that_message`,
      `::test_history_fetch_failure_returns_zero_and_never_raises`,
      `::test_missing_messages_key_returns_zero` + adversarial break paths 1, 3.
- [x] PASS — AC3: idempotent via deterministic_id overwrite (`offer_index.add`,
      matching/index.py:53-62). Evidence: `::test_double_run_yields_stable_index_size`
      (real OfferIndex, size stable at 3) + adversarial break path 2 (real OfferIndex).
- [x] PASS — AC4: both gates no-op (backfill.py:171-177); env read truthy/falsy spellings
      (backfill.py:74-76). Evidence: `::test_gate_no_op_when_flag_disabled`,
      `::test_gate_no_op_when_channel_unset`, `::test_gate_open_spawns_a_daemon_thread`,
      parametrized `::test_backfill_enabled_reads_env` + adversarial break paths 5, 6, 7.
- [x] PASS — AC5: wired in app.py:33 after `register_listeners` (line 27), before
      `SocketModeHandler.start()` (line 36); daemon thread (backfill.py:184,
      `daemon=True`); runner does sweep then `update_board` in order (backfill.py:179-181).
      Evidence: `::test_runner_indexes_then_publishes_board` (`calls == ["sweep","board"]`)
      + adversarial break path 7 (real daemon, non-blocking, board after sweep).
- [x] PASS — AC6: `.env.example` lists `BACKFILL_ON_START=false` with comment (diff present);
      CLAUDE.md env section documents it under CRISIS_CHANNEL (diff present).
- [x] PASS — AC7: `docs/adr/0006-startup-offer-index-backfill.md` present, four Nygard
      sections (Status/Context/Decision/Consequences), covers history-not-RTS (lines 33-44),
      opt-in (69-74), best-effort (75-78), idempotent (79-81), preserves ADR-0003 in-memory
      posture (92-98), and the secondary post-restart-wipe fix (22-26, 87-91).
- [x] PASS — AC8: `make pre-commit` + unit (432) + integration (5 pass/1 skip) green,
      0 warnings, double-run stable.
- [ ] [HUMAN] — AC9: live verification (BACKFILL_ON_START=true, seed, restart, canvas
      "Open" + Connect transition). Awaiting human verification — requires live `slack run`.

**Guardrail re-check** (CLAUDE.md mandates explicit re-check when touching board/index)
- Human-decides: backfill only populates the read-only board ("Open" cases); a Connect
  is still a human button click. No auto-action. (PASS)
- Never assert safety: backfill indexes typed Offers, composes no message/safety language.
  (PASS)
- Sourcing/timestamps: every indexed Offer carries `offerer` + `source_ts` (validator
  rejects naive datetimes; `_event_ts_to_utc` yields aware-UTC). (PASS)
- Degraded states explicit: history failure → logged warning + returns 0, never silent.
  (PASS)

**Known-gap check**: confirmed backfill does NOT worsen the separate
"safety/info questions parse as NotACrisisMessage" gap — `NotACrisisMessage` is not an
`Offer`, so the `isinstance(parsed, Offer)` gate (backfill.py:134) skips it; Needs and
chatter are never indexed.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
94 files already formatted
uv run ruff check
All checks passed!
...
============================= 432 passed in 3.79s ==============================

$ make integration-tests
SKIPPED [1] tests/integration/agent/test_parsing_live.py:30: no live provider key configured
========================= 5 passed, 1 skipped in 0.80s =========================
```
Adversarial live drive (real backfill, fake client, parse stubbed at LLM boundary):
```
indexed count returned: 1  (expect 1) ; index size: 1 ; history calls: 1
history fetch raises -> returned 0, no exception: PASS ; index untouched: True
idempotent: run1 count=1 size=1; run2 count=1 size=1 ; stable: True
missing 'messages' -> 0 ; messages=None -> 0 ; junk elements -> 0 (no crash)
gate flag-off -> history calls: 0 ; gate channel-unset -> history calls: 0
gate both-set -> sweep ran (1), index 1, board published ('xoxp-demo','T1') after sweep
raising board inside daemon -> main thread survived (offer indexed first)
```

**Other issues found**
- None blocking. Notes (non-blocking, orchestrator's call): (a) `user_token` is accepted by
  `backfill_offer_index` for signature stability but unused by the fetch (bot token carries
  `channels:history`) — documented in the docstring, intentional. (b) `_event_ts_to_utc` is
  a 1-line replication of `recall_reply`'s helper; verified byte-identical — a deliberate
  decoupling choice, documented in the SWE log; acceptable.

**VERDICT: PASS** (AC1–AC8 verified with code + test + adversarial evidence; AC9 [HUMAN]
awaiting live sandbox verification)
