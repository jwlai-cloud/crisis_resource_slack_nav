# 006 — Passive listening in the designated mutual-aid channel

DECIDED (user, 2026-06-12): Option B — passive listening in ONE designated channel;
everywhere else stays mention-gated.

## Acceptance criteria

- [x] 1. Config: `CRISIS_CHANNEL` env var (channel id; empty = feature off). .env.example
   documented. Settings read where the listeners can reach it.
- [x] 2. listeners/events/message.py: top-level messages in CRISIS_CHANNEL get the full
   route_message flow — offers indexed + acked (threaded), needs answered in-thread
   with the standard reply. All other channels keep the current "handled by
   app_mentioned" skip. DMs unchanged. Thread replies in the channel unchanged
   (still skipped).
- [x] 3. NotACrisisMessage results in the channel are silently ignored (no reply, no ack)
   — chatter must not trigger bot noise; log at debug only.
- [x] 4. Bot/self messages and message_changed subtypes excluded (existing guards apply).
- [x] 5. ADR-0004: passive-listening posture — one channel only, why (design-doc flow vs
   token cost/noise), the env-config trigger to widen/narrow.
- [x] 6. CLAUDE.md: document CRISIS_CHANNEL in commands/env surface.
- [x] 7. Unit tests: channel-gating table (designated channel top-level → routed; other
   channel → skipped; thread reply → skipped; chatter → silent), mocked parse.
- [ ] 8. [HUMAN] live: create #exmouth-mutual-aid in sandbox, set CRISIS_CHANNEL, post a
   plain offer → indexed + acked; plain need → replied in thread; chatter → silence.

## Log

DECISION 2026-06-12: Option B per user. Demo script's volunteer-posts-plainly flow
becomes real.

### [SWE] 2026-06-12 23:10 — Implementation

**Files modified**
- `listeners/channel_gate.py` (new) — `CRISIS_CHANNEL` gate: `is_crisis_channel()` /
  `designated_channel_id()`, read from env at call time; empty/unset = feature off.
- `listeners/events/message.py` — split into the unconditional DM/engaged-thread
  reply path (`_reply_conversationally`) and the new passive-channel path
  (`_listen_in_designated_channel`); top-level messages route through passive
  listening ONLY when `is_crisis_channel(channel_id)`, all other channels keep the
  app_mentioned skip.
- `docs/adr/0004-passive-listening-single-channel.md` (new) — Nygard ADR for the
  one-channel posture.
- `.env.example` — documented `CRISIS_CHANNEL` (passive-listening section).
- `CLAUDE.md` — one-line `CRISIS_CHANNEL` entry in the env surface.
- `tests/unit/listeners/test_channel_gate.py` (new) — gate truth table.
- `tests/unit/listeners/events/test_message.py` (new) — channel-gating table for the
  handler.

**Tests**
- Unit: 243 passing, 0 failing (`make pre-commit`), zero warnings
  (`filterwarnings = ["error"]`). 20 new tests (5 gate + 15 handler).
- Integration: N/A — no infra touched; the handler is exercised with mocked
  Slack/LLM/recall seams. No integration test references the changed code.

**Acceptance criteria**
- [x] 1 — `CRISIS_CHANNEL` env var read via `listeners/channel_gate.py`; documented
  in `.env.example`. Verified by `tests/unit/listeners/test_channel_gate.py`.
- [x] 2 — passive route in the designated channel (offer → ack via route_message;
  need → one threaded `compose_reply` naming requester); other channels skipped; DMs
  + thread replies unchanged. Verified by
  `tests/unit/listeners/events/test_message.py::test_designated_channel_offer_acked_no_compose`,
  `::test_designated_channel_need_gets_one_reply`,
  `::test_other_channel_top_level_skipped_no_parse`,
  `::test_thread_reply_in_designated_channel_unchanged`,
  `::test_dm_path_unchanged_composes_even_without_recall`.
- [x] 3 — chatter (route_message → None) is silent (no compose, no say; debug log).
  Verified by `::test_designated_channel_chatter_is_silent` and
  `::test_designated_channel_route_failure_stays_silent`.
- [x] 4 — bot/subtype guards apply before the branch. Verified by
  `::test_bot_message_in_designated_channel_ignored`,
  `::test_message_changed_subtype_in_designated_channel_ignored`.
- [x] 5 — `docs/adr/0004-passive-listening-single-channel.md` (Status: Accepted).
- [x] 6 — `CLAUDE.md` env surface updated.
- [x] 7 — gating-table unit tests (above), parse/run_agent mocked, zero warnings.
- [ ] 8 — [HUMAN] NOT RUN — needs the sandbox: create #exmouth-mutual-aid, set
  `CRISIS_CHANNEL` to its id, `slack run`, post a plain offer (expect indexed +
  threaded ack), a plain need (expect one threaded reply), and chatter (expect
  silence).

**NotACrisisMessage-silence design**
- The DM/engaged-thread path calls `compose_reply` unconditionally — every message
  gets an LLM reply. The passive-channel path does NOT: it runs `route_message` and
  composes ONLY when a `NeedRecall` comes back. `route_message` returns `None` for
  both an acked offer and a `NotACrisisMessage`; in both cases there is no need reply
  to compose, so guarding compose on a returned `NeedRecall` is the silence
  guarantee — chatter never reaches `run_agent`/`compose_reply`, so no LLM reply, no
  block, no reaction ever lands in the channel for non-crisis text (debug log only).
- The passive path also does NOT post the `:warning:` error reply the DM path posts
  on failure — an error reply on every failed parse would be exactly the channel
  noise the guardrail forbids. Failed passive parses log the exception and stay
  silent (covered by `::test_designated_channel_route_failure_stays_silent`).

**Evidence**
```
$ make pre-commit
... (format-check + lint-check clean) ...
tests/unit/listeners/events/test_message.py ..........              [ 22%]
tests/unit/listeners/test_channel_gate.py .....                     [ 24%]
...
============================= 243 passed in 1.29s ==============================

$ CRISIS_CHANNEL=C_EXMOUTH uv run python -  (in-process gating smoke)
CRISIS_CHANNEL = C_EXMOUTH
is_crisis_channel('C_EXMOUTH') = True
is_crisis_channel('C_OTHER')   = False
is_crisis_channel(None)        = False
designated/offer-or-chatter (route->None): route called=True compose called=False say called=False
designated/need (route->NeedRecall): route called=True compose called=True say called=False
other channel top-level: route called=False compose called=False say called=False
designated thread reply (not engaged): route called=False compose called=False say called=False
DM (route->None, still replies): route called=True compose called=True say called=False
```

**Notes**
- Guardrails re-checked: (confirmation) unchanged — a need reply still carries the
  recall blocks + feedback buttons via `compose_reply`; (never assert safety)
  unchanged — same prose path; (sourcing) unchanged — offer ack + recall blocks keep
  their source/timestamp; (degraded states) unchanged — `NeedRecall` still carries
  the explicit "search unavailable" block.
- `os.environ` read at call time matches the repo's established pattern
  (`agent/deps.py`, `agent/agent.py`, `mocks/server.py`) — no `pydantic-settings`
  module exists yet, so a tiny helper is the lightest fit and is hot-reloadable.
- AC8 ([HUMAN]) requires a live sandbox + TTY (`slack run`), which the agent
  environment cannot drive — left for manual verification.
- Code is NOT committed (awaiting Tester PASS + PM ACCEPT).

### [Tester] 2026-06-12 23:55 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check`: 71 files formatted; `ruff check`: all checks passed)
- Unit tests: 243 passed / 0 failed (double-run identical), 15 of those are task-006 new (5 gate + 10 handler)
- Integration tests: 5 passed / 1 skipped (no live key) / 0 failed (double-run identical)
- Warnings: 0 (`filterwarnings = ["error"]` in effect; no warning surfaced)
- Note: SWE log says "20 new tests (5 gate + 15 handler)"; actual is 5 gate + 10 handler = 15. Count mismatch only, not a defect.

**E2E adversarial pass** (handler driven in-process; route_message/compose_reply/store mocked seams)
- Happy path — plain need in designated channel: `route->NeedRecall` -> `route=1, compose=1, say(handler)=0, set_status=1`; reply threads under triggering msg (`deps.thread_ts == event ts`), `mention_requester=True`. PASS
- Happy path — plain offer/chatter (`route->None`): `route=1, compose=0, say=0`. Silent, as required. PASS
- Break path 1 (silence on parse/route exception, passive path): `route` raises -> `compose=0, say=0, logger.exception=1`. NO `:warning:` posted into channel. PASS — and correct re guardrail 4: a passive listener that never promised a reply staying quiet on unparseable chatter is right; the DM path's explicit `:warning:` is unchanged (`_reply_conversationally` still posts it). Silent passive parse-failure does NOT violate guardrail 4.
- Break path 2 (subtypes/bot in designated channel): `message_changed`, `message_deleted`, `channel_join`, `bot_id`, `subtype=bot_message` -> all `route=0, compose=0, say=0`. Guards fire before the gate. PASS
- Break path 3 (boundary: empty / missing text): `text=""` and absent `text` key -> `route=1, compose=0, say=0` (route mocked None). No crash. PASS
- Break path 4 (weird config: `CRISIS_CHANNEL` = a DM id): DM event whose channel == configured id hits the `is_dm` branch FIRST -> unconditional DM reply (`compose=1`), passive gate never consulted. Sane. PASS
- Break path 5 (hot-reload, one process): env flips unset->C1->C2->whitespace->unset all reflected immediately by `is_crisis_channel` / `designated_channel_id` (read at call time, not cached). PASS
- Break path 6 (double-run state pollution): same offer routed twice -> identical gating result; handler holds no gating state. PASS
- **Break path 7 (FAIL — dual routing): mention-prefixed top-level message in the designated channel.** Slack delivers BOTH an `app_mention` and a `message.channels` event for one user message (manifest subscribes to both: `bot_events` = `app_mention` + `message.channels/.groups/.im`). Pre-006, `handle_message` skipped ALL top-level channel messages (`else: return`, comment: "Top-level channel messages are handled by app_mentioned") — deliberate deferral, no overlap. Task 006 replaced that skip with `_listen_in_designated_channel`, which has NO mention guard. Result for `<@bot> I can offer water` posted top-level in the crisis channel: `handle_app_mentioned` route+ack (offer indexed + acked once) AND `handle_message` route+ack (offer indexed + acked AGAIN) — `route_message` invoked 2x for one message. For a mention-prefixed need: compose called 2x => TWO threaded replies. This is a double-ack / double-reply (and double-index) — exactly the channel noise the design forbids, and it breaks AC2's "exactly ONE composed reply".

**Acceptance criteria**
- [x] 1 PASS — `CRISIS_CHANNEL` read via `listeners/channel_gate.py:27` (`os.environ.get(...).strip()`, empty/whitespace -> None = off); documented in `.env.example`. Verified by `tests/unit/listeners/test_channel_gate.py` (5/5) + in-process hot-reload smoke.
- [ ] FAIL — 2. Designated-channel top-level routing. Within a single handler invocation it is correct (offer acked via `route_message` thread_ts=event ts, returns None, compose skipped; need -> exactly one threaded `compose_reply`, mention_requester=True, deps.thread_ts==event ts; other channels skipped with `route_message` NOT called; DMs + thread replies unchanged — all verified). BUT the AC requires "needs answered in-thread with **the standard reply**" / one reply, and a mention-prefixed top-level post in the designated channel is processed by BOTH `app_mention` and `message` handlers (no mention guard in the passive path), producing a double ack / double reply / double index. See Break path 7.
      Expected: a top-level offer/need in the designated channel is acked/answered EXACTLY ONCE regardless of whether it @mentions the bot.
      Actual: a mention-prefixed top-level post is processed twice (app_mention + passive message) -> two acks / two replies / indexed twice.
      Fix: in `_listen_in_designated_channel` (or before the `is_crisis_channel` branch in `handle_message`), skip messages that mention `context.bot_user_id` so the `app_mention` handler owns them — mirroring the pre-006 deferral. Add a regression test: mention-prefixed top-level message in the designated channel -> passive `route_message` NOT called.
- [ ] FAIL — 3. NotACrisisMessage silently ignored. The pure passive path IS silent (Break paths 1 & happy-path-offer/chatter: compose=0, say=0, debug log only) — design is sound and guardrail-4-compliant. Marked FAIL only because the dual-routing in AC2 means a mention-prefixed non-crisis message would still reach the `app_mention` path (which always composes); the silence guarantee holds for the passive path but is undermined for mention-prefixed chatter in the channel. Resolves with the AC2 fix.
- [x] 4 PASS — bot/self + subtype guards apply before the gate (`message.py:45-48`). Verified by `::test_bot_message_in_designated_channel_ignored`, `::test_message_changed_subtype_in_designated_channel_ignored`, and adversarial subtypes (`message_deleted`, `channel_join`, `bot_message`) all `route=0`.
- [x] 5 PASS — `docs/adr/0004-passive-listening-single-channel.md` present, Nygard-complete (Status: Accepted + Date / Context / Decision / Consequences), one-channel posture + `CRISIS_CHANNEL` trigger + widen/narrow fork documented.
- [x] 6 PASS — `CLAUDE.md` env surface gains the `CRISIS_CHANNEL` line (diff present).
- [x] 7 PASS — gating-table unit tests present and green (parse/run_agent mocked, 0 warnings). Coverage is thorough for the single-handler decision; missing only the cross-handler dual-routing case (see AC2 fix).
- [ ] 8 [HUMAN] — Awaiting human verification (live sandbox: create #exmouth-mutual-aid, set CRISIS_CHANNEL, post plain offer/need/chatter). NOT run; agent env cannot drive `slack run`.

**Evidence**
```
$ make format-check
71 files already formatted
$ make lint-check
All checks passed!
$ make unit-tests
243 passed in 1.29s        (double-run: 243 passed in 1.26s)
$ make integration-tests
5 passed, 1 skipped in 0.96s   (double-run: 5 passed, 1 skipped in 0.86s)

# Dual-routing trace (one mention-prefixed offer message, designated channel):
app_mention  -> route_message called 1x, compose called 1x
message      -> route_message called 1x, compose called 0x   # offer acked inside route_message
TOTAL route_message invocations for ONE user offer message: 2   # indexed + acked TWICE
# mention-prefixed need: app_mention compose=1 + message compose=1 => 2 threaded replies

# manifest.json bot_events confirm both events arrive:
"bot_events": ["app_home_opened","app_mention","assistant_thread_started",
               "message.channels","message.groups","message.im"]
```

**Other issues found**
- SWE log test count is off (claims 15 handler tests; 10 exist). Cosmetic.
- `_STATUS_LOADING_MESSAGES` is now duplicated as an inline list in `app_mentioned.py:43-49` — not introduced by this task, but a follow-up dedup candidate (PASS-with-note, do not block).
- Demo impact is limited: the demo's primary need is posted in the agent thread (DM path, unaffected) and the "second need" compounding flow is a PLAIN post (single-route, correct). The dual-routing bites only mention-prefixed top-level posts — but residents `@`-ing the bot in the channel is realistic, and double-ack/double-index corrupts the recall index, so it must be fixed before acceptance.

**VERDICT: FAIL** — 1 blocking defect (dual routing of mention-prefixed top-level messages in the designated channel -> double ack/reply/index; AC2 + AC3). Pure passive path, gating, silence-on-failure, hot-reload, ADR, docs, and full suite are all green.

### [SWE] 2026-06-12 — Fix (Break path 7: dual routing)

**Defect** Slack delivers BOTH an `app_mention` and a `message.channels` event for one
user message that mentions the bot. `_listen_in_designated_channel` had no mention
guard, so a mention-prefixed top-level post in `CRISIS_CHANNEL` was processed by both
`handle_app_mentioned` AND `handle_message` -> double ack / double reply / double index.

**Fix (the exact guard added)** In `_listen_in_designated_channel`
(`listeners/events/message.py`), immediately after reading `text`, before the
`route_message` call:

```python
if context.bot_user_id and f"<@{context.bot_user_id}>" in text:
    logger.debug(
        "Passive listen in %s: skipping mention-prefixed post (app_mention owns it)",
        channel_id,
    )
    return
```

This restores the pre-006 deferral for mention-prefixed posts: the `app_mention`
handler owns them, so the passive path skips them. The `context.bot_user_id` truthiness
check makes the guard a no-op (defers nothing) when the bot id is unknown/`None` —
defensive, never crashes. Docstring updated to document the deferral.

**Test added** `tests/unit/listeners/events/test_message.py::test_designated_channel_mention_prefixed_post_deferred_to_app_mention`
— mention-prefixed top-level post (`<@B1> I can offer water`, where context.bot_user_id
== "B1") in the designated channel asserts the passive path defers: `route_message` NOT
called, `compose_reply` NOT called, `say` NOT called, `set_status` NOT called. (Without
the guard `route_message` fires once -> test red. With the guard -> green.) The
`_channel_event` helper gained a `text=` kwarg so the event can carry a real mention.

**Files modified**
- `listeners/events/message.py` — mention guard in `_listen_in_designated_channel` + docstring.
- `tests/unit/listeners/events/test_message.py` — regression test + `text=` kwarg on `_channel_event`.

**Tests**
- Unit: 244 passing, 0 failing, zero warnings (`filterwarnings = ["error"]`). +1 over the
  243 the Tester ran (the new regression test). Task-006 new tests now 16: 5 gate + 11 handler.
- Integration: N/A — no infra touched.

**Acceptance criteria** (deltas from the Tester's FAIL)
- [x] 2 — now ack/answered EXACTLY ONCE regardless of mention-prefix; the dual-routing is
  closed. Verified by the new regression test + the existing single-handler gating table.
- [x] 3 — the silence guarantee now holds for mention-prefixed chatter too: such posts no
  longer leak into the always-composing app_mention path via a duplicate passive route.

**Count correction (cosmetic, per Tester)** The original [SWE] log claimed "20 new tests
(5 gate + 15 handler)". The Tester correctly counted 15 (5 gate + 10 handler). With this
fix's regression test the task-006 total is now **16: 5 gate + 11 handler**.

**QA tail**
```
$ make format-fix && make lint-fix && make format-check && make lint-check && make pre-commit
uv run ruff format            -> 71 files left unchanged
uv run ruff check --fix       -> All checks passed!
uv run ruff format --check    -> 71 files already formatted
uv run ruff check             -> All checks passed!
uv run pytest tests/unit      -> 244 passed in 1.20s
```

**Notes**
- Guardrails re-checked: (confirmation) unchanged; (never assert safety) unchanged;
  (sourcing) unchanged; (degraded states) unchanged. The guard only changes WHICH handler
  owns a mention-prefixed post — it does not alter any reply content or remove sourcing.
- The `_STATUS_LOADING_MESSAGES` inline-duplication note in `app_mentioned.py` is left as
  the Tester flagged it: out of scope for this fix, follow-up dedup candidate.
- Code is NOT committed (awaiting Tester re-review PASS + PM ACCEPT).

### [Tester] 2026-06-12 — QA (focused re-review: Break path 7 fix)

Scope: re-verify only the dual-routing blocker from my prior FAIL. Did NOT re-walk the
whole AC set — pure-passive gating, silence, hot-reload, ADR, docs were green last cycle
and are unchanged by this fix (the guard only changes WHICH handler owns a
mention-prefixed post; no reply content touched).

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check`: 71 files already formatted;
  `ruff check`: All checks passed)
- Unit tests: 244 passed / 0 failed (was 243; +1 is the new regression test), zero
  warnings (`filterwarnings = ["error"]` in effect)
- Integration tests: 5 passed / 1 skipped (no live key) / 0 failed
- Double-run identical.

**Guard placement / correctness review** (`listeners/events/message.py`)
- Placement: subtype/bot guards fire in `handle_message` (L45-48) BEFORE dispatch; the
  mention guard sits at L189-194 inside `_listen_in_designated_channel`, after `text` is
  read (L181) and BEFORE `route_message` (L196). Correct — nothing routes past it.
- None handling: `if context.bot_user_id and f"<@{context.bot_user_id}>" in text:` —
  short-circuits to a no-op when `bot_user_id` is falsy/None (defers nothing, never
  crashes, still routes). Verified in-process (see edge below).
- DM path untouched: `_reply_conversationally` has no mention guard; the DM/engaged-thread
  branch in `handle_message` (L53-62) returns before the passive branch is reached.
  Verified in-process (mention-prefixed DM still composes once).
- Hand-off is real, not a drop: `handle_app_mentioned` (`app_mentioned.py`) strips
  `<@...>` then calls `route_message` + `compose_reply` — so a deferred mention-prefixed
  offer/need is still processed EXACTLY ONCE, by the app_mention handler. No message lost.

**Regression test goes red without the guard (verified by mutation)**
Temporarily neutralised the guard (`if False and ...`) and ran
`test_designated_channel_mention_prefixed_post_deferred_to_app_mention`:
```
AssertionError: Expected 'route_message' to not have been called. Called 1 times.
  Calls: [call('<@B1> I can offer water', author='U_REQ', ... bot_user_id='B1', ...)]
```
Red without the guard, green with it. File restored from backup; lint re-confirmed clean.

**E2E adversarial pass** (handle_message driven in-process; route_message/compose_reply/
store mocked seams; `CRISIS_CHANNEL=C_CRISIS`)
- Re-run of Break path 7 — mention-PREFIXED offer in designated channel:
  `route=0 compose=0 say=0 set_status=0`. Exactly the deferral; NO passive route. PASS
- Break path 7b — mention-prefixed NEED (route would return NeedRecall): `route=0
  compose=0`. No second threaded reply — the double-reply is closed. PASS
- Edge (mid-text mention, not prefix) — `hey folks <@B1> can you help, I need water`:
  `route=0`. Guard is `contains`, not `startswith`; app_mention fires for ANY mention, so
  `contains` is the correct predicate — no top-level mention slips past to dual-route. PASS
- Edge (DIFFERENT user mentioned, not the bot) — `<@U999> thanks! I can offer blankets`:
  `route=1`. Guard does NOT over-block; passive listening still engages. PASS
- Edge (different-user mention that is a NEED): `route=1 compose=1`. Passive need reply
  unaffected by the guard. PASS
- Edge (bot_user_id=None, mention-prefixed text): `route=1`. Guard no-ops on unknown bot
  id and still routes — defensive, no crash. PASS
- DM path (mention-prefixed DM): `compose=1`. DM unconditional reply untouched. PASS
- Sanity (plain no-mention offer): `route=1 compose=0`. Offer still acked inside
  route_message. PASS

**Acceptance criteria** (only the previously-failed ones re-verified; PASSes spot-checked)
- [x] 2 PASS (was FAIL) — a top-level offer/need in the designated channel is now
  acked/answered EXACTLY ONCE regardless of mention-prefix. Mention-prefixed posts defer
  to `handle_app_mentioned` (verified it owns + routes them once); plain posts route
  passively once. Evidence: new regression test
  `tests/unit/listeners/events/test_message.py::test_designated_channel_mention_prefixed_post_deferred_to_app_mention`
  (red without guard, green with) + the 8 in-process break/edge paths above.
- [x] 3 PASS (was FAIL) — silence guarantee now holds for mention-prefixed chatter too:
  such a post no longer leaks into the always-composing app_mention path via a duplicate
  passive route; the app_mention handler is the single owner. Pure passive chatter stays
  silent as before. Evidence: Break path 7/7b (no double processing) + prior-cycle
  silence tests still green.
- [x] 1, 4, 5, 6, 7 — unchanged by this fix; green last cycle, full suite still green.
- [ ] 8 [HUMAN] — Awaiting human verification (live sandbox), as before. NOT run.

**Evidence**
```
$ make pre-commit
uv run ruff format --check   -> 71 files already formatted
uv run ruff check            -> All checks passed!
uv run pytest tests/unit     -> 244 passed in 1.28s
$ make integration-tests     -> 5 passed, 1 skipped in 0.99s
$ # guard mutated out:
$ uv run pytest ...::test_designated_channel_mention_prefixed_post_deferred_to_app_mention
1 failed  (route_message called 1 time)  -> guard restored -> 244 passed
```

**Other issues found**
- None new. The `_STATUS_LOADING_MESSAGES` inline-duplication in `app_mentioned.py:43-49`
  remains a PASS-with-note follow-up dedup candidate (out of scope here), as last cycle.

**VERDICT: PASS** — the dual-routing blocker is closed. Mention-prefixed top-level posts
in the designated channel now route through the app_mention handler ONLY (exactly one
ack/reply/index); plain posts route passively once; the guard correctly no-ops on an
unknown bot id and never over-blocks different-user mentions; the DM path is untouched.
The new regression test is genuine (red without the guard). Full suite green, zero
warnings. Only AC8 ([HUMAN], live sandbox) remains outstanding. Hand off to PM for
acceptance review.
