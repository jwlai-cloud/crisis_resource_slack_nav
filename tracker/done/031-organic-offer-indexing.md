# 031 — Index operator/integration-posted offers (skip only the agent's own messages)

Verified live 2026-06-13: seeded offers never reach the in-memory index, so the board
only fills if hand-built. Root cause — a seeded offer arrives as:
`{"user":"U0BA67L9HRS", "bot_id":"B0B9MHFTGMD", "app_id":"A0B9ZKSDZ9B", "text":"Offering: a 2kW petrol generator…"}`.
It carries a `bot_id` because it was posted by an app's WebClient (the operator's
user token through the bot client). `listeners/events/message.py:47` skips **any**
message with a `bot_id` (`if event.get("bot_id"): return`), so every
operator/integration-posted offer is dropped before parsing → never indexed → never on
the board. (Human-typed offers index fine; only API-posted ones are lost.)

Fix the over-broad guard: skip only the **agent's own** messages, not the mere presence
of a `bot_id`. Then API-posted offers (seeds + any tool/integration post) are parsed,
indexed, acked, and appear on the board organically — no hand-built board.

## Design decisions (locked)
- **Skip the agent itself, by identity — not by `bot_id` presence.** Replace the blanket
  `if event.get("bot_id"): return` with a guard that skips when the message is from THIS
  agent: `event.get("user") == context.bot_user_id` (the bot's own user id; the agent's
  acks/replies all carry it). Keep skipping message **subtypes** (edits/deletes/joins/
  `message_changed`, etc.) — unchanged. Everything else (humans + operator/integration
  API posts) is processed.
- **No self-loop.** The agent's own ack ("Logged your offer") and need replies post as
  the bot (`user == bot_user_id`) → still skipped. Verify there is no
  index→ack→re-process loop. (Also: the existing mention-dedup + `message_changed`
  subtype skip remain.)
- **Acceptable wider intake.** Processing now includes posts from OTHER bots/integrations
  in the channel. In the crisis channel that's rare; `parse_message` classifies them
  (offer/need/chatter) and chatter is silently dropped. Document the trade in the handler
  docstring + an ADR note. If a concrete noisy bot shows up later, narrow then (its own
  fork) — do not pre-optimize.
- **Defensive when `bot_user_id` is unknown.** If `context.bot_user_id` is `None`
  (shouldn't happen in socket mode, but be safe), fall back to the OLD behaviour for that
  message (skip on `bot_id`) so we never accidentally treat our own posts as user input.
- **Scope = the message-event guard + its tests.** Do NOT change recall, parsing, the
  board, or the system prompt. `recall.client._drop_agent_noise` already filters the
  agent's own messages out of RTS results by `bot_user_id` — consistent with this.

## Implementation sketch
- `listeners/events/message.py::handle_message`: change the guard. Roughly:
  - keep `if event.get("subtype"): return`
  - replace `if event.get("bot_id"): return` with:
    skip if the message is from the agent itself — `bot_user_id = context.bot_user_id;
    if bot_user_id and event.get("user") == bot_user_id: return`; and when
    `bot_user_id` is falsy, retain the `bot_id` skip as a safe fallback.
  - Update the docstring (the routing comment block) to state "skip our own messages,
    not any bot" + the wider-intake trade.
- Tests (`tests/unit/listeners/events/test_message.py`): 
  - operator API post (user=OPERATOR, bot_id=SOMEBOT) in the crisis channel → routed
    (route_message called / offer path reached), NOT skipped.
  - the agent's own message (user == bot_user_id, bot_id set) → skipped (no route).
  - a subtype message → skipped (unchanged).
  - a plain human message → routed (unchanged).
  - `bot_user_id is None` + bot_id present → skipped (safe fallback).
  Mock route_message / the deps so no live calls.
- ADR: a short amendment to ADR-0004 (passive listening) or a one-paragraph ADR note —
  SWE's call; at minimum the handler docstring carries the rationale.

## Acceptance criteria
1. [x] An operator/integration-posted message (real `user`, with a `bot_id` from the app)
   in CRISIS_CHANNEL is processed: an "Offering: …" post is parsed → `offer_index.add`
   → ack → `update_board`. — unit test (route reached; mock the rest).
2. [x] The agent's OWN messages (`user == bot_user_id`) are still skipped — no self-loop,
   no re-processing of its acks/replies. — unit test.
3. [x] Subtypes still skipped; plain human messages still routed (no regression). — tests.
4. [x] `bot_user_id is None` → safe fallback to the old `bot_id` skip. — unit test.
5. [x] Scope: only `listeners/events/message.py` (+ its test) changed; no recall/parsing/
   board/prompt changes. Guardrails unaffected (no safety/sourcing/confirm change). — diff + state.
6. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
7. [ ] [HUMAN] Live: `make seed-demo ARGS=--fresh` with the agent up → the agent acks each
   seeded offer and the Community Cases board fills (Open) on its own — no hand-built board.

## BDD scenarios
- Given a crisis-channel message with `user=U_OPERATOR, bot_id=B_APP, text="Offering: …"`,
  When handled, Then it is routed and the offer is indexed (not skipped).
- Given a crisis-channel message with `user=<bot_user_id>`, When handled, Then it is
  skipped (the agent never processes its own post).
- Given `context.bot_user_id is None` and a `bot_id` message, When handled, Then skipped.

## Out of scope
- `chat:write.customize` persona posts (task 024) — those post as the bot with a custom
  username (`user == bot_user_id`) and would still be skipped; varied-author offers need
  024's own handling, not this fix.
- The flaky LLM-parse one-off board populate (a dev convenience) and the
  `BACKFILL_ON_START` startup sweep (026) are unchanged; this fixes the *live* path.

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `listeners/events/message.py` — replaced the blanket `if event.get("bot_id"): return`
  with an identity-based self-guard: skip only when `event["user"] == context.bot_user_id`;
  fall back to the old `bot_id` skip only when `bot_user_id` is falsy (defensive). Rewrote
  the handler docstring to state "skip our own messages, not any bot", the wider-intake
  trade-off, and the no-self-loop rationale (carries the ADR-0004 amendment in code, per the
  SWE's-call note in the spec).
- `tests/unit/listeners/events/test_message.py` — replaced the old
  `test_bot_message_in_designated_channel_ignored` (which pinned the over-broad guard) with
  `test_agents_own_message_in_designated_channel_ignored` (identity-based), and added
  `test_operator_api_post_in_designated_channel_routed` (the bug) +
  `test_bot_user_id_none_falls_back_to_bot_id_skip` (fallback).

**Tests**
- Unit: 505 passing, 0 failing — `make unit-tests`. The `test_message.py` module: 13 passing.
- Integration: 5 passing, 1 skipped (`test_parsing_live` — no live provider key; pre-existing,
  unrelated to this change) — `make integration-tests`.
- TDD: wrote the operator-API-post test first; confirmed red (`route_message` called 0 times —
  the exact bug), then implemented the guard → green.
- Double-run stable: ran `test_message.py` twice, 13 passed both times.
- Zero warnings (`filterwarnings = ["error"]` in pyproject — the suite would error on any).

**Acceptance criteria**
- [x] AC1 — operator/integration API post (real user + bot_id) routed —
  `test_operator_api_post_in_designated_channel_routed`.
- [x] AC2 — agent's own message (`user == bot_user_id`) skipped, no self-loop —
  `test_agents_own_message_in_designated_channel_ignored`.
- [x] AC3 — subtype skipped (`test_message_changed_subtype_in_designated_channel_ignored`);
  plain human message routed (`test_designated_channel_offer_acked_no_compose`,
  `test_designated_channel_need_gets_one_reply`).
- [x] AC4 — `bot_user_id is None` falls back to `bot_id` skip —
  `test_bot_user_id_none_falls_back_to_bot_id_skip`.
- [x] AC5 — scope: `git status` shows only `listeners/events/message.py` +
  `tests/unit/listeners/events/test_message.py` modified. No recall/parsing/board/prompt
  touched. Guardrails unaffected (see below).
- [x] AC6 — `make pre-commit` (505 passed), unit + integration green, zero warnings,
  double-run stable.
- [ ] AC7 — [HUMAN] live `make seed-demo ARGS=--fresh` with the agent up; needs a real
  `slack run` socket + sandbox (TTY). Left for human verification.

**Guardrail recheck (routing/intake change)**
- This change touches only the intake guard in `handle_message` — it does NOT alter safety
  language, sourcing/timestamps, the confirmation step, or degraded-state handling. Those
  live downstream in `route_message` / recall / reply composition, all untouched.
- NO self-loop: the agent's acks and need replies post as the bot and carry its own user id;
  `event["user"] == context.bot_user_id` skips them, so an indexed offer's ack is never
  re-parsed/re-indexed/re-acked. Verified by `test_agents_own_message_in_designated_channel_ignored`
  and the e2e smoke (own-ack routed = False). Consistent with
  `recall.client._drop_agent_noise`, which already drops the agent's own posts from RTS by
  `bot_user_id`.

**Evidence**
```
$ make unit-tests
============================= 505 passed in 1.78s ==============================

$ make integration-tests
========================= 5 passed, 1 skipped in 0.84s =========================

$ uv run pytest tests/unit/listeners/events/test_message.py -q
.............                                                            [100%]
13 passed in 0.88s
```

E2E smoke (real `handle_message`, route/compose seams patched; exact verified root-cause
payload `{"user":"U0BA67L9HRS","bot_id":"B0B9MHFTGMD","app_id":"A0B9ZKSDZ9B","text":"Offering: a 2kW petrol generator"}`):
```
[AC1] operator API offer routed (was dropped before fix): True
[AC2] agent's own ack routed (must be False — no self-loop): False
[AC4] bot_user_id=None + bot_id post routed (must be False — fallback): False
[AC3] plain human offer routed (regression): True
[AC3] message_changed subtype routed (must be False): False
ALL E2E ASSERTIONS PASSED
```

**Notes**
- ADR-0004 is PM territory (SWE is read-only on `docs/adr/`). The spec gave the SWE the call
  between an ADR amendment and a docstring note; I carried the full rationale + wider-intake
  trade-off in the `handle_message` docstring (product code) and left ADR-0004 untouched. If
  the PM wants the amendment in the ADR itself, that's a one-line rollup.
- Removed `test_bot_message_in_designated_channel_ignored`: it asserted the OLD over-broad
  behaviour (a bare `bot_id` with no matching user → skip), which is exactly what this task
  reverses. Replaced by the identity-based self-guard test.
- AC7 is the only [HUMAN]/live item — needs `slack run` against the sandbox (a TTY), which
  this environment can't drive.

### [Tester] 2026-06-13 21:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 97 files formatted; `ruff check` all
  checks passed; pre-commit unit run 505 passed).
- Unit tests: 505 passed / 0 failed (`make unit-tests`).
- Integration tests: 5 passed / 0 failed, 1 skipped (`test_parsing_live` — no live provider key;
  pre-existing, unrelated to this change).
- Warnings: 0 (confirmed under `filterwarnings = ["error"]` and an explicit `-W error` run).
- Double-run stable: full unit suite 505 passed twice; `test_message.py` 13 passed twice.

**E2E adversarial pass** (real `handle_message`, route/compose seams patched; exact verified
root-cause payloads)
- Happy path: operator/integration seeded offer `{"user":"U0BA67L9HRS","bot_id":"B0B9MHFTGMD","app_id":"A0B9ZKSDZ9B","text":"Offering: a 2kW petrol generator"}`
  in CRISIS_CHANNEL → `route_message` called once with the offer text, NOT skipped (PASS).
- Break path 1 (self-loop / state edge): agent's OWN ack `{"user":<bot_user_id>,"bot_id":"B_BOT","text":"Logged your offer…"}`
  → routed=False, composed=False, say=0 — the ack is never re-parsed/re-indexed/re-acked (PASS).
- Break path 2 (fallback / None state): `context.bot_user_id is None` + a `bot_id` post → skipped
  (falls back to the old bot_id skip). Also verified own-post-with-bot_id under None → skipped, so
  the fallback can never let our own posts through (PASS).
- Break path 3 (malformed/missing field — other-bot edge): a message with NO `user` key but a
  `bot_id`, `bot_user_id` set → `user` (None) != `bot_user_id` → routed. This is the documented
  intended *wider intake* (parse + classify; chatter dropped downstream). Handled sanely, no crash (PASS).
- Break path 4 (boundary): empty-text operator offer (`text:""`) → routed to `route_message`
  (which classifies); no crash, no leaked trace (PASS).
- Regression: `message_changed` subtype → skipped (PASS); plain human offer → routed (PASS);
  mention-prefixed post `<@bot> …` → deferred to app_mention, not passively routed (PASS); operator
  DM (`channel_type:im`) → DM path composes even on `route_message`→None (PASS).

**Acceptance criteria**
- [x] PASS — AC1 operator/integration API post (real user + bot_id) ROUTED, offer text reaches
      `route_message`. Evidence: `test_operator_api_post_in_designated_channel_routed`
      (`tests/unit/listeners/events/test_message.py:267`) + E2E happy path above with the exact
      verified payload. Guard at `listeners/events/message.py:69-74`.
- [x] PASS — AC2 (CRITICAL no self-loop) agent's OWN message (`user == bot_user_id`, bot_id set)
      SKIPPED — no route/compose/say. Evidence: `test_agents_own_message_in_designated_channel_ignored`
      (`:247`) + E2E break path 1. Ack posts via `say(...)` as the bot
      (`listeners/recall_reply.py:222`) → comes back with `user == bot_user_id` → skipped at
      `message.py:71`. Loop closed.
- [x] PASS — AC3 subtypes skipped, plain human messages routed (no regression). Evidence:
      `test_message_changed_subtype_in_designated_channel_ignored` (`:347`),
      `test_designated_channel_offer_acked_no_compose` (`:97`),
      `test_designated_channel_need_gets_one_reply` (`:114`), DM path
      `test_dm_path_unchanged_composes_even_without_recall` (`:229`); engaged-thread + other-channel
      paths green (`:195`, `:178`). Mention-dedup + DM paths reconfirmed in E2E.
- [x] PASS — AC4 `bot_user_id is None` + bot_id present → SKIPPED (safe fallback). Evidence:
      `test_bot_user_id_none_falls_back_to_bot_id_skip` (`:293`) + E2E break path 2 (incl. own-post
      variant). `elif event.get("bot_id"): return` at `message.py:73`.
- [x] PASS — AC5 scope: `git status --porcelain` shows only `listeners/events/message.py` +
      `tests/unit/listeners/events/test_message.py` modified (tracker doc aside). No recall/parsing/
      board/prompt change. Diff is the guard swap + docstring only.
- [x] PASS — AC6 `make pre-commit` + unit (505) + integration (5 passed/1 skipped) green, 0 warnings,
      double-run stable.
- [ ] [HUMAN] — AC7 awaiting human live verification (`make seed-demo ARGS=--fresh` with `slack run`
      against the sandbox; needs a TTY this environment can't drive).

**Guardrail recheck (routing/intake change only)**
- Touches only the intake guard in `handle_message`. Safety language, sourcing/timestamps, the
  confirmation step, and degraded-state handling all live downstream in `route_message` / recall /
  reply composition — all untouched. Block Kit payloads unchanged.
- **NO SELF-LOOP — explicit:** the agent's acks and need replies post as the bot and carry its own
  `user` id; `event["user"] == context.bot_user_id` skips them (verified routed=False/composed=False/
  say=0 on the exact own-ack shape), so an indexed offer's ack is never re-parsed, re-indexed, or
  re-acked. The fallback branch (bot_user_id None) skips on `bot_id`, which our own posts always
  carry — so the loop is closed even when we can't identify ourselves by user id. Consistent with
  `recall.client._drop_agent_noise`. **Confirmed: no index→ack→re-process loop.**

**Evidence**
```
$ make pre-commit
uv run ruff format --check
97 files already formatted
uv run ruff check
All checks passed!
============================= 505 passed in 1.85s ==============================

$ make unit-tests
============================= 505 passed in 1.75s ==============================   (re-run: 505 passed in 1.66s)

$ make integration-tests
========================= 5 passed, 1 skipped in 0.88s =========================

$ uv run pytest tests/unit/listeners/events/test_message.py -W error -q
13 passed in 0.85s   (double-run: 13 passed both times)

E2E (real handle_message, route/compose patched):
[AC1] seeded operator offer routed: True  (route text == offer)
[AC2] agent's own ack routed: False / composed: False / say: 0   ← no self-loop
[AC4] bot_user_id=None + bot_id post routed: False  (fallback skip)
[AC4] bot_user_id=None + own post routed: False     (fallback protects own posts)
[edge] no-user + bot_id, bot_user_id set → routed: True   (intended wider intake)
[reg]  message_changed subtype routed: False
[reg]  plain human offer routed: True
[reg]  mention-prefixed post routed: False  (app_mention owns it)
[reg]  operator DM composed: True           (DM always replies)
[bound] empty-text operator offer routed: True (no crash)
ALL ADVERSARIAL E2E ASSERTIONS PASSED
```

**Other issues found** (non-blocking; do NOT block this task — flagged for the orchestrator/PM)
- `listeners/backfill.py:122` (task 026 `BACKFILL_ON_START` startup sweep) STILL uses the old
  blanket `if message.get("bot_id") or message.get("subtype"): continue`. Given the verified root
  cause (seeded operator offers carry a `bot_id`), the *backfill* path will still drop the very
  seeded offers it was built to recover — the live path (031) and the startup-sweep path now
  diverge. The 031 spec explicitly scopes backfill OUT ("the `BACKFILL_ON_START` startup sweep (026)
  are unchanged; this fixes the *live* path"), so this is correctly NOT part of 031, but it is a
  genuine inconsistency worth a follow-up task. AC7's live happy path (`seed-demo` + agent up) does
  NOT depend on backfill — the live `handle_message` path indexes the seeds organically — so AC7 is
  unaffected.
- ADR-0004: SWE carried the rationale + wider-intake trade-off in the `handle_message` docstring
  (product code) rather than amending the ADR (SWE is read-only on `docs/adr/`). If the PM wants the
  amendment in ADR-0004 itself, that's a one-line PM rollup — no AC names the ADR as expected output,
  so it is not a Tester FAIL.

**VERDICT: PASS** (AC1–AC6 verified with evidence; AC7 [HUMAN] awaiting live sandbox verification.)
