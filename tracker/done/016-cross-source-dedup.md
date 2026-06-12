# 016 — Dedup index/RTS twins + index-match display polish

Live 006 verification (2026-06-12): a freshly indexed offer appeared TWICE in one
reply — MATCH 1 from RTS (the channel message) and MATCH 2 from the in-memory
index (same content) — and the LLM prose mirrored the duplicate. The index card
also leaks raw ids: "Posted by U0BA67L9HRS in #indexed offers".

## Acceptance criteria

- [x] 1. Cross-source dedup in _merge_recall_results: an index hit and an RTS hit that
   are the same underlying offer collapse to ONE match — prefer the INDEX hit (it
   carries offer_id, enabling status transitions via the buttons) but adopt the RTS
   hit's permalink/channel for display when present. **AMENDED (PM, 2026-06-12):**
   twin ⟺ same author_id AND identical timestamp (PRIMARY, deterministic — the index
   hit and its RTS twin come from the same Slack message, so the offer's source_ts and
   the RTS match's ts are the same instant). Jaccard >= 0.85 same-author is retained as
   the SECONDARY fallback (catches a re-posted copy with a fresh ts). Replaces the
   original Jaccard-only rule, which under-collapsed loosely-phrased originals (the live
   cooker case, ~0.64).
- [x] 2. Index-match display polish in matching/conversion.py: author renders as a
   mention (<@id>), channel label becomes the real channel when known or
   "workspace memory" (no fake #indexed offers).
- [x] 3. LLM context reflects the deduped list (it already serializes post-merge — verify).
- [x] 4. Unit tests: twin collapse (keeps offer_id + adopts permalink), non-twin offers
   from the same author survive, display fields. Zero warnings.
- [ ] 5. [HUMAN] live: repeat the 006 need test — the cooker offer appears exactly once,
   with offer_id-backed buttons and the real channel label.

## Log

### [SWE] 2026-06-12 21:40 — Implementation

**Files modified**
- `listeners/recall_reply.py` — cross-source twin collapse (`_is_cross_source_twin` /
  `_merge_twin` / `_collapse_cross_source_twins`) wired into `_merge_recall_results`
  post-merge, pre-dismissal-filter, pre-rank; imports `tokenize`; adds
  `_TWIN_JACCARD_THRESHOLD = 0.85`.
- `matching/conversion.py` — index-card display polish: `author` now renders as a
  Slack mention `<@id>` (no leaked raw id), `INDEX_SOURCE_CHANNEL` is now
  `"workspace memory"` (no fake `#indexed offers`).
- `tests/unit/listeners/test_recall_reply.py` — twin-collapse tests (collapse to one,
  keeps index offer_id, adopts RTS permalink/channel, keeps own permalink when
  present, two different offers from same author both survive, no collapse across
  different authors) + post-merge deduped LLM-context test.
- `tests/unit/matching/test_conversion.py` — author-as-mention + "workspace memory"
  label tests; updated `preserves_source_fields` to the new `<@id>` author contract.

**Dedup design**
- `_collapse_cross_source_twins(index_matches, rts_matches)` concatenates index hits
  first, then untwinned RTS hits; each index hit absorbs at most one RTS twin and each
  RTS hit is consumed at most once (no fan-in). Final ordering is left to `rank_matches`
  downstream — the collapse step preserves order, it doesn't rank.
- `_is_cross_source_twin`: hard same-`author_id` gate, then `tokenize`-based Jaccard
  `>= 0.85` (same tokeniser as ranking/index/echo-filter; same threshold value the
  echo filter uses). Different authors with identical text are two genuine offers.
- `_merge_twin`: keeps the INDEX hit (for `offer_id` → button status transitions);
  fills only the display gaps (`permalink`/`channel`/`channel_id`) from the RTS twin
  when the index copy's permalink is empty. `RecallMatch` is a Pydantic model →
  `model_copy(update=...)`, never in-place mutation.

**Tests**
- Unit: 253 passing, 0 failing (was 244; +9 new). Zero warnings (`filterwarnings=error`).
- Integration: N/A — no infra changes (pure in-process recall logic).

**Acceptance criteria**
- [x] 1 — `tests/unit/listeners/test_recall_reply.py::test_merge_collapses_index_and_rts_twins_into_one`,
  `::test_merge_twin_keeps_index_offer_id`, `::test_merge_twin_adopts_rts_permalink_and_channel`,
  `::test_merge_twin_keeps_index_permalink_when_already_present`,
  `::test_merge_does_not_collapse_twins_with_different_authors`.
- [x] 2 — `tests/unit/matching/test_conversion.py::test_index_source_channel_is_workspace_memory_not_a_fake_channel`,
  `::test_match_from_offer_author_id_drives_a_real_mention`,
  `::test_match_from_offer_preserves_source_fields`.
- [x] 3 — `tests/unit/listeners/test_recall_reply.py::test_serialize_context_reflects_the_deduped_merged_list`
  (routes a need through `route_message`, asserts the post-merge `llm_context` lists the
  collapsed twin exactly once).
- [x] 4 — twin collapse + non-twin survival + display-field tests above; suite is zero-warning.
- [ ] 5 — [HUMAN] live re-run of the 006 need test. NOT RUN (no live sandbox here).

**Evidence**
```
$ make unit-tests
... 253 passed in 1.10s ...

$ uv run python  (end-to-end exercise of the recall path)
=== merged result ===
count: 1 (expect 1 — twin collapsed)
offer_id: 'e71be8b0-c071-5af7-9d3d-0328a7de9e3a' (expect the index offer id — buttons work)
permalink: 'https://acme.slack.com/archives/C123/p1742550600' (expect adopted RTS twin link)
channel: 'offers' (expect adopted RTS channel 'offers')
author: '<@U0BA67L9HRS>' author_id: 'U0BA67L9HRS'
Posted-by line: Posted by *<@U0BA67L9HRS>* in #offers · 2026-03-21 09:30 UTC · <https://.../p1742550600|View message>
Contact line:   Contact: <@U0BA67L9HRS>
=== index-only card (no RTS twin) ===
Posted-by line: Posted by *<@U0BA67L9HRS>* in #workspace memory · 2026-03-21 09:30 UTC
=== LLM context (post-merge, deduped) ===
1 prior offer(s) shown, ranked best-fit first:
1. contact=<@U0BA67L9HRS> · channel=#offers · when=... · text='generator — collect any time today (Exmouth)'
ALL END-TO-END CHECKS PASSED

$ make format-check && make lint-check && make pre-commit
71 files already formatted · All checks passed! · 253 passed
```

**Notes**
- **Threshold reality check (for the [HUMAN] live test):** the AC fixes Jaccard at
  0.85. The recomposed index text is `"{resource_type} — {availability} ({location})"`
  (e.g. `generator — collect any time today (Exmouth)`). If the *original* channel
  message RTS returns is phrased loosely (e.g. `"I have a spare generator in Exmouth,
  collect any time today"`), the pair scores ~0.75 and will **not** collapse. Verified:
  `generator collect any time today Exmouth` vs `spare generator collect any time today
  Exmouth` = 0.857 (collapses); the looser phrasing above = 0.75 (does not). So the
  live cooker test will collapse only if the original message phrasing stays close to
  the structured form. If the human still sees a twin, the lever is lowering
  `_TWIN_JACCARD_THRESHOLD` (a follow-up + ADR-worthy decision — I did not lower it,
  the AC pinned 0.85).
- **Cosmetic, out of AC scope:** `recall/blocks.py::_source_line` prefixes every channel
  with `#`, so a solo index card now reads `in #workspace memory`. Honest (no fake
  channel), but the `#` reads oddly for a non-channel label. Fixing it means touching
  `blocks.py` (outside this task's `conversion.py` scope) — flagging for a follow-up.

### [SWE] 2026-06-12 23:15 — Amendment (PM spec change: ts-identity twin rule + cosmetic)

PM amended AC1 in response to the threshold-reality flag above: the original
Jaccard-only twin rule under-collapsed the live cooker case (text overlap ~0.64,
below the 0.85 bar). The amended rule makes twin detection **deterministic** by
using the timestamp the index hit and its RTS twin share.

**Files modified**
- `listeners/recall_reply.py` — `_is_cross_source_twin` reworked to a two-tier,
  deterministic-first rule behind the unchanged hard same-`author_id` gate:
  1. **PRIMARY — timestamp identity.** `abs(index_match.ts - rts_match.ts) <=
     _TWIN_TS_TOLERANCE` ⟹ twin, regardless of text. Collapses the cooker case.
  2. **SECONDARY — Jaccard fallback.** When timestamps differ (a re-posted copy with
     a fresh ts), `tokenize`-based Jaccard `>= _TWIN_JACCARD_THRESHOLD` (0.85,
     unchanged) still collapses the pair. Imports `timedelta`; adds
     `_TWIN_TS_TOLERANCE = 1 ms`.
- `recall/blocks.py` — `_source_line` no longer prefixes `#` when the channel equals
  `INDEX_SOURCE_CHANNEL` ("workspace memory"); a real channel still gets `#`. (The
  label is imported *inside* the function to dodge a `matching` ↔ `recall` module-load
  import cycle — both packages cross-import Block-Kit helpers at top level.)
- `tests/unit/listeners/test_recall_reply.py` — new twin-ordering tests (ts-identity
  collapse with loose cooker text; a guard proving the cooker Jaccard is < 0.85;
  Jaccard-fallback collapse when ts differs; no collapse for different authors even
  with identical ts). Updated `test_merge_keeps_two_different_offers_from_same_author`
  to give the two distinct offers distinct timestamps (as two real Slack messages
  would have) so ts-identity correctly does NOT fire.
- `tests/unit/recall/test_blocks.py` — cosmetic tests: a real channel renders `in
  #general`; the index label renders `in workspace memory` with no `#`.

**TS-comparison findings (the load-bearing verification)**
Both conversion paths are the SAME pipeline applied to the SAME message ts string:
- Offer: `route_message` → `_event_ts_to_utc(event_ts)` = `datetime.fromtimestamp(
  float(ts), tz=UTC)` → `parse_message` → `Offer.source_ts` → `match_from_offer` sets
  `RecallMatch.ts = offer.source_ts`.
- RTS: `recall/models.py::match_from_message` = `datetime.fromtimestamp(float(
  message_ts), tz=UTC)`.

Measured (`uv run python`):
- float64 ULP at ~1.74e9 s is ~0.238 µs; `fromtimestamp` rounds to the nearest
  microsecond.
- Across every string spelling of one `SSSS.NNNNNN` value (canonical, trailing-zeros
  trimmed, extra trailing zeros), the parsed datetimes are **identical** — worst-case
  delta **0 µs**. So exact equality already holds; no normalization is required.
- End-to-end repro (real Offer + real `match_from_message` off the SAME ts string
  `1742653500.000400`): `index_hit.ts == rts_hit.ts` is `True`, delta `0.0 µs`.

The 1 ms `_TWIN_TS_TOLERANCE` is therefore **defence in depth at the RTS boundary**
(whose exact ts serialization we don't own), NOT a correctness crutch — the measured
need is 0. Documented as such in the constant's docstring.

**Tests**
- Unit: 259 passing, 0 failing (was 253; +6 net new). Zero warnings.
- Integration: N/A — no infra changes (pure in-process recall logic + a one-line
  Block Kit cosmetic).
- Red-check: temporarily disabling the ts-identity rule makes
  `test_twin_collapses_on_ts_identity_even_with_loose_text` FAIL (2 matches, Jaccard
  0.636 < 0.85), restored to PASS — the test genuinely depends on the primary rule.

**Acceptance criteria**
- [x] 1 (amended) — `tests/unit/listeners/test_recall_reply.py::test_twin_collapses_on_ts_identity_even_with_loose_text`,
  `::test_twin_collapses_via_jaccard_fallback_when_ts_differs`,
  `::test_no_collapse_for_different_author_even_with_identical_ts`,
  `::test_twin_text_jaccard_below_bar_is_proven_for_cooker_case` (+ existing collapse /
  offer_id / permalink-adoption tests still green).
- [x] Cosmetic — `tests/unit/recall/test_blocks.py::test_index_provenance_label_is_not_hash_prefixed`,
  `::test_real_channel_is_hash_prefixed`.
- [ ] 5 — [HUMAN] live re-run of the 006 cooker need test. NOT RUN (no live sandbox
  here). The amended rule means it now collapses on the shared message ts regardless of
  wording, so the earlier "phrasing must stay close to the structured form" caveat no
  longer applies.

**Evidence**
```
$ make unit-tests
... 259 passed in 0.99s ...   (zero warnings, filterwarnings=error)

$ uv run python  (end-to-end cooker flow off ONE message ts 1742653500.000400)
=== ts comparison (the decisive check) ===
index_hit.ts (offer.source_ts) : 2025-03-22T14:25:00.000400+00:00
rts_hit.ts   (RTS message_ts)  : 2025-03-22T14:25:00.000400+00:00
identical?                     : True
abs delta (us)                 : 0.0
text Jaccard                   : 0.636  (< 0.85 -> Jaccard alone would NOT collapse)
is_cross_source_twin           : True
=== merged result ===
count : 1 (expect 1 — twin collapsed on ts identity)
offer_id (buttons need it) : 'fde848c7-810d-58eb-b62f-4d788b79c732'
permalink (adopted RTS)    : https://acme.slack.com/archives/C_OFFERS/p1742653500000400
channel (adopted RTS)      : offers
=== index-ONLY card source line (cosmetic fix) ===
Posted by *<@U_COOK>* in workspace memory · 2025-03-22 14:25 UTC
ALL END-TO-END CHECKS PASSED

$ make format-fix && make lint-fix && make format-check && make lint-check && make pre-commit
71 files left unchanged · All checks passed! · 71 files already formatted · All checks passed! · 259 passed
```

**Notes**
- Threshold-reality caveat from the prior entry is RESOLVED by the amendment: ts-identity
  is independent of phrasing, so the cooker collapses deterministically. The Jaccard bar
  (0.85) is now only the secondary path for re-posted copies.
- One real-world property the ts-identity rule relies on: two *genuinely different* offers
  from one author come from two different Slack messages → two different timestamps, so
  they don't false-collapse. The updated same-author-different-offers test encodes this by
  giving the two offers distinct ts (the prior test's shared INDEX_TS was an artifact of
  the Jaccard-only world).
- Did NOT commit — handing to Tester per the contract.

### [Tester] 2026-06-12 23:55 — QA

**Test summary** (double-run, identical both times)
- Format / lint / pre-commit: PASS (`71 files already formatted`, `All checks passed!`, 259 unit passed).
- Unit tests: 259 passed / 0 failed.
- Integration tests: 5 passed / 1 skipped (live provider key absent — expected) / 0 failed.
- Warnings: 0 (`filterwarnings = ["error"]` confirmed in pyproject.toml:75 — any warning would have failed the run).
- Double-run: run 1 and run 2 both 264 passed, 1 skipped — no pollution, no order dependence.

**E2E adversarial pass** (drove the real `_merge_recall_results` / `_is_cross_source_twin` /
`_merge_twin` / `_collapse_cross_source_twins` + blocks composition + `ConnectPayload`)
- Happy path (live cooker scenario): indexed "gas cooker — can drop off (Exmouth town)" +
  RTS "Offering: portable gas cooker and 10kg of rice, Exmouth town, can drop off", same
  author `U_COOK` + same ts `1742653500.000400` → **exactly 1 match**; `offer_id` preserved
  (`fde848c7-…`), RTS `channel`/`channel_id`/`permalink` adopted, author `<@U_COOK>`,
  LLM context lists it once. PASS.
- Independent ts-identity verification (the load-bearing claim): ran one ts string through
  BOTH conversion paths (`_event_ts_to_utc`→`Offer.source_ts`→`match_from_offer` vs
  `recall.models.match_from_message`) across 4 string spellings (canonical,
  trimmed-zeros, extra-zeros). Every spelling → IDENTICAL aware-UTC datetime, delta 0.0 µs,
  `_is_cross_source_twin` True. The SWE's "measured need is 0" claim is confirmed. PASS.
- Red-check (is the ts rule load-bearing?): disabled the ts rule at runtime
  (`_TWIN_TS_TOLERANCE = -1µs`) → cooker case goes from 1 match to 2 (Jaccard 0.64 < 0.85
  can't save it); restored → 1. The primary rule genuinely does the work. PASS.
- Break path 1 (state edge — two REAL different offers, same author, 1s apart): both survive
  (count 2); `_is_cross_source_twin` between them is False. PASS.
- Break path 2 (boundary — ts tolerance): delta exactly 1.000 ms → twin True (inclusive `<=`);
  delta 1.001 ms with dissimilar text → twin False. Boundary correct. PASS.
- Break path 3 (merge precedence — index copy already has a permalink): `_merge_twin` keeps
  its own permalink/channel, does NOT adopt the RTS twin's, returns the same object. PASS.
- Break path 4 (button trace — offer_id → ConnectPayload): composed real blocks; the Connect
  button value decodes to `ConnectPayload(offerer_id=U_COOK, offer_id=fde848c7-…,
  permalink=…)`; `offer_index.mark_resolved(UUID(offer_id))` resolved the real index row.
  Buttons work end-to-end. PASS.
- Break path 5 (collapse order vs ranking): a stronger RTS generator hit (different author)
  outranks an older tarp index hit post-merge — `rank_matches` owns final order, collapse
  only preserves order. PASS.
- Break path 6 (double-run pollution within the merge path): re-adding the same offer
  (idempotent index) and re-running → 1 match both times. PASS.
- Edge — empty-text twin pair: no crash; empty union + differing ts → False; same ts → True
  (ts rule fires regardless of text). PASS.
- Edge — missing `author_id` on index match: hard gate → never a twin. PASS.
- Edge — degraded RTS (`RecallError`) with index hits present → index hits surfaced (list,
  not silent); fully degraded (empty index) → `RecallError` passes through. PASS.

**Acceptance criteria**
- [x] PASS — 1 (amended) Cross-source dedup, ts-identity PRIMARY + Jaccard SECONDARY behind
      same-author gate. Evidence: live cooker scenario collapses to 1 with offer_id kept +
      RTS permalink/channel adopted; red-check proves ts rule is load-bearing
      (listeners/recall_reply.py:156-241); tests
      `::test_twin_collapses_on_ts_identity_even_with_loose_text`,
      `::test_twin_collapses_via_jaccard_fallback_when_ts_differs`,
      `::test_no_collapse_for_different_author_even_with_identical_ts`,
      `::test_merge_keeps_two_different_offers_from_same_author` all green.
- [x] PASS — 2 Index-match display polish. Evidence: `match_from_offer` renders
      `author="<@{offerer}>"` and `INDEX_SOURCE_CHANNEL="workspace memory"`
      (matching/conversion.py:24,46); rendered source line shows `<@U_COOK>` mention, no
      raw id, no fake channel; tests
      `::test_index_source_channel_is_workspace_memory_not_a_fake_channel`,
      `::test_match_from_offer_author_id_drives_a_real_mention` green.
- [x] PASS — 3 LLM context reflects the deduped list. Evidence: serialized post-merge context
      lists the collapsed cooker twin exactly once (1 numbered line);
      `::test_serialize_context_reflects_the_deduped_merged_list` routes through
      `route_message` and asserts one line.
- [x] PASS — 4 Unit tests for twin collapse / non-twin survival / display fields, zero
      warnings. Evidence: 259 unit passed, `filterwarnings=error`; the 016 test set above.
- [x] PASS — Cosmetic (`recall/blocks.py::_source_line`): "workspace memory" renders WITHOUT
      `#`, real channels keep `#`. Evidence: rendered `in workspace memory` vs `in #offers`
      / `in #general`; tests `::test_index_provenance_label_is_not_hash_prefixed`,
      `::test_real_channel_is_hash_prefixed` green. Import-inside-function avoids the
      matching↔recall load cycle (both packages import clean — verified).
- [ ] [HUMAN] — 5 Live re-run of the 006 cooker need test in the sandbox. Awaiting human
      verification (no live sandbox in this environment). The deterministic ts-identity rule
      means it no longer depends on phrasing staying close to the structured form.

**Sourcing guardrails on the merged card** — re-checked explicitly (CLAUDE.md product
requirement): source (`<@U_COOK>`), where (`#offers`), when (`2025-03-22 14:25 UTC`),
permalink (`View message` link), tappable `Contact: <@U_COOK>`, and the
`Verify before relying on this.` note — all present. Human-decides confirmation buttons
(Connect / Not relevant) intact on the merged card. Degraded RTS path stays explicit.
No safety assertion introduced.

**Evidence**
```
$ make pre-commit          → 259 passed in 1.09s  (format-check: 71 files formatted; lint: All checks passed!)
$ make integration-tests   → 5 passed, 1 skipped in 0.82s
$ make test (run 2)        → 264 passed, 1 skipped in 0.97s   (identical to run 1)

ts-identity (4 spellings)  → all IDENTICAL, delta 0.0 µs, is_twin True
cooker merge               → count 1, offer_id fde848c7-…, channel 'offers', permalink adopted
red-check (ts disabled)    → count 2 (proves ts rule load-bearing)
button trace               → ConnectPayload(offer_id=fde848c7-…) → mark_resolved → 'resolved'
```

**Other issues found**
- None blocking. Diff is scoped to the 6 expected files (3 source + 3 test) + the tracker;
  no stray files, no `git add -A` smell. No `print()` in library code. New functions fully
  type-annotated. `_merge_twin` correctly treats `RecallMatch` immutably via `model_copy`.

**VERDICT: PASS**
(AC5 is `[HUMAN]` — left unchecked, awaiting the human's live sandbox re-run; all
machine-verifiable criteria pass.)
