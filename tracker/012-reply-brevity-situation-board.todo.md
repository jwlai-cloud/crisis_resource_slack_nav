# 012 — Reply brevity + shared situation board

User feedback (2026-06-12, after 009 live test): the need reply dumped the full official picture (roads + water + evac) at one user — too long, and the general MCP content is identical for everyone in the same time frame.

## Direction

1. **Relevance pruning (prompt + compose):** a need reply includes only official items directly relevant to the parsed need — water need → water point; explicit travel/road mention → that closure; shelter need → evac centres. Hard cap (~2-3 official lines). Anchor-test the prompt rule.
2. **Shared situation board:** the general official picture lives in ONE shared artifact — fold into W4's coordinator Canvas as a "situation board" section (roads / water / evac / advice, each feed-stamped with fetched-at), refreshed on demand or per significant change. Individual replies end with a one-line pointer ("Full road and evac status: situation board, updated HH:MM UTC") instead of repeating it.
3. Threading stays as-is: channel replies in-thread (already true), DMs linear.

Groom with W4 (Canvas task) — the board is the Canvas's first concrete content.

## Log

Addendum (2026-06-12, token-cost review): serialize_recall_context sends ALL ranked
matches with untruncated text to the LLM while blocks render top 5 — cap the context
at the same 5 and truncate snippets (~200 chars). Also add an RTS observability log
line (query latency + pre/post-filter counts) alongside the W4 audit work.

### [SWE] 2026-06-12 — Implementation (PARTIAL: addendum cap item only)

**Scope of this entry.** ONLY the Log addendum (LLM context cap + snippet truncation +
RTS observability log line). The relevance-pruning prompt rule (Direction §1) and the
shared situation board / Canvas (Direction §2) remain UNTOUCHED — they groom with W4 as
the task says. This file stays `.todo.md` for that remaining scope.

**Design decisions**
- **Context cap:** `serialize_recall_context` now slices to the top `_CONTEXT_MAX_MATCHES = 5`
  — the same top-N the Block Kit reply renders — so the LLM never receives matches it can't
  surface. Header line reworded "N shown" (was "N found").
- **Snippet truncation:** `_truncate_snippet` trims each snippet to `_CONTEXT_SNIPPET_MAX = 200`
  chars, appending an ellipsis when truncated; short snippets pass through unchanged.
- **(+N more found):** when the ranked result exceeds the cap, a trailing `(+N more found)`
  line is appended so the model knows the list is a head, not the whole.
- **Observability:** ONE `logger.info` line in `recall_offers` — `query`, `latency` (ms,
  `time.monotonic` around the RTS call), `raw` count (pre-filter), `post_filter` count.

**Files modified**
- `listeners/recall_reply.py` — cap + `_truncate_snippet` + `(+N more found)` in `serialize_recall_context`.
- `recall/client.py` — `time` import + observability `logger.info` line in `recall_offers`.
- `tests/unit/listeners/test_recall_reply.py` — cap at 5, `(+N more found)`, no-line within cap,
  long-snippet truncation, short-snippet intact.
- `tests/unit/recall/test_client.py` — `test_recall_logs_observability_line`.

**Acceptance criteria (addendum item)**
- [x] Context caps at the same 5 matches the blocks render — `test_serialize_recall_context_caps_at_five_matches`.
- [x] Each snippet truncated to ~200 chars — `test_serialize_recall_context_truncates_long_snippets`.
- [x] `(+N more found)` appended when truncated — `test_serialize_recall_context_appends_plus_n_more_when_truncated`.
- [x] ONE RTS observability log line (query, latency ms, raw, post-filter) — `test_recall_logs_observability_line`.
- [ ] Direction §1 relevance-pruning prompt rule — NOT IN SCOPE this round (W4).
- [ ] Direction §2 shared situation board / Canvas — NOT IN SCOPE this round (W4).

**Evidence**
```
$ make pre-commit
... 228 passed in 1.17s ...
$ recall_offers e2e -> INFO recall.client: RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1
$ serialize_recall_context(8 matches) -> "5 prior offer(s) shown..." + "(+3 more found)" + truncated snippets
```

**Notes**
- File intentionally left `.todo.md`: the situation-board scope is the bulk of this task and
  stays for the W4 Canvas grooming. This entry closes only the token-cost addendum.

### [Tester] 2026-06-12 15:40 — QA (addendum cap item only)

Scope of this verdict: ONLY the Log addendum (LLM context cap + snippet truncation + RTS observability log line). Direction §1 (relevance-pruning prompt) and §2 (situation board / Canvas) remain out of scope (W4) — not tested, file stays `.todo.md`.

**Test summary**: pre-commit PASS; unit 228 passed / 0 failed / 0 warnings; integration 5 passed / 1 skipped.

**Acceptance criteria (addendum item)**
- [x] PASS — context caps at the same 5 matches the blocks render — `recall_reply.py:137` (`result[:_CONTEXT_MAX_MATCHES]`, =5); probed: 8 matches → exactly 5 numbered lines; slicing does NOT mutate the input list, so the blocks still render their own top-N independently; `test_serialize_recall_context_caps_at_five_matches`
- [x] PASS — each snippet truncated to ~200 chars — `_truncate_snippet` (`recall_reply.py:153`, `_CONTEXT_SNIPPET_MAX=200`); probed: 150-char snippet untouched/no ellipsis; 500-char → 201 chars ending in "…" (body exactly 200); `test_serialize_recall_context_truncates_long_snippets`
- [x] PASS — `(+N more found)` appended when truncated — `recall_reply.py:147-149`; probed: 8 matches → "(+3 more found)"; within cap → no line; `test_serialize_recall_context_appends_plus_n_more_when_truncated`
- [x] PASS — ONE RTS observability log line (query, latency ms, raw, post-filter) — `recall/client.py:114-120`; verified LIVE: `INFO recall.client: RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1` (all four fields present, fires in normal operation); `test_recall_logs_observability_line`
- [ ] Direction §1 relevance-pruning prompt rule — NOT IN SCOPE this round (W4), not tested
- [ ] Direction §2 shared situation board / Canvas — NOT IN SCOPE this round (W4), not tested

**Evidence**
```
$ serialize_recall_context(8 matches) -> 5 numbered lines + "(+3 more found)"; input list len unchanged (slice, not mutate)
$ _truncate_snippet: 150->150 (no ellipsis); 500->201 (ends "…", body=200)
$ live recall_offers -> INFO recall.client: RTS recall: query='generator Exmouth' latency=1ms raw=2 post_filter=1
```

**VERDICT (addendum cap item): PASS** — remaining §1/§2 scope stays open for W4.
