# 032 — Align the backfill sweep's skip guard with task 031

Task 031 fixed the LIVE passive-listener path to skip only the agent's own messages
(`user == bot_user_id`) instead of any `bot_id`, so operator/integration-posted offers
(which carry a `bot_id`) get indexed. But the `BACKFILL_ON_START` startup sweep
(`listeners/backfill.py`, task 026) STILL uses the old blanket skip:
`if msg.get("bot_id"): continue` (~line 122). Seeded offers carry a `bot_id`, so the
backfill drops the very offers it exists to recover — the live path and the startup
sweep now disagree. Align them.

## Design decisions (locked)
- **Mirror 031 exactly.** In `backfill_offer_index`, skip a history message only when it
  is the agent's OWN post (`bot_user_id and msg.get("user") == bot_user_id`); fall back
  to the old `bot_id` skip when `bot_user_id` is unknown (defensive, identical to 031).
  Keep skipping subtypes / no-text / no-user.
- **Resolve `bot_user_id` best-effort.** `backfill_offer_index` takes a `bot_user_id:
  str | None` param. `maybe_backfill_on_start` resolves it best-effort (e.g.
  `client.auth_test()["user_id"]` on the bot token, wrapped — a failure → `None` → the
  defensive `bot_id` fallback). Never let resolving it raise out of the backfill.
- **Still best-effort + idempotent** (unchanged from 026): a fetch/parse failure is
  swallowed; `offer_index.add` dedups by deterministic id, so an offer the live path
  also indexes is not duplicated.
- **No self-loop concern here** (one-shot sweep, no acks posted), but skipping the
  agent's own past acks/replies still matters so they aren't parsed as offers/needs.
- **Scope = `listeners/backfill.py` + its test** (and the one `maybe_backfill_on_start`
  call site if the signature gains `bot_user_id`). Do NOT touch the live handler (031),
  recall, parsing, board, or prompt.

## Acceptance criteria
1. [x] `backfill_offer_index` indexes an operator/integration-posted offer from history
   (real `user`, with a `bot_id`); the old blanket `bot_id` skip is gone. — unit test
   with the seeded payload shape.
2. [x] The agent's OWN past posts (`user == bot_user_id`) are skipped (not parsed as
   offers/needs). — unit test.
3. [x] `bot_user_id is None` → defensive fallback to the `bot_id` skip. — unit test.
4. [x] Subtypes / no-text / no-user still skipped; idempotent + best-effort unchanged
   (fetch failure → 0, never raises). — tests (regression).
5. [x] `maybe_backfill_on_start` resolves `bot_user_id` best-effort and passes it in;
   resolving it never raises out of the sweep. — test.
6. [x] Scope: only `listeners/backfill.py` (+ its test) changed. Guardrails unaffected.
7. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
8. [ ] [HUMAN] Live: with `BACKFILL_ON_START=true`, seeds present, restart the agent →
   the board fills from the startup sweep (not just the live path).

## BDD
- Given history with a seeded offer (`user=OPERATOR, bot_id=B_APP, text="Offering: …"`),
  When the sweep runs, Then that offer is indexed.
- Given history containing the agent's own ack (`user=bot_user_id`), When the sweep
  runs, Then it is skipped (not indexed/parsed).
- Given `bot_user_id` resolution fails, When the sweep runs, Then it falls back to the
  `bot_id` skip and still never raises.

## Out of scope
The live handler (031, done); recall/parsing/board/prompt; the dev one-off populate.

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `listeners/backfill.py` — added `bot_user_id: str | None = None` param to
  `backfill_offer_index`; replaced the blanket `if msg.get("bot_id"): continue` with
  the 031-mirrored guard (skip subtype always; then skip `user == bot_user_id`, else
  fall back to `bot_id` skip when `bot_user_id` is falsy). Added `_resolve_bot_user_id`
  (best-effort `client.auth_test()["user_id"]`, → `None` on any failure) and wired it
  into `maybe_backfill_on_start`'s daemon-thread runner, forwarding it to the sweep.
- `tests/unit/listeners/test_backfill.py` — 7 new tests for the aligned guard +
  resolution; updated `test_runner_indexes_then_publishes_board` to assert the new
  `bot_user_id=` kwarg is forwarded.

**Tests**
- Unit: 512 passing, 0 failing (`make unit-tests`); 28 in `test_backfill.py`.
- Integration: 5 passing, 1 skipped (live LLM, no key) — no infra changed.
- Zero warnings (`filterwarnings=error`). Double-run idempotence test green.

**Acceptance criteria**
- [x] AC1 — `test_seeded_offer_with_bot_id_is_indexed` (+ `test_bot_user_id_none_still_indexes_a_plain_user_offer`, `test_other_bot_offer_is_indexed_when_bot_user_id_known`)
- [x] AC2 — `test_agents_own_post_is_skipped_by_user_identity`
- [x] AC3 — `test_bot_user_id_none_falls_back_to_bot_id_skip`
- [x] AC4 — `test_only_offers_are_indexed`, `test_history_fetch_failure_returns_zero_and_never_raises`, `test_per_message_parse_failure_skips_only_that_message`, `test_double_run_yields_stable_index_size` (regression, unchanged)
- [x] AC5 — `test_resolves_bot_user_id_and_passes_it_to_sweep`, `test_auth_test_failure_does_not_break_the_sweep`
- [x] AC6 — only `listeners/backfill.py` + its test touched (see git status)
- [x] AC7 — `make pre-commit` + unit + integration green, zero warnings
- [ ] [HUMAN] AC8 — needs live verification (`BACKFILL_ON_START=true`, seeds present, restart → board fills from startup sweep)

**Guardrail note**
No safety/sourcing/confirmation/degraded-state behavior changed. The sweep stays
best-effort (history-fetch failure → 0, never raises) and idempotent
(`offer_index.add` dedups by deterministic id); `_resolve_bot_user_id` is wrapped so
an `auth.test` failure degrades to `None` (defensive `bot_id` fallback) and never
raises out of the daemon thread. The `BACKFILL_ON_START` / `CRISIS_CHANNEL` gating is
unchanged — only the skip guard + `bot_user_id` plumbing.

**Evidence**
```
$ make unit-tests
============================= 512 passed in 1.85s ==============================

$ make integration-tests
========================= 5 passed, 1 skipped in 1.03s =========================

$ make format-check && make lint-check
97 files already formatted
All checks passed!

# end-to-end (real guard logic, parse_message stubbed at the LLM boundary):
bot_user_id=known -> indexed: 1   offerers in index: ['U_OPERATOR']  (agent ack skipped)
bot_user_id=None  -> indexed: 0   (bot_id fallback drops bot-posted msgs)
resolve bot_user_id on auth failure -> None ; ok -> U_AGENT
```

**Notes**
- The previously-existing `test_only_offers_are_indexed` still passes unchanged: its
  `bot_msg` carries a `bot_id` but no `user`, so it's now skipped by the no-user guard
  (the call uses the default `bot_user_id=None`, so the `bot_id` fallback also applies).
- Uncommitted — handing to Tester for review per `/day` flow.

### [Tester] 2026-06-13 23:10 — QA (re-run of committed `fac6ad5`)

Clean re-run for a formal verdict; a prior Tester pass stalled on an infra watchdog
after reporting green. Reviewed the committed code as it stands (HEAD = `fac6ad5`,
working tree clean).

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` → 97 files already formatted;
  `ruff check` → All checks passed)
- Unit tests: 512 passed / 0 failed (`make pre-commit` and a second `make unit-tests`
  run — double-run stable at 512/512)
- Integration tests: 5 passed / 1 skipped (live LLM, no provider key — expected)
- `test_backfill.py`: 28 passed
- Warnings: 0 (`filterwarnings=["error"]` in effect — a warning would have failed the run)

**E2E adversarial pass** (real guard + real `OfferIndex`; only `parse_message` and the
`WebClient` stubbed at the I/O boundary)
- Happy path — mixed history (seeded operator offer w/ `bot_id`, agent's own ack
  `user==bot_user_id`, human need, subtype edit, no-user msg), `bot_user_id=U_AGENT` →
  `count=1`, indexed offerers `['U_OPERATOR']`, agent ack never parsed. PASS
- Break path 1 (state: `bot_user_id=None`, same mixed history) → `bot_id` fallback drops
  BOTH bot-posted msgs (seeded offer + ack); need not indexed → `count=0`, index empty.
  PASS
- Break path 2 (failure mode: `auth_test` raises inside `maybe_backfill_on_start`) →
  sweep still runs with `bot_user_id=None`, board still published, no raise; degraded
  log "could not resolve bot_user_id via auth.test" emitted. PASS
- Break path 3 (failure mode: `conversations.history` raises inside the daemon runner) →
  sweep returns 0, no raise, board still published; degraded log emitted. PASS
- Break path 4 (malformed input: non-dict history entries `"not a dict", None, 42`) →
  silently skipped, the one real offer still indexed → `count=1`. PASS
- Break path 5 (state edge: agent's OWN offer-shaped post `user==bot_user_id`,
  text "Offering: gen") → skipped BEFORE parse (`parse_message` not called), `count=0`
  — no self-index. PASS
- Break path 6 (boundary: `auth_test` returns a dict with no `user_id` key) →
  `_resolve_bot_user_id` returns `None` (fallback), no raise. PASS

**Acceptance criteria**
- [x] PASS — AC1: seeded/operator offer (real `user` + `bot_id`) IS indexed; blanket
      `bot_id` skip gone. Evidence: `test_seeded_offer_with_bot_id_is_indexed` +
      `test_other_bot_offer_is_indexed_when_bot_user_id_known`; adversarial happy path
      indexed `U_OPERATOR`. Guard at `listeners/backfill.py:153-157`.
- [x] PASS — AC2: agent's OWN past posts (`user == bot_user_id`) skipped, not parsed.
      Evidence: `test_agents_own_post_is_skipped_by_user_identity` (parse_spy not called);
      adversarial break path 5 (`parse_message` not called). `backfill.py:153-155`.
- [x] PASS — AC3: `bot_user_id is None` → defensive `bot_id` fallback.
      Evidence: `test_bot_user_id_none_falls_back_to_bot_id_skip` +
      `test_bot_user_id_none_still_indexes_a_plain_user_offer`; adversarial break path 1
      (count=0 under `None`). `backfill.py:156-157` (`elif message.get("bot_id")`).
- [x] PASS — AC4 (regression): subtype/no-text/no-user still skipped; history-fetch
      failure → 0 never raises; idempotent double-run stable. Evidence:
      `test_only_offers_are_indexed`, `test_history_fetch_failure_returns_zero_and_never_raises`,
      `test_per_message_parse_failure_skips_only_that_message`,
      `test_double_run_yields_stable_index_size`; adversarial break paths 3 & 4.
      `backfill.py:147-148, 158-167`; idempotence via `offer_index.add` deterministic id.
- [x] PASS — AC5: `maybe_backfill_on_start` resolves `bot_user_id` via `auth.test` and
      forwards it; an `auth.test` raise degrades to `None` (does NOT break the sweep).
      Evidence: `test_resolves_bot_user_id_and_passes_it_to_sweep`,
      `test_auth_test_failure_does_not_break_the_sweep`; adversarial break paths 2 & 6.
      `backfill.py:79-91` (`_resolve_bot_user_id`), `217-220` (`_run`).
- [x] PASS — AC6: committed diff (`fac6ad5`) touches ONLY `listeners/backfill.py` +
      `tests/unit/listeners/test_backfill.py` (+ this tracker doc — process bookkeeping,
      not product code). Evidence: `git show fac6ad5 --name-only`.
- [x] PASS — AC7: `make pre-commit` + unit + integration green, zero warnings,
      double-run stable (512/512 across two runs).
- [ ] [HUMAN] AC8 — Awaiting human verification: live restart with
      `BACKFILL_ON_START=true` + seeds present → board fills from the startup sweep.

**Guard mirrors 031 EXACTLY** — verified by side-by-side comparison of
`listeners/events/message.py:62-74` and `listeners/backfill.py:146-157`: identical skip
order (subtype → `user == bot_user_id` → `bot_id` fallback), identical branch structure
(`if bot_user_id: / elif msg.get("bot_id")`). Only difference is `return` (handler) vs
`continue` (loop), appropriate to each context. Live path and startup sweep now agree.

**Guardrail / robustness recheck**
- Best-effort + idempotent intact: history-fetch failure → 0 (never raises);
  `offer_index.add` dedups by `deterministic_id(author, source_ts)` (double-run stable).
- `bot_user_id` resolution never raises out of the daemon thread: `_resolve_bot_user_id`
  wraps `auth.test` in try/except → `None` on any failure or missing `user_id`
  (adversarial break paths 2 & 6 confirm).
- Gating unchanged: `BACKFILL_ON_START` (`_backfill_enabled`) + `CRISIS_CHANNEL`
  (`designated_channel_id`) gate checks untouched by the diff; gate tests
  (`test_gate_no_op_when_flag_disabled`, `test_gate_no_op_when_channel_unset`,
  `test_gate_open_spawns_a_daemon_thread`) green.
- No safety/sourcing/confirmation/degraded-state behaviour changed — only the skip
  guard + `bot_user_id` plumbing.

**Evidence**
```
$ make pre-commit
============================= 512 passed in 1.70s ==============================
$ make unit-tests        # second run — double-run stable
============================= 512 passed in 1.65s ==============================
$ make integration-tests
========================= 5 passed, 1 skipped in 0.90s =========================
$ uv run pytest tests/unit/listeners/test_backfill.py -q
28 passed in 0.90s
$ make format-check && make lint-check
97 files already formatted
All checks passed!
```

**Other issues found**
- None. Scope is tight, the guard is a faithful mirror of 031, and the daemon-thread
  failure modes are all swallowed as designed.

**VERDICT: PASS**
