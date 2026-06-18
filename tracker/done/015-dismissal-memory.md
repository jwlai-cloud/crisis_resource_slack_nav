# 015 — Per-user dismissal memory

Live finding (2026-06-12): "Not relevant" rewrites only the clicked card; a new
need re-queries RTS and resurfaces the same match with fresh buttons. The old
copy promised "I won't surface this match again" — softened to "Dismissed for
this request" (accurate) pending this task.

Direction: in-memory dismissal store keyed (user_id, match identity: offer_id or
permalink or text-hash), consulted in the recall filter for that user's needs.
Same persistence posture as the offer index (process-lifetime; W4 persistence
decision covers both). Audit already records the dismiss signal — reuse it as
the store if convenient. Pairs with 014 (need-echo filter), which removes the
echo case observed here.

## Log

### [SWE] 2026-06-12 — Implementation

**Design decisions**
- **Dedicated store, not the audit trail.** New `recall/dismissals.py` with a
  `DismissalStore` singleton (`dismissal_store`) holding a `set[(user_id, identity)]`.
  The task allowed reusing the audit trail "if convenient" — a dedicated set is cleaner:
  membership lookup is the operation we need, and the audit trail is an append-only
  event list with a different shape and purpose (rank-tuning signal vs. live filter).
- **Identity scheme:** `match_identity(offer_id, permalink, text)` — `offer_id` if present,
  else `permalink`, else a SHA-256 hash of whitespace-collapsed/lowercased text. Each is
  prefixed (`offer:` / `link:` / `text:`) so two handles can never collide. `identity_of(match)`
  applies the same scheme to a `RecallMatch` so the write side (button payload) and read
  side (recall result) agree.
- **Persistence posture:** plain in-process set, dies with the process — the *same* posture
  as the matching index (ADR-0003) and audit trail, documented in the module docstring; W4
  persistence decision covers all three together. Thread-safe (lock), since handlers run on
  Bolt's thread pool.
- **Per-user filter location:** `_merge_recall_results` calls
  `dismissal_store.filter_dismissed(requester_id, ...)` on the combined index+RTS matches
  before ranking. `requester_id` is threaded from `route_message`'s existing `author` arg.
  Filter is keyed to the dismissing user only — user A's dismissal never hides a match from B.

**Files modified**
- `recall/dismissals.py` — new: `DismissalStore`, `match_identity`, `identity_of`, singleton.
- `listeners/actions/crisis_buttons.py` — `handle_crisis_not_relevant` writes the
  `(clicker, identity)` dismissal after auditing.
- `listeners/recall_reply.py` — `_merge_recall_results` filters dismissed matches per-user;
  `route_message` passes `requester_id=author`.
- `tests/unit/recall/test_dismissals.py` — new: identity priority, round-trip, per-user isolation, filter order.
- `tests/unit/listeners/test_recall_reply.py` — route-level: dismissed match filtered for that
  requester; per-user isolation (U_B still sees it).
- `tests/unit/listeners/actions/test_crisis_buttons.py` — `not_relevant` writes the dismissal,
  keyed to the clicker only.

**Acceptance criteria**
- [x] Process-lifetime store keyed (user_id, identity = offer_id|permalink|text-hash) — `test_dismissals.py`.
- [x] `crisis_not_relevant` writes it — `test_not_relevant_records_dismissal_for_the_clicker`.
- [x] Recall path filters dismissed matches out for that user's needs — `test_need_filters_out_a_match_this_requester_dismissed`.
- [x] Per-user isolation (A's dismissal doesn't hide it from B) — `test_dismissal_is_per_user_*` (store + route).
- [x] Same persistence posture as offer index, documented — module docstring.

**Evidence**
```
$ make pre-commit
... 228 passed in 1.17s ...
$ uv run python (e2e) — U_A dismisses -> U_A sees [], U_B sees [match]
INFO recall.dismissals: Dismissal recorded for U_A on link:https://x/offer (1 total)
```

**Notes**
- Identity from the button payload uses the (truncated, <=280-char) `snippet` for the
  text-hash fallback; offer_id/permalink (present for index and RTS hits) are the normal
  paths, so the text-hash fallback is the rare case where neither id nor link exists.
- Pairs with 014 (need-echo filter), which removes the echo case originally observed here.

### [Tester] 2026-06-12 15:40 — QA

**Test summary**
- Format / lint / pre-commit: PASS
- Unit tests: 228 passed / 0 failed
- Integration tests: 5 passed / 0 failed / 1 skipped (live LLM)
- Warnings: 0
- Double-run: full unit suite twice → identical 228 passed; new `DismissalStore` singleton is patched per-test (`_patch_dismissals` in test_crisis_buttons; fresh `DismissalStore()` in test_recall_reply/test_dismissals) — no cross-test leakage observed.

**E2E adversarial pass**
- Happy path: end-to-end dismiss-then-recall via the normal RTS (permalink) tier — built a button `ConnectPayload` from a real `RecallMatch`, ran `to_value()/from_value()`, dismissed, then `filter_dismissed` on the same match → hidden; a different user still sees it (PASS)
- Break path 1 (state: restart simulation): dismiss in one store, then a fresh `DismissalStore()` (simulating process restart) → match RETURNS (PASS — documented W4/ADR-0003 in-memory posture, deliberate)
- Break path 2 (perf: 1000 dismissals): 1000 dismiss writes = 2.9 ms; filter 1000 matches against the store = 0.2 ms (per-user set pre-built, O(n) membership — no quadratic blowup) (PASS)
- Break path 3 (unicode/emoji text-hash stability): emoji 💧🔋, accents (café/résumé), CJK (提供 发电机) — all hash stably across whitespace+case; `identity_of` of a unicode text-hash match doesn't crash (PASS)

**Acceptance criteria**
- [x] PASS — process-lifetime store keyed `(user_id, identity = offer_id|permalink|text-hash)` — `recall/dismissals.py:36-100`; in-process `set[tuple[str,str]]`, lock-guarded; `test_dismissals.py` (13 tests)
- [x] PASS — `crisis_not_relevant` writes it — `crisis_buttons.py:288-291` writes `(actor, match_identity(...))` after audit; `test_not_relevant_records_dismissal_for_the_clicker`
- [x] PASS — recall path filters dismissed matches for that user's needs — `recall_reply.py:106,110` `dismissal_store.filter_dismissed(requester_id, ...)` before ranking (both the index-only and combined branches); `test_need_filters_out_a_match_this_requester_dismissed`
- [x] PASS — per-user isolation (A's dismissal doesn't hide it from B) — `filter_dismissed` keys on the dismissing user only; probed at store + route level; `test_user_a_dismissal_does_not_hide_match_from_user_b`, `test_dismissal_is_per_user_other_requester_still_sees_match`
- [x] PASS — same persistence posture as offer index, documented — module docstring (`dismissals.py:20-24`) cites ADR-0003; restart sim confirms it dies with the process

**Identity round-trip (probed directly, as required)**
- Precedence offer_id > permalink > text-hash — `match_identity` short-circuits in that order (`dismissals.py:45-51`); prefixes (`offer:`/`link:`/`text:`) prevent cross-tier collisions; verified `test_identity_prefers_offer_id`, `test_different_handles_never_collide`
- Write side (button `ConnectPayload` → `match_identity`) vs read side (`identity_of(RecallMatch)`) — **MATCH for Tier 1 (offer_id) and Tier 2 (permalink)**, the two normal paths; Tier 3 (text-hash) matches for short text.

**Evidence**
```
$ make unit-tests -> 228 passed in 1.34s
$ round-trip probe ->
  TIER 1 offer_id:  write='offer:uuid-123'  read='offer:uuid-123'  MATCH=True
  TIER 2 permalink: write='link:https://x/rts' read='link:https://x/rts' MATCH=True
  TIER 3 short:     write==read  MATCH=True
$ end-to-end (permalink): dismiss via button -> hidden on recall=True; per-user U_OTHER still sees=True
$ perf: 1000 writes=2.9ms, filter 1000=0.2ms
```

**Other issues found (honest divergences — narrow, NOT FAIL-grade)**
1. **Text-hash (Tier 3) write/read divergence when text > 280 chars.** The button payload truncates `snippet` to 280 chars (`payload.py:35`), so the write-side hash is over the truncated text while the read-side `identity_of` hashes the FULL `match.text`. Probed: 800-char text → write hash `46ea...` ≠ read hash `ab1f...` → such a match could not be hidden after dismissal. **Real-world reach is narrow**: it only bites a match that is RTS-only (no offer_id) AND has no permalink AND text > 280 chars. Index hits always carry offer_id (Tier 1); RTS hits normally carry a permalink (Tier 2). So Tier 3 is the documented rare fallback and the divergence only matters in the corner of a corner. The AC ("offer_id|permalink|text-hash priority") is met as written; flagging for SWE awareness — a cheap hardening would be to hash a consistently-truncated text on both sides.
2. **Index hit and its RTS twin do NOT share identity** (probed as required). The same workspace message surfacing as an index hit (`offer:uuid-abc`) and an RTS hit (`link:https://x/msg1`) yields divergent identities, so dismissing one does not hide the other. This is **inherent to the architecture**: `match_from_offer` deliberately sets `permalink=""` ("an index hit links to no single workspace message", `matching/conversion.py:31-44`), and the in-memory index and RTS have no shared key. The two sources are complementary (parsed offer vs raw workspace message) rather than duplicative, and the spec did not require cross-source identity unification. Recorded honestly per the QA brief; not a regression and not a FAIL.

**VERDICT: PASS**
