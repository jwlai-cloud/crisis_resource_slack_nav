# 017 — Coordinator Canvas: live case board + audit log

W4 anchor (design doc §5 "Coordinator oversight"; demo beat 1:45–2:10). A Slack
Canvas shows coordinators a live board of community cases by status, plus the audit
trail of every human-confirmed action. The Canvas is Slack-persisted, so it doubles
as the durable board — it survives an agent restart even though the in-memory index
does not (this is the W4 answer to the ADR-0003 persistence gap for the *board*; the
matching index stays in-memory for speed and is the fast path, the Canvas is the
record of truth coordinators read).

## Pre-work (SWE: research the Canvas API first)
Slack Canvas APIs are new. Before coding, verify via context7 / docs.slack.dev:
- `canvases.create` / `canvases.edit` (or `conversations.canvases.create` for a
  channel canvas) — exact method names, the markdown/section payload shape, whether
  a standalone canvas or a channel-tab canvas fits a coordinator board best.
- Which token: the manifest grants `canvases:read`/`canvases:write` as USER scopes —
  confirm the bot can write a canvas with the user token we already have
  (SLACK_USER_TOKEN), or whether a bot scope is needed (add to manifest + note the
  re-install).
Record findings in the task log before implementing. If the API can't support a
live-updating canvas the way the design assumes, write an ADR documenting the
fork and the fallback (e.g. a pinned Block Kit "board message" updated via
chat_update).

## Acceptance criteria
1. A `canvas/` (or `coordinator/`) module that builds and updates the board from
   existing state — `offer_index.all_offers()` grouped by `Status`
   (open / matched / resolved) + `audit_trail.list_events()` as a dated activity
   log. Pure board-composition functions are unit-testable without Slack.
2. The board is created once (idempotent — find-or-create, keyed by a stored canvas
   id or a known title) and updated on every button action (Connect / Mark resolved
   / Not relevant) so it stays live. Update is best-effort: a Canvas API failure
   logs and never breaks the button handler (degraded-state guardrail).
3. Every case row is sourced + timestamped (offerer, channel/origin, when) and every
   audit line carries actor + action + target + time — same sourcing guardrail as
   the cards.
4. The board never asserts safety and never shows an auto-action — it is a record of
   human-confirmed actions only (it reads from the audit trail, which only the
   buttons write).
5. A `make`/script entry-point or a slash trigger to (re)create the board on demand
   for the demo, plus auto-create on first relevant action. Document how a
   coordinator opens it.
6. Persistence note: on restart the in-memory index is empty but the Canvas still
   holds the last board; document that the board is the durable artifact and the
   index rehydration question (RTS reseed) is deferred / its own task if needed.
   Update ADR-0003's revisit note and/or add ADR-0005 (Canvas as durable board).
7. Tests: board composition (status grouping, sourcing on every row, empty state),
   Canvas client mocked (no live API in unit tests); integration test only if the
   FastMCP-style test client pattern applies. Zero warnings.
8. [HUMAN] live: trigger the board in the sandbox; perform a Connect + Mark resolved;
   confirm the Canvas reflects the case moving open → matched → resolved and the
   audit log gains the lines. (Demo beat 1:45–2:10.)

## Out of scope
Situation board / official-info section (task 012 — can be a second Canvas section
later). SQLite persistence of the index (separate decision if rehydration proves
needed). Escalate button (W4 follow-on).

## Log

### [SWE] 2026-06-13 — Canvas API research (pre-work, before coding)

**Installed SDK probe** (`uv run python` introspection on `slack_sdk` 3.42.0):
`WebClient` exposes `canvases_create`, `canvases_edit`, `canvases_delete`,
`conversations_canvases_create`, `canvases_sections_lookup`, `canvases_access_*`.
Signatures:
- `canvases_create(*, title=None, document_content: dict[str,str], **kwargs) -> SlackResponse`
- `canvases_edit(*, canvas_id: str, changes: Sequence[dict], **kwargs) -> SlackResponse`
- `canvases_delete(*, canvas_id: str, **kwargs)`

**Docs** (docs.slack.dev, fetched 2026-06-13):
- `canvases.create` (https://docs.slack.dev/reference/methods/canvases.create/):
  creates a **standalone canvas owned by the acting user**. Returns
  `{"ok": true, "canvas_id": "F..."}`. `document_content` shape is
  `{"type": "markdown", "markdown": "..."}`. **Scopes: `canvases:write` works on
  BOTH bot AND user token.** `channel_id` optional (required only on free teams).
- `canvases.edit` (https://docs.slack.dev/reference/methods/canvases.edit/):
  `changes` is an array of one op. Operations: `insert_after/before/at_start/at_end`,
  `replace`, `delete`, `rename`. **`replace` with NO `section_id` replaces the
  ENTIRE canvas** — exactly the find-or-update / full-recompose semantic we need.
  `document_content` works identically to create. Markdown supports headings h1-h3,
  bold, lists, dividers, tables, `:emoji:`, links, `@` mentions.

**API decision — live-updating standalone Canvas IS feasible (no fallback needed).**
- Method pair: `canvases_create(title=..., document_content={"type":"markdown","markdown":...})`
  once to mint the board → store the returned `canvas_id` in a process-local var →
  `canvases_edit(canvas_id=..., changes=[{"operation":"replace","document_content":{...}}])`
  on every button action to re-render the whole board from current state.
- **Token: `SLACK_USER_TOKEN`** (the manifest grants `canvases:read`/`canvases:write`
  as USER scopes, and the create call authors the canvas as the acting user — the
  coordinator). The user token is already plumbed via `agent.deps.resolve_user_token`
  / `SLACK_USER_TOKEN`. **No new bot scope, no re-install needed.**
- Payload shape: `document_content = {"type": "markdown", "markdown": "<board md>"}`.
- Because `canvases.edit` `replace` (no section_id) overwrites the full doc, the board
  composer is a pure `state -> markdown` function; no per-section diffing, no
  `sections.lookup`. Idempotent find-or-create: store the canvas id; if unset, create;
  else edit.

ADR-0005 (Canvas as durable board) is still written per AC 6 — it records the
durable-artifact decision (Canvas survives restart; in-memory index stays the fast
path; index rehydration deferred), NOT an API fallback. The design's live-updating
canvas assumption holds.

### [Tester] 2026-06-13 14:30 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` → "All checks passed!")
- Unit tests: 290 passed / 0 failed (incl. 11 board + 12 canvas + 4 open_board + 23 crisis_buttons)
- Integration tests: 5 passed / 1 skipped (live LLM — no provider key; expected)
- Warnings: 0 (`filterwarnings = ["error"]` active — a warning would have failed the run)
- Double-run / state-isolation: full suite run twice + coordinator/button subset twice, all green.
  No test references the `coordinator_board` module singleton without `patch`; lifecycle
  tests use a `fresh_board` (`CoordinatorBoard()`) fixture, so the process-local `canvas_id`
  does not leak between tests.

**E2E adversarial pass**
- Happy path (compose): `compose_board_markdown([offer], [event])` → board with title, verify
  note, Open/Connected/Resolved sections, sourced rows, audit lines. (PASS)
- Happy path (publish lifecycle): first `publish` → `canvases_create` (id stored); subsequent
  `publish` → `canvases_edit` replace, no duplicate create. (PASS)
- Happy path (script): `open_board.main()` with token + recreate→id → exit 0, recreate gets
  the resolved user token. (PASS)
- Break 1 (boundary: empty state): `compose_board_markdown([], [])` → all 3 status headings
  with `(0)` + `_No cases yet._` + `_No actions recorded yet._` + verify note. Coherent
  empty board (the post-restart case). (PASS)
- Break 2 (scale: 40 offers across 3 statuses + 200 audit events): renders, counts correct
  (Open 14 / Connected 13 / Resolved 13), 15,704 bytes. Well under Slack canvas doc limit
  (~1.5 MB); no truncation logic present — fine at demo scale, noted below as a follow-up.
  (PASS)
- Break 3 (degraded: `user_token=None`): `publish(client, None)` and `update_board(client, None)`
  → returns None, no `canvases_create`, no raise, logs "skipped: no user token". (PASS)
- Break 4 (degraded: `canvases_create` raises `SlackApiError`): swallowed, returns None, no
  id stored, logs "update failed (handler unaffected)". (PASS)
- Break 5 (degraded: `canvases_edit` raises `SlackApiError` on 2nd publish): swallowed,
  returns None, stored `canvas_id` retained for the next attempt. (PASS)
- Break 6 (concurrency: 50 threads race `publish` on a fresh board, create artificially
  slowed to widen the window): exactly 1 `canvases_create`, 49 `canvases_edit`, single
  `canvas_id`. Lock serialises the find-or-create read-modify-write — no duplicate canvas.
  10 reader threads × concurrent writers: 0 errors. (PASS)
- Break 7 (hostile: audit `target` containing "the road is safe to travel" + backticks):
  rendered verbatim inside a code span — it is recorded audit data of a human's action, not
  a board-composed safety assertion. The composer adds no safety claims. (PASS)

**Acceptance criteria**
- AC1 PASS — `coordinator/` module: `board.py` is a pure `state -> markdown` composer
  (imports only `datetime`, `entities`, `matching.audit` — grep confirms zero Slack/API refs),
  groups `offer_index.all_offers()` by `Status` + renders `audit_trail.list_events()`.
  Evidence: `coordinator/board.py:133` `compose_board_markdown`; `tests/unit/coordinator/test_board.py` (11 tests).
- AC2 PASS — idempotent find-or-create: first `publish` creates + stores id, later publishes
  edit via single full `replace` (no `section_id`); best-effort, never raises.
  Evidence: `coordinator/canvas.py:89-114`; idempotency probe (1 create / N edits) + degraded
  probes above; `test_canvas.py::test_second_publish_edits_existing_canvas_with_full_replace`,
  `::test_publish_swallows_create_failure_and_returns_none`, `::..._edit_failure...`.
- AC3 PASS — every case row carries offerer (`<@mention>`) + resource + location + post time;
  every audit line carries actor + verb + target + UTC time.
  Evidence: `board.py:74` `_case_row`, `board.py:106` `_activity_line`;
  `test_board.py::test_every_case_row_is_sourced_and_timestamped`,
  `::test_activity_lines_carry_actor_action_target_and_time`. NOTE: AC text says "channel/origin";
  the row sources offerer + timestamp but not a channel/origin field — the `Offer` entity has no
  channel field, so this is the maximal sourcing the state carries (see follow-ups).
- AC4 PASS — board never asserts safety, shows human-confirmed actions only. Reads the audit
  trail (written exclusively by the buttons; the agent never acts). No safety phrase composed
  (banned-phrase probe clean); standing verify note present.
  Evidence: `board.py:39` `VERIFY_NOTE`; `test_board.py::test_board_carries_verify_note_and_asserts_no_safety`.
- AC5 PASS — `scripts/open_board.py` + `make board` (re)create on demand; auto-create on
  first button action via `update_board`. `init_logger`-style bootstrap at module level before
  project imports; reads `SLACK_USER_TOKEN` via `resolve_user_token`; clear exit codes.
  Evidence: `scripts/open_board.py`; `Makefile` `board` target; CLAUDE.md command table updated;
  no-token run → exit 1 with actionable error; happy-path → exit 0;
  `tests/unit/scripts/test_open_board.py` (4 tests).
- AC6 PASS — ADR-0005 written (4-section Nygard, Accepted) documenting Canvas-as-durable-board,
  index stays fast path, id-not-durable + RTS-reseed rehydration explicitly deferred; ADR-0003
  revisit note updated to record the fired trigger answered without changing the decision.
  Evidence: `docs/adr/0005-canvas-as-durable-board.md`; `docs/adr/0003-...md` "Status note (2026-06-13, task 017)".
- AC7 PASS — board-composition tests (grouping, sourcing per row, empty state, newest-first,
  no-safety) + Canvas client fully mocked (no live API); 0 warnings. No integration test added —
  acceptable, the FastMCP test-client pattern does not apply to the Canvas REST surface and the
  publisher is fully covered by mocked-client unit tests.
  Evidence: `tests/unit/coordinator/` (23 tests); suite output 0 warnings.
- AC8 [HUMAN] — NOT RUN. Live sandbox: trigger board, Connect + Mark resolved, confirm the
  Canvas reflects open→matched→resolved and the audit log gains lines (demo beat 1:45–2:10).
  Awaiting human verification.

**Token / scope guardrail**
- Uses `SLACK_USER_TOKEN` via `resolve_user_token(context.user_token)`; per-call
  `Authorization: Bearer <user_token>` header override on the bot-token WebClient — the exact
  `recall.client` pattern. With no token → skipped + logged, never falls back to bot token.
- `manifest.json` UNCHANGED (clean in `git status`); `canvases:read`/`canvases:write` are USER
  scopes (in the `user` block, not `bot`). No new bot scope, no re-install. (PASS)

**010/008 regression**
- All 23 `test_crisis_buttons.py` tests pass. `update_board` is the LAST statement in all three
  handlers (`crisis_buttons.py:246, 280, 314`), after audit record + DM/post + card flip — so it
  sees post-action state and a board failure cannot undo the action. Malformed-payload path
  returns early (line ~184) before `update_board`, correctly (no state change → no refresh).
  Audit codes (`connect`/`resolve`/`not_relevant`) map exactly to board `_ACTION_LABELS`.
  Real-path isolation test (`test_board_hook_is_isolated_so_a_failure_never_breaks_connect`)
  exercises a failing `canvases_create` and confirms the intro still posts.

**Evidence**
```
$ make pre-commit
All checks passed!
... 290 passed in 3.01s
$ make integration-tests
... 5 passed, 1 skipped in 4.43s
$ uv run pytest tests/unit (x2)  -> 290 passed, 290 passed
```

**Other issues found** (PASS-with-note — non-blocking, orchestrator/PM to triage)
- Board write happens INSIDE the lock (canvas.py:104-110), so concurrent button presses
  serialise their Canvas API calls. Correct + safe for a single shared canvas; just means
  board refreshes are sequential under a click storm. Acceptable at demo scale; flagged for
  awareness, not a fix.
- No markdown size cap / truncation. A pathological audit trail (thousands of events) would
  grow the doc unbounded toward Slack's canvas limit. ADR-0005 already names incremental
  section edits as a future optimisation; a row/byte cap could be a small follow-on task.
- AC3 wording mentions "channel/origin" but the `Offer` entity carries no channel field, so
  rows source offerer + timestamp only. This matches the recall cards' available sourcing; if
  channel-of-origin is wanted on the board it needs an entity change — out of this task's scope.

**VERDICT: PASS**
(AC8 is [HUMAN] live verification — must be performed in the sandbox before the demo; not a
blocker for this code review.)
