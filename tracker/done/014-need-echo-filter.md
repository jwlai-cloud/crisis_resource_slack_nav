# 014 — Filter need-shaped echoes from recall matches

Live W3 verification (2026-06-12): the requester's own earlier need message
("Family of 4... need water and a generator", posted plain in #general) surfaced
as MATCH 1 — it's a near-perfect keyword match but it's a need, not an offer.

Fix direction: at recall time we hold the current message text — drop RTS matches
whose token set is a near-duplicate (Jaccard >= ~0.85) of the current request.
Cheap, no LLM call. Note the deeper limitation honestly: distinguishing arbitrary
needs from offers in RTS results would need per-result classification (costly);
near-duplicate filtering covers the observed failure mode.

Also note: resolved offers reappearing after a server restart is the ADR-0003
persistence gap (W4 decision), NOT this task.

## Log

### [SWE] 2026-06-12 — Implementation

**Design decisions**
- **Filter location:** `_drop_need_echoes(matches, request_text)` in `recall/client.py`,
  alongside `_drop_agent_noise`, run inside `recall_offers` *after* noise filtering and
  *before* the result is returned for ranking. Co-located with the other RTS noise
  filters so all "drop this RTS hit" logic lives in one place. The current message text
  is threaded in via a new `request_text` param on `recall_offers`, populated by
  `route_message` (which already holds `text`) — no listener signature change.
- **Similarity:** Jaccard over `tokenize()` sets (the same tokeniser RTS ranking and the
  offer index use), threshold `>= 0.85` (`_ECHO_JACCARD_THRESHOLD`). Cheap, no LLM call.
- **Honest limitation** (in code docstring + threshold comment): this kills *echoes* of
  the current request, not arbitrary foreign needs — distinguishing an unrelated need
  from an offer would need per-result classification (an LLM call per hit, costly).

**Files modified**
- `recall/client.py` — `_drop_need_echoes`; threaded `request_text` into `recall_offers`.
- `listeners/recall_reply.py` — `route_message` passes `request_text=text` to `recall_offers`.
- `tests/unit/recall/test_echo_filter.py` — new: echo dropped at/above 0.85, near-miss
  kept below threshold, boundary cases (6/7 drops, 4/6 kept), empty-request passthrough.
- `tests/unit/recall/test_client.py` — `test_recall_drops_need_echo_when_request_text_passed`.

**Acceptance criteria**
- [x] RTS matches near-duplicate (Jaccard >= 0.85) of current request dropped — `test_echo_filter.py`.
- [x] Near-miss below threshold kept (honest scope) — `test_near_miss_below_threshold_is_kept`.
- [x] Request text threaded from `route_message` into `recall_offers` — wired + e2e verified.

**Evidence**
```
$ make pre-commit
... 228 passed in 1.17s ...
$ uv run python (e2e) — request "...need water and a generator" -> echo dropped, offer kept
$ recall_offers e2e -> RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1
```

**Notes**
- ADR-0003 persistence gap (resolved offers reappearing after restart) is out of scope
  per the task — untouched, W4.

### [Tester] 2026-06-12 15:40 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check`: 68 files formatted; `ruff check`: all passed)
- Unit tests: 228 passed / 0 failed
- Integration tests: 5 passed / 0 failed / 1 skipped (live LLM, no provider key — legitimate)
- Warnings: 0 (`filterwarnings = ["error"]` in effect)
- Double-run: full unit suite run twice back-to-back — 228 passed both times, identical (no singleton state pollution).

**E2E adversarial pass**
- Happy path: live `recall_offers()` with the exact 014 failure scenario (requester's own need + a real offer in the RTS results) → `INFO recall.client: RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1`; echo dropped, offer "I have a spare generator to lend in town" kept (PASS)
- Break path 1 (boundary: Jaccard probe): exact echo Jaccard=1.0 → dropped; 6/7=0.857 → dropped; 5/7=0.625 → kept; **exact 0.85 → dropped** (>= is inclusive, confirmed) (PASS)
- Break path 2 (CRITICAL — legit offer phrased close to the need): "Offering: water and a generator for family in North Exmouth" vs need "...water and a generator for family in North Exmouth" → Jaccard=**0.8333**, margin **0.0167** below threshold → **SURVIVES** (the distinguishing token "offering" tips it below 0.85) (PASS)
- Break path 3 (boundary: empty/whitespace/punct-only/stopword-only request_text): "", "   ", "\t\n", "!!! ???", "the a of to" → all produce empty token sets → filter no-ops, every match kept (PASS)

**Acceptance criteria**
- [x] PASS — RTS matches near-duplicate (Jaccard >= 0.85) of current request dropped — `recall/client.py:177` (`>= _ECHO_JACCARD_THRESHOLD`); probed exact 0.85 boundary drops; `test_echo_filter.py::test_threshold_boundary_at_0_85_drops`
- [x] PASS — near-miss below threshold kept (honest scope) — probed 0.625 and 0.8333 both kept; `test_near_miss_below_threshold_is_kept`
- [x] PASS — request_text threaded from BOTH listener paths into `recall_offers` — `recall_reply.py:206` passes `request_text=text`; `events/message.py:71` passes raw `text`, `events/app_mentioned.py:61` passes `cleaned_text` (mention-stripped) — both correct for their context; live e2e exercised it

**Evidence**
```
$ make pre-commit -> 228 passed in 1.25s; ruff format/check clean
$ uv run python (live recall_offers) ->
  INFO recall.client: RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1
  post-filter texts: ['I have a spare generator to lend in town']  (echo dropped, offer kept)
$ Jaccard probe -> exact-echo:1.0(drop)  legit-offer:0.8333(keep,margin 0.0167)  0.85:drop  6/7:drop  5/7:keep
```

**Other issues found**
- Honest-limitation edge (already documented by SWE in code + spec, NOT a defect): a *terse* offer whose content tokens are identical to the need (e.g. an offer posted as bare "water, generator, exmouth" with no verb) has Jaccard 1.0 and WOULD be dropped as an echo. Real offers carry a verb ("have"/"offering"/"spare"/"lend") that drops Jaccard below 0.85 (probed: "have water generator spare" vs "water generator" = 0.5, kept). The legit-offer margin is thin (one distinguishing token) but holds for realistic phrasings. Within the documented scope of near-duplicate filtering; flagging for awareness only.

**VERDICT: PASS**
