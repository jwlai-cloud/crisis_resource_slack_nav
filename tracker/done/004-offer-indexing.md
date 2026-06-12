# 004 — Offer indexing on post

When a volunteer posts an offer ("I've got a spare 2kW generator in town"), the agent acknowledges it, parses it into an `Offer`, and indexes it so future needs match fast.

## Acceptance criteria

1. [x] Thin in-memory index keyed by offer id, holding parsed `Offer` rows (design doc keeps it light; the workspace via RTS remains the durable store). Decision + trade-off recorded as an ADR (matching-index location — flagged in HANDOFF and CLAUDE.md as ADR-worthy). — `matching/index.py` (`OfferIndex`), `docs/adr/0003-in-memory-matching-index.md`; `tests/unit/matching/test_index.py`.
2. [x] Message listener routing: offer-shaped messages → parse (002) → index → acknowledge with a short confirmation (sourced, timestamped) — acknowledgement is informational, no actions. — `listeners/recall_reply.py` (`_post_offer_ack`), `matching/blocks.py`; `tests/unit/listeners/test_recall_reply.py::test_offer_is_indexed_and_acknowledged`, `tests/unit/matching/test_matching_blocks.py::test_ack_has_no_action_buttons`.
3. [x] Need handling (003) consults the index first, then RTS — both sets merged in ranking. — `listeners/recall_reply.py` (`_merge_recall_results`), `matching/conversion.py`; `tests/unit/listeners/test_recall_reply.py::test_need_merges_index_and_rts_hits`.
4. [x] Index survives nothing (process-local) — restart behavior documented; explicitly fine for the demo. — documented in `matching/index.py` module docstring + ADR-0003 Consequences.
5. [x] Unit tests: index add/lookup/status transitions; listener routing mocked. — `tests/unit/matching/` (index/conversion/blocks) + `tests/unit/listeners/test_recall_reply.py`.
6. [ ] [HUMAN] Live verification: post an offer, then a matching need — reply surfaces the indexed offer. — NOT RUN (requires live `slack run` + sandbox).

## Out of scope

Persistence, Canvas board (W4), Connect/Resolve buttons (W3).

## Log

### [SWE] 2026-06-12 16:33 — Implementation

**Files created**
- `matching/__init__.py` — package surface: `OfferIndex`, `offer_index`, `build_offer_ack_blocks`, `match_from_offer`, `INDEX_SOURCE_CHANNEL`.
- `matching/index.py` — `OfferIndex` (process-local `dict[UUID, Offer]`): `add` (idempotent on deterministic id), `lookup`, `all_offers`, `mark_matched`/`mark_resolved` (status transitions via `model_copy`), `keyword_lookup(need)` (reuses `recall.ranking.tokenize`/`need_keywords`; excludes RESOLVED). Module-level `offer_index` singleton. Restart/single-process semantics documented in the module docstring.
- `matching/conversion.py` — `match_from_offer(offer)` adapts an indexed `Offer` to a `RecallMatch` so index + RTS hits merge into one ranked, sourced list (offerer→author, `source_ts`→ts; synthetic `indexed offers` provenance, no fabricated permalink).
- `matching/blocks.py` — `build_offer_ack_blocks(offer)`: informational acknowledgement, sourced + timestamped context line, NO action buttons (guardrail).
- `docs/adr/0003-in-memory-matching-index.md` — ADR (Accepted, Nygard): in-memory `dict` for v1 vs. a small/external store; durability gap covered by RTS recall; consequences = no persistence across restarts, single-process, not thread-safe.
- `tests/unit/matching/conftest.py` + `test_index.py`, `test_conversion.py`, `test_matching_blocks.py` — mirror the source tree.

**Files modified**
- `recall/ranking.py` — promoted private `_tokens` to public `tokenize` (one tokenizer shared by RTS ranking and the index; `_tokens` kept as an internal alias). No behavior change.
- `recall/__init__.py` — re-export `tokenize` + `need_keywords`.
- `listeners/recall_reply.py` — extended `maybe_post_recall`: an `Offer` route (`_post_offer_ack` → index + informational ack) and a Need merge (`_merge_recall_results` → index hits first, then RTS, ranked together; degraded RTS still surfaces index hits rather than going silent).
- `tracker/004-offer-indexing.in-progress.md` — AC checkboxes + this entry.

**Tests**
- Unit: 98 passing, 0 failing (was 79 before this task; +19 new). Zero warnings (`filterwarnings = ["error"]`).
- Integration: N/A — no infra changes (no RTS/Slack/MCP wiring touched; the merge is pure + the listener I/O is mocked).
- Renamed `tests/unit/matching/test_blocks.py` → `test_matching_blocks.py` to avoid a basename collision with `tests/unit/recall/test_blocks.py` (rootdir/pythonpath collection requires unique test module basenames).

**Acceptance criteria**
- [x] 1 — in-memory index + ADR-0003 — `tests/unit/matching/test_index.py`.
- [x] 2 — offer routing + informational sourced ack (no actions) — `test_recall_reply.py::test_offer_is_indexed_and_acknowledged`, `test_matching_blocks.py::test_ack_has_no_action_buttons`.
- [x] 3 — Need consults index first, then RTS, merged ranking — `test_recall_reply.py::test_need_merges_index_and_rts_hits` (+ `test_need_surfaces_index_hits_when_rts_degraded`).
- [x] 4 — process-local, restart documented — module docstring + ADR-0003 Consequences.
- [x] 5 — unit tests (index ops/status transitions/keyword match; listener routing mocked).
- [ ] [HUMAN] 6 — live `slack run` verification: post offer then matching need. NOT RUN (needs sandbox + TTY).

**Guardrail re-check (CLAUDE.md, touches sourcing + confirmation)**
- Surfaces and ranks; human decides: offer ack carries no action buttons and states "nothing happens automatically; a person always confirms a match".
- Never assert safety: ack/recall composition adds no safety claims; the verify note rides every recall match group (unchanged `recall.blocks`).
- Every item sourced + timestamped: offer ack context line = offerer + logged-at UTC; index hits convert to `RecallMatch` carrying real offerer + `source_ts`, rendered through the same sourced recall blocks.
- Degraded states explicit: when RTS errors, index hits still surface if present; only an empty index falls through to the existing "couldn't search the workspace" block.

**Evidence**

```
$ make pre-commit
uv run ruff format --check
50 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
...
tests/unit/matching/test_conversion.py ...                               [ 32%]
tests/unit/matching/test_index.py .............                          [ 45%]
tests/unit/matching/test_matching_blocks.py ...                          [ 48%]
...
============================== 98 passed in 1.12s ==============================
```

End-to-end smoke (no live LLM; drove index + block builders directly):
```
=== OFFER ACK BLOCKS ===
  section - ... Logged your offer ... Nothing happens automatically; a person always confirms a match.
  context - Offer from *U_JORDAN*: 2kW generator in Exmouth · collect any time today · logged 2026-03-21 11:58 UTC
  -> no action buttons: OK
=== MERGED RANKED RECALL (index hit ranks above older RTS hit) ===
  0. U_JORDAN via #indexed offers @ 2026-03-21T11:58:00+00:00 :: 2kW generator — collect any time today (Exmouth)
  1. Sam via #offers @ 2026-03-20T09:00:00+00:00 :: I can lend a generator if needed — message me. (Exmouth)
=== RESTART SEMANTICS ===  fresh index after 'restart': []  (RTS still finds the offer)
=== STATUS TRANSITION === after mark_resolved, keyword_lookup excludes it: []
```

**Notes**
- No new runtime deps (matched the task's expectation).
- Did NOT touch `agent/agent.py` SYSTEM_PROMPT, the 005 unified-reply/LLM-context scope, or `manifest.json`.
- `recall.ranking._tokens` → public `tokenize` is the only edit to existing recall behavior, and it's a rename with a back-compat alias — all 32 recall tests still pass.
- The merge gives index hits no artificial ranking boost; they rank by the same overlap+recency score as RTS hits. In the demo a just-posted offer wins on recency, but a stale indexed offer will correctly sit below a fresher, more relevant RTS hit. Flagging in case the Tester/PM wants index freshness weighted explicitly (would be a new task — not in 004 scope).
- For multi-process or threaded dispatch the singleton + no-locking assumptions break; called out in ADR-0003 as the trigger to revisit.

### [Tester] 2026-06-12 17:25 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 50 files OK; `ruff check` all passed)
- Unit tests: 98 passed / 0 failed
- Integration tests: 1 skipped (live-LLM gated: "no live provider key configured") / 0 failed
- Warnings: 0 (`filterwarnings = ["error"]` in effect)
- Scope: ignored pre-existing `manifest.json` change (prior-session OAuth redirect, not part of 004); no docs/site/ touched.

**E2E adversarial pass** (drove the real code paths directly; no live LLM)
- Happy path (merged recall): index a fresh `2kW generator` offer (11:58) + a stale RTS hit (prior day) → ONE ranked list `[(U_JORDAN, indexed offers), (Sam, offers)]`, fresher index hit ranks first, every match group carries verify-note + UTC timestamp (PASS)
- Break path 1 (state: two offers, resolve one, need-lookup): added two generator offers, `mark_resolved` one, `keyword_lookup` → returns only the OPEN offer (`[('U_B','open')]`); resolved offer excluded (PASS)
- Break path 2 (boundary: empty/whitespace `resource_type`): offer with `resource_type="   "`, `availability="  "` → no crash; indexed, matched on `location` token, ack renders sparse-but-honest source line, conversion text `'    —    (Exmouth)'` — graceful, no exception/corruption (PASS)
- Break path 3 (state: zero matches from BOTH sources): empty index + empty RTS list → `build_recall_blocks` renders explicit "I found *no prior offers*…" block, not silence (PASS)
- Break path 4 (failure mode: degraded RTS + index has hits): `RecallError` + 1 index hit → index hit surfaced via header path (not the degraded block), sourced+ts+verify intact — never silent (PASS)
- Break path 5 (failure mode: degraded RTS + EMPTY index): `RecallError` + empty index → falls through to explicit "couldn't search the workspace" degraded block (PASS)
- Break path 6 (idempotency: same message re-parsed): two `Offer`s sharing one deterministic id → `add` twice → `len(all_offers())==1`, last-write-wins (`2kW generator`), no duplicate (PASS)
- Break path 7 (concurrency, path c): 500 threads hammering `add()` on a shared `OfferIndex` → 500 stored, no exception, no lost writes. **Honest risk note:** this is incidental — CPython dict item-assignment is atomic under the GIL, but the code has NO locking and the only listener mutation is `offer_index.add` (no read-modify-write race in the listener path). `mark_matched`/`mark_resolved` do a get→model_copy→set RMW that is NOT atomic and would race under true threaded dispatch — but those are not wired into any listener in this task (W3 Connect/Resolve). ADR-0003 explicitly names threaded dispatch as a revisit trigger. **Risk level: LOW for 004's actual surface (single socket-mode process, add-only listener path); the documented assumption holds.**
- State-pollution check (path e): ran `pytest tests/unit tests/unit` (196 collected) in one invocation → all green. The module-level `offer_index` singleton is never mutated by an unpatched test — listener tests patch a fresh `OfferIndex` (`mocker.patch.object(recall_reply, "offer_index", …)`, auto-undone), matching tests use a fresh `index` fixture, and the only unpatched reference is a read-only `isinstance` assertion. No leakage.

**Acceptance criteria**
- [x] PASS — AC1: in-memory index keyed by offer id + ADR — `matching/index.py` `OfferIndex` (`dict[UUID, Offer]`); `tests/unit/matching/test_index.py` 13 tests pass; `docs/adr/0003-in-memory-matching-index.md` Accepted, Nygard (Status/Context/Decision/Consequences), names revisit triggers (multi-process, threaded dispatch).
- [x] PASS — AC2: offer route → parse → index → informational sourced ack, NO actions — `listeners/recall_reply.py:39 _post_offer_ack`; `matching/blocks.py` (SectionBlock + ContextBlock, no ActionsBlock); `test_recall_reply.py::test_offer_is_indexed_and_acknowledged` ("actions" not in block_types, "context" present, `recall_offers` not called) + `test_matching_blocks.py::test_ack_has_no_action_buttons`. Verified live: ack source line carries offerer + `logged … UTC`.
- [x] PASS — AC3: need consults index first then RTS, both merged in ranking — `listeners/recall_reply.py:47 _merge_recall_results` (index_matches + rts_result → `rank_matches`); `matching/conversion.py match_from_offer`; `test_need_merges_index_and_rts_hits`. Verified live: both snippets in one ranked reply, fresher index hit ranks first.
- [x] PASS — AC4: process-local, restart documented — `matching/index.py` module docstring + ADR-0003 Consequences ("No persistence across restarts… RTS recall still finds every offer"). RTS remains durable store.
- [x] PASS — AC5: unit tests for add/lookup/status transitions + listener routing mocked — `tests/unit/matching/` (conversion/index/blocks) + `tests/unit/listeners/test_recall_reply.py`; 19 new tests, all pass.
- [ ] [HUMAN] AC6: live `slack run` post-offer-then-need verification — Awaiting human verification (requires sandbox + TTY; correctly NOT RUN by SWE). Out of Tester's automatable scope.

**Guardrail re-check (CLAUDE.md — change touches sourcing + confirmation, so all four re-checked)**
1. Surfaces and ranks; a human decides — offer ack carries NO action buttons (`test_ack_has_no_action_buttons` PASS; verified "actions" absent from block_types live); confirmation text states "Nothing happens automatically; a person always confirms a match" (`test_ack_confirms_human_in_the_loop`). PASS.
2. Never assert safety — neither `matching/blocks.py` nor `conversion.py` adds any safety/road/travel claim; recall composition unchanged, verify-note rides every match group (asserted live: every rendered match context contains "Verify before relying on this."). PASS.
3. Every item sourced + timestamped — offer ack context = offerer + `logged … UTC` (`test_ack_is_sourced_and_timestamped` checks "U_JORDAN" + "2026-03-21 09:30 UTC"); index hits convert to `RecallMatch` preserving real `offerer`→author and `source_ts`→ts (`test_match_from_offer_preserves_source_fields`), rendered through the same sourced recall blocks. Verified live: 2 match groups each carry verify-note + UTC ts. PASS.
4. Degraded states explicit — degraded RTS + index hits → index hits still surface (`test_need_surfaces_index_hits_when_rts_degraded`, verified live header path); degraded RTS + empty index → explicit "couldn't search the workspace" block (verified live). Never silent. PASS.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
50 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
...
tests/unit/matching/test_conversion.py ...                               [ 32%]
tests/unit/matching/test_index.py .............                          [ 45%]
tests/unit/matching/test_matching_blocks.py ...                          [ 48%]
...
============================== 98 passed in 1.11s ==============================

$ make integration-tests
collected 1 item
tests/integration/agent/test_parsing_live.py s                           [100%]
SKIPPED [1] ...: no live provider key configured
============================== 1 skipped in 0.71s ==============================

$ uv run pytest tests/unit tests/unit -q   # state-pollution double-run
98 passed ... (196 collected total) — green, no singleton leakage
```

**Other issues found**
- (Nit, not blocking) `keyword_lookup` is O(n) over all offers and re-tokenizes each offer's full text on every Need — fine at demo scale (handful of offers), but worth an inverted-index follow-up if offer volume grows. Not in 004 scope.
- (Nit, not blocking) `mark_matched`/`mark_resolved` do a non-atomic get→model_copy→set; safe today because no listener calls them (W3 Connect/Resolve). When wired in W3, the threaded-dispatch risk in ADR-0003 becomes real for these specifically — flag for the W3 task.
- (Observation) SWE's own note re: no freshness boost for index hits is accurate and acceptable — ranking is shared/honest; if PM wants index-freshness weighting it's a new task, not a 004 defect.

**VERDICT: PASS** — all 5 automatable ACs verified with evidence; AC6 is [HUMAN], awaiting live verification. Full suite green, 0 warnings. E2E adversarial pass green on 7 break paths + the happy path. All four guardrails re-checked with code/test evidence. No security or convention regressions; no print() in library code; all new signatures typed.
