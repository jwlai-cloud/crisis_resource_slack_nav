# 010 — Action buttons: Connect / Mark resolved / Not relevant

Demo script beats 1:20–1:45: tap **Connect me** → DM to the offerer fires; tap **Mark resolved** → state change. The bounded-autonomy confirmation step (guardrail 1) becomes real UI.

## Acceptance criteria

1. [x] Workspace match cards gain buttons: **Connect me** (primary) and **Not relevant**. After a connect, the connected card gains **Mark resolved**.
2. [x] Connect me → opens/posts a group DM (requester + offerer) with a short sourced intro ("X needs …, Y offered … (posted <ts>) — connecting you both; verify details together"). Requires `mpim:write`/`im:write` (bot has im:write; check mpim — add scope to manifest if needed, note re-install requirement in the log).
3. [x] Mark resolved → offer index `mark_resolved` (and need status when tracked) + visible confirmation (✅ on the card / short threaded ack). Resolved offers stop matching (004 behavior, now reachable via UI).
4. [x] Not relevant → acknowledges + (for now) just visual dismissal state on the card; log the signal for future rank tuning.
5. [x] Handlers in `listeners/actions/` following the template's action-handler pattern (feedback_buttons.py as reference); button `action_id`s carry the offer/need ids via `value` (JSON payload, typed parse on receipt).
6. [x] Concurrency note from 004's Tester: mark_matched/mark_resolved are non-atomic get→copy→set — add the minimal lock (threading.Lock in OfferIndex) since button handlers now mutate from Bolt's thread pool. ADR-0003's revisit trigger fires; update the ADR status note.
7. [x] Every button action appends to an in-memory audit trail (actor, action, target ids, ts) — thin precursor to W4's audit log; surface count in logs only for now.
8. [x] Unit tests: handler routing (mocked ack/say/client), payload round-trip, index transitions via the handlers, lock behavior smoke. Zero warnings.
9. [ ] [HUMAN] live verification: full demo beat — need → match card → Connect me → DM fires → Mark resolved → card updates; screenshot evidence.

## Out of scope
Escalate (W4 coordinator flow), Canvas (W4), card colors/fields (008).

## Log

### [SWE] 2026-06-12 12:40 — Implementation

**Files created**
- `recall/payload.py` — `ConnectPayload` (frozen dataclass): the match identity carried on a button `value` as compact JSON. `to_value()` / `from_value()` round-trip; snippet truncated (≤280 chars) and dropped-if-needed to stay under Slack's 2000-char value cap; `from_value` raises `ValueError` on malformed JSON / missing `offerer_id`. Lives in the `recall` layer (the compose step owns the contract) so the dependency arrow stays `listeners` → `recall`. **No requester in the payload** — it's the clicker (`body["user"]["id"]`).
- `matching/audit.py` — `AuditTrail` / `AuditEvent` + module singleton `audit_trail`. Append-only, process-local (mirrors ADR-0003), `threading.Lock`-guarded; `record()` stamps `datetime.now(UTC)` (aware-UTC, naive rejected) and logs the running count; `list_events()` returns a snapshot copy.
- `listeners/actions/crisis_buttons.py` — the three handlers + `CRISIS_ACTIONS` registry. `handle_crisis_connect` / `handle_crisis_resolve` / `handle_crisis_not_relevant`. Each `ack()`s first, parses the payload (explicit ephemeral on failure), audits, then acts. Card region rewritten via `chat_update` (swap the clicked `block_id`'s action row).
- `tests/unit/recall/test_payload.py` (6), `tests/unit/matching/test_audit.py` (3), `tests/unit/listeners/actions/test_crisis_buttons.py` (16) + `conftest.py` (body/offer builders).

**Files modified**
- `recall/blocks.py` — every workspace/index match group now ends with an `ActionsBlock` (Connect me primary `crisis_connect` + Not relevant `crisis_not_relevant`), stable unique `block_id` per match (`crisis_actions_{i}`); both buttons carry the same `ConnectPayload` value. Added `ACTION_CONNECT/RESOLVE/NOT_RELEVANT` constants. Degraded/empty replies carry NO buttons (verified).
- `recall/models.py` — `RecallMatch` gains optional `offer_id: str = ""` (index id when an index hit; empty for RTS-only). Backward-compatible — all existing constructions omit it.
- `matching/conversion.py` — `match_from_offer` now sets `offer_id=str(offer.id)` so the resolve handler can `mark_resolved` the exact offer.
- `matching/index.py` — added `threading.Lock`; `add`/`lookup`/`all_offers`/`_set_status`/`keyword_lookup` all guard dict access. The non-atomic get→copy→set transition is now fully inside the lock (the 004 Tester race). `keyword_lookup` snapshots under the lock then scores outside (no lock held during pure CPU work; no iterating a dict another thread mutates).
- `matching/__init__.py` / `recall/__init__.py` — re-export `audit_trail`/`AuditTrail`/`AuditEvent` and `ConnectPayload`/`ACTION_*`.
- `listeners/actions/__init__.py` — registers each `CRISIS_ACTIONS` id to its handler.
- `manifest.json` — added bot scope **`mpim:write`** (group DM for requester+offerer). **Re-install required**: a `slack run` re-install applies the new scope. Until then the connect handler degrades to the offerer-only DM fallback (uses `im:write`, already present) — no silent failure.
- `docs/adr/0003-in-memory-matching-index.md` — appended a "Status note (2026-06-12, task 010)": the "Not thread-safe" revisit trigger fired; minimal `threading.Lock` added; supersession (external store) not needed for the single-process demo. Decision unchanged (hardening note only). [Done at the task's explicit instruction; no decision authored.]

**Payload design**
`value` = compact JSON: `{"offerer_id": <Slack uid, always>, "offer_id": <UUID str, index hits only>, "permalink": <RTS hits only>, "snippet": <≤280 chars>}`. Empty fields omitted; snippet dropped if the value would exceed 2000 chars. Requester is NEVER in the payload — derived from `body["user"]["id"]` at click time, so the agent can't act on a match on anyone's behalf (guardrail 1). Resolve uses `offer_id`; the intro uses `permalink` (RTS) or the snippet to source the connect.

**Scope / manifest changes**
- Added `mpim:write` to bot scopes (AC2). Re-install via `slack run` applies it; graceful offerer-DM fallback in the meantime.
- Relocated the payload type from `listeners/actions/` to `recall/` during implementation to keep the layer dependency one-directional (`listeners` → `recall`, never the reverse). No behavior change.

**Tests**
- Unit: 184 passing, 0 failing (was 98 at end of 004; +25 new for this task: payload 6, audit 3, handlers 16; plus button assertions folded into `recall/test_blocks.py` and `matching/test_conversion.py`). Zero warnings (`filterwarnings=["error"]`).
- Integration: 5 passing, 1 skipped (live-LLM, no key) — no infra touched by this task.
- Lock smoke: `test_concurrent_mark_resolved_loses_no_writes` fans 200 distinct `mark_resolved` calls across threads behind a `Barrier`; all 200 end RESOLVED (a lost write would leave one OPEN).

**Acceptance criteria**
- [x] AC1 — Connect me (primary) + Not relevant on every match card; connected card → Mark resolved — `recall/blocks.py`; `test_blocks.py::test_match_card_carries_connect_and_not_relevant_buttons`, `test_crisis_buttons.py::test_connect_swaps_in_mark_resolved_button`.
- [x] AC2 — Connect → group DM (requester+offerer) + sourced intro; `mpim:write` added + re-install noted; offerer-DM fallback — `test_connect_opens_group_dm_with_requester_and_offerer`, `test_connect_posts_sourced_intro`, `test_connect_falls_back_to_offerer_dm_when_group_dm_fails`.
- [x] AC3 — Mark resolved → `mark_resolved` + visible card state + threaded ack; resolved stops matching — `test_resolve_marks_index_offer_resolved`, `test_resolve_mutes_card_and_posts_threaded_confirmation` (+ 004 `keyword_lookup` excludes RESOLVED).
- [x] AC4 — Not relevant → muted Dismissed card + logged signal; no connection/index change — `test_not_relevant_mutes_card_to_dismissed`, `test_not_relevant_makes_no_connection_and_no_index_change`.
- [x] AC5 — handlers in `listeners/actions/` (feedback pattern); `action_id`s carry ids via JSON `value`, typed parse — `crisis_buttons.py`, `test_payload.py` round-trip.
- [x] AC6 — `threading.Lock` in `OfferIndex`; ADR-0003 status note — `matching/index.py`, lock smoke test, ADR note.
- [x] AC7 — audit trail append per action (actor/action/target/ts), count logged — `matching/audit.py`, `test_audit.py`, `test_*_records_audit_event`.
- [x] AC8 — unit tests: handler routing (mocked ack/client), payload round-trip, index transitions via handlers, lock smoke. Zero warnings.
- [ ] [HUMAN] AC9 — live demo beat (need → card → Connect → DM → Resolve → card updates, screenshot). NOT RUN — requires `slack run` + sandbox + TTY; manifest re-install also needed for `mpim:write`.

**Guardrail re-check (CLAUDE.md — touches confirmation + sourcing + degraded states, so all four re-checked)**
1. Surfaces and ranks; a human decides — buttons ARE the confirmation step; nothing fires automatically. The requester is the clicker, never carried in the payload, so the agent can't act on anyone's behalf (`test_button_value_omits_requester_identity`). Dismiss makes no connection and no index change (`test_not_relevant_makes_no_connection_and_no_index_change`). PASS.
2. Never assert safety — the connect intro says "verify anything before relying on it — I just made the introduction"; no road/travel/placement claim (`test_connect_posts_sourced_intro` asserts "verify"). PASS.
3. Every item sourced + timestamped — match cards keep the existing source/timestamp/contact/verify context line; buttons are additive. The connect intro cites the offer (snippet) + RTS permalink when present. Audit events are aware-UTC stamped. PASS.
4. Degraded states explicit — malformed payload → explicit ephemeral ("didn't do anything"), no side effects (`test_malformed_payload_posts_visible_message_and_does_nothing`); group DM unavailable → offerer-DM fallback, then an explicit "couldn't open … nothing was sent" ephemeral if that also fails (`test_connect_posts_visible_message_when_both_dm_attempts_fail`). Never silent. PASS.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
65 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
...
tests/unit/listeners/actions/test_crisis_buttons.py ................     [ 22%]
tests/unit/matching/test_audit.py ...                                    [ 33%]
tests/unit/matching/test_index.py ..............                         [ 42%]
tests/unit/recall/test_blocks.py ................                        [ 63%]
tests/unit/recall/test_payload.py ......                                 [ 72%]
============================= 184 passed in 1.03s ==============================

$ make integration-tests
5 passed, 1 skipped in 0.94s
```

End-to-end demo-beat drive (real `recall.blocks` + real handlers, fake client; no live Slack):
```
=== MATCH CARD ===  actions: [(crisis_connect, Connect me, primary), (crisis_not_relevant, Not relevant, None)]
   value: {"offerer_id":"U_JORDAN","offer_id":"d7a6877c-…","snippet":"2kW generator — collect any time today (Exmouth)"}
=== TAP Connect me ===  conversations_open users=U_REQUESTER,U_JORDAN · intro posted · card → [crisis_resolve] · index → matched
=== TAP Mark resolved ===  card → "Resolved — closed, won't match again" · threaded ack · index → resolved
=== TAP Not relevant ===  card → "Dismissed — won't surface again"
=== DEGRADED malformed value ===  chat_postEphemeral ":warning: I couldn't read this match's details…" (no side effects)
=== AUDIT TRAIL ===  connect / resolve / not_relevant by U_REQUESTER, each aware-UTC stamped
```

**Notes**
- No new runtime deps.
- Did NOT touch `agent/agent.py` SYSTEM_PROMPT (bounded-autonomy language already covers confirmation) and did NOT start 008's visual work — buttons are placed cleanly (one `ActionsBlock` per match, stable `block_id`) so 008 can restyle around them.
- Buttons attach ONLY to workspace/RTS + index match cards (the only thing `build_recall_blocks` renders). Official MCP items are composed elsewhere and stay informational — no actions.
- `mark_matched` on connect uses the offer id when present (index hit); an RTS-only match has no id, so connect makes no index transition (`test_rts_only_match_connect_does_not_touch_index`). Need-status tracking (AC3 "when tracked") is not wired — Needs aren't indexed in the current design (only Offers are), so there's no Need row to transition; flagged as a non-issue, not a silent descope.
- `slack manifest validate` NOT RUN — the CLI prompts and needs a TTY (fails headless); `manifest.json` confirmed valid JSON and the scope is a single well-formed entry.

### [Tester] 2026-06-12 21:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 65 files clean; `ruff check` all passed)
- Unit tests: 184 passed / 0 failed
- Integration tests: 5 passed / 0 failed / 1 skipped (live-LLM, no key — not touched by this task)
- Warnings: 0 (`filterwarnings=["error"]` in effect; suite would error on any warning)
- State-pollution double-run: PASS — re-ran the full unit suite (184) and re-ran `test_audit + test_crisis_buttons + test_index + test_audit` together in one session (33); all green. Handler tests swap the module-level `audit_trail`/`offer_index` for fresh instances via `_patch_singletons`, so the singletons don't leak between tests.

**E2E adversarial pass** (drove the real handlers + real `recall.blocks` with a fake `WebClient` — no live Slack/TTY in this env; same approach as the SWE's demo-beat drive)
- Happy path (index-hit Connect): `handle_crisis_connect` → `conversations_open(users="U_REQUESTER,U_OFFERER")` · sourced intro posted · index → `matched` · card flipped to `[crisis_resolve]` · 1 audit event `(U_REQUESTER, connect, offer:…)` (PASS)
- Resolve → stops matching (end-to-end through handler then `keyword_lookup`): before=1 hit → handler resolve → index `resolved` → after=0 hits (PASS)
- Break path 1 (boundary/malformed payload — 8 inputs incl. `''`, `[]`, `{}`, `null`, `123`, `{"offer_id":"x"}`, `not json {`): every one raises `ValueError`; handler posts the explicit "I didn't do anything" ephemeral, `conversations_open` not called, 0 audit events (PASS — degraded guardrail)
- Break path 2 (boundary — 5000-char snippet): `to_value()` truncates snippet to 280, serialized value = 315 chars (< 2000 cap); parses back with snippet intact (PASS)
- Break path 3 (concurrency — my own variant: 200× concurrent `mark_matched`+`mark_resolved` on the SAME offer behind a `Barrier`): no crash, no torn write; final is consistently a valid clean transition. Plus `keyword_lookup` under concurrent `add`/`mark_resolved` from a writer thread: 0 `RuntimeError` (snapshot-under-lock holds). SWE's 200-distinct-offer lock smoke also re-run green. (PASS)
- Break path 4 (adversarial a — double-click Connect, same payload twice): produces 2 `conversations_open`, 2 duplicate intro DMs, 2 audit events. No idempotency. Not a guardrail breach (each is a human click; nothing auto-acts) and not spec'd — recorded under "Other issues" as a non-blocking hardening note. After one real click the card's Connect button is swapped out via `chat_update`, so this is a narrow stale-card/double-tap race, not the normal path. (PASS — not a blocker)
- Break path 5 (adversarial b — Resolve on already-resolved offer): index stays `resolved` (idempotent), still posts the threaded confirmation + card flip; 1 `resolve` audit event (PASS)
- Break path 6 (adversarial c — self-connect, clicker == offerer): opens DM `users="U_SAME,U_SAME"`, intro reads "Connecting <@U_SAME> and <@U_SAME>". Cosmetically odd but the bot never auto-acts and never asserts safety; harmless. (PASS — noted)
- Break path 7 (adversarial d — RTS-only match, no offer_id): connect works, intro cites the permalink, `mark_matched` NOT called, audit target = `offerer:U_SAM` (PASS)
- Break path 8 (adversarial e — `conversations_open` hard API error on both attempts): 2 attempts (group then offerer), explicit ephemeral "couldn't open … nothing was sent", card NOT flipped (`chat_update` not called) (PASS — degraded guardrail). Note: the `connect` audit event is recorded BEFORE the attempt, so a fully-failed connect still leaves a `connect` event — see "Other issues".

**Guardrail re-check (mandatory — touches confirmation + sourcing + degraded states)**
1. Human decides — PASS. `handle_crisis_connect:181` `requester = (body.get("user") or {}).get("id", "")` — requester is derived ONLY from the click body. `ConnectPayload` has no requester field (structurally impossible to carry one). No handler auto-acts: each `ack()`s then acts solely on the clicked payload; no scheduler/loop/auto-trigger exists. Dismiss makes no connection and no index change (verified: `conversations_open` not called, offer stays `OPEN`).
2. Never assert safety — PASS. `_intro_text:160-165` ends "verify anything before relying on it — I just made the introduction"; no road/travel/placement claim.
3. Sourced + timestamped — PASS. Match cards keep the source/timestamp/contact/verify context line; buttons are additive. Connect intro cites the offer snippet + RTS permalink. Audit events stamped aware-UTC (`_ensure_aware_utc(datetime.now(UTC))`, naive rejected).
4. Degraded explicit — PASS. Malformed payload → explicit ephemeral, zero side effects; group DM unavailable → offerer-DM fallback; both fail → explicit "nothing was sent" ephemeral, no card flip. Never silent.

**Acceptance criteria**
- [x] AC1 PASS — Connect (primary "Connect me") + Not relevant on every match card; connected card → single Mark resolved button. Evidence: `recall/blocks.py:115-160`; `test_blocks.py::test_match_card_carries_connect_and_not_relevant_buttons`, `::test_every_match_card_carries_action_buttons`; handler drive flipped card to `[crisis_resolve]`.
- [x] AC2 PASS — Connect → group DM (requester+offerer) + sourced intro; `mpim:write` added (manifest valid, only that scope); offerer-DM fallback. Evidence: handler drive `users="U_REQUESTER,U_OFFERER"`, intro names both + cites offer; `test_connect_opens_group_dm_*`, `test_connect_falls_back_to_offerer_dm_when_group_dm_fails`.
- [x] AC3 PASS — Resolve → index `mark_resolved` + visible card state + threaded ack; resolved stops matching. Evidence: end-to-end drive index→`resolved`, `keyword_lookup` 1→0 hits; `test_resolve_marks_index_offer_resolved`, `test_resolve_mutes_card_and_posts_threaded_confirmation`. (Need-status "when tracked" correctly N/A — Needs aren't indexed; not a silent descope.)
- [x] AC4 PASS — Not relevant → muted Dismissed card + logged signal; no connection, no index change. Evidence: `test_not_relevant_mutes_card_to_dismissed`, `test_not_relevant_makes_no_connection_and_no_index_change` (offer stays OPEN).
- [x] AC5 PASS — handlers in `listeners/actions/crisis_buttons.py` (feedback pattern), registered via `CRISIS_ACTIONS` in `listeners/actions/__init__.py`; `value` is typed-parsed JSON (`ConnectPayload.from_value`). Evidence: `test_payload.py` round-trips; `__init__.py` diff wires each id.
- [x] AC6 PASS — `threading.Lock` in `OfferIndex` guards every dict access incl. the get→copy→set; `keyword_lookup` snapshots under lock then scores outside. ADR-0003 status note appended (revisit trigger fired, minimal lock, no supersession). Evidence: `matching/index.py:49-126`, lock smoke + my connect+resolve race + lookup-under-mutation stress all clean; `docs/adr/0003` diff present and topical.
- [x] AC7 PASS — every handler appends exactly one `AuditEvent` (actor from clicker, action verb, target, aware-UTC ts), count logged. Evidence: `matching/audit.py`, `test_audit.py`, `test_*_records_audit_event`; handler drive showed exactly one event per action.
- [x] AC8 PASS — unit tests cover handler routing (mocked ack/client), payload round-trip, index transitions via handlers, lock smoke. 184 pass, 0 warnings.
- [ ] [HUMAN] AC9 — live demo beat (need → card → Connect → DM → Resolve → screenshot). Awaiting human verification — requires `slack run` + sandbox + TTY + `mpim:write` re-install. Not verifiable headless; left unchecked.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
65 files already formatted
uv run ruff check
All checks passed!
============================= 184 passed in 1.14s ==============================

$ make integration-tests
5 passed, 1 skipped in 0.87s

$ (payload probes)  5000-char snippet -> value len 315 (<2000); 8 malformed inputs all ValueError; requester never serialized; unicode round-trips
$ (handler drive)   resolve via handler: index resolved, keyword_lookup 1 -> 0 hits
$ (concurrency)     200x connect+resolve same offer: no torn write; keyword_lookup under mutation: 0 RuntimeError
$ (manifest)        valid JSON; bot-scope delta = +"mpim:write" only
```

**Other issues found** (non-blocking — for orchestrator/PM to triage, not FAILs)
- Double-click Connect is not idempotent: a repeated click on the same payload opens a second DM and posts a second intro (2 audit events). Not spec'd and not a guardrail breach (every action is still a human click; nothing auto-acts), and the real card swaps the Connect button out on first click. Worth a follow-up hardening task (e.g. short-circuit if the offer is already MATCHED) but does not block this task.
- Audit-before-side-effect ordering: `handle_crisis_connect` records the `connect` event before attempting the DM, so a fully-failed connect (both DM attempts fail) still leaves a `connect` audit event. Defensible (it records intent/attempt) and harmless for the W1-precursor trail, but the W4 audit log may want to distinguish attempted-vs-completed. Note for W4.
- Payload value cap is robust for realistic input (snippet dropped if needed), but a pathological multi-thousand-char `permalink` alone could still exceed 2000 chars since only the snippet is droppable. Real Slack permalinks are well under 200 chars, so unreachable in practice — noted only for completeness.

**VERDICT: PASS** — all eight implementable ACs verified with code + runtime evidence; full suite green twice over with zero warnings; e2e adversarial pass green on every break path; all four guardrails re-checked and hold (guardrail 1 confirmation step is real, requester is the clicker only, nothing auto-acts). AC9 is [HUMAN] and awaits live `slack run` verification. The three "Other issues" are non-blocking notes, not defects.

### [Human] 2026-06-12 21:24 — AC9 live verification (PASS)
Live in sandbox: match card rendered with Connect me / Not relevant + full sourcing;
Connect click posted the sourced intro with original-message link (self-connect
collapsed to the bot DM as expected — real group DM deferred to the Mara persona,
task 013) and the card flipped to "✅ Connected — Mark resolved". Resolve transition
exercised; handler behavior covered by 185-test suite incl. concurrency.
