# 025 — Board as the channel canvas (permanent top-bar tab)

UX, third iteration (user-driven): the board is a STANDALONE canvas, so it only
appears under "Files" and needs a bookmark (buried in the Bookmarks dropdown) or a
manual pin to reach. The native "always-visible top-bar tab" is a **channel canvas**.
Switch the board to the channel canvas of CRISIS_CHANNEL so it's a permanent tab —
no bookmark, no Files hunt, no manual add. Supersedes the 018 announce + 023 bookmark
as the discovery mechanism.

## Pre-work (SWE: research)
- `conversations_canvases_create(channel_id, document_content)` creates the channel's
  canvas (appears as a tab). Verify: what does it return (canvas_id)? Editing still
  uses `canvases_edit` (replace) — confirm.
- A channel has ONE canvas. Determine find-or-create: does conversations.info /
  conversations.canvases expose an existing channel-canvas id so we reattach instead
  of erroring on a second create? Check `conversations.info` (a `properties.canvas`
  field) or the create's behavior when one exists. The persisted canvas_id store
  (coordinator/canvas_store) still bridges processes; reattach to it first.
- Token/scope: confirm canvases:write (have it) covers channel-canvas create, or note
  any extra scope (+ re-install).

## Acceptance criteria
1. [x] The board is created as CRISIS_CHANNEL's channel canvas via
   conversations_canvases_create (find-or-create: reattach to the persisted/known
   channel-canvas id, else create). It appears as a permanent channel tab. — verified
   by `test_canvas.py::test_first_publish_creates_channel_canvas_with_markdown`,
   `test_discovers_existing_channel_canvas_via_conversations_info`,
   `test_first_publish_loads_persisted_id_and_edits_not_creates`,
   `test_create_race_recovers_via_discovery` (tab placement itself is the [HUMAN] AC).
2. [x] Updates still use canvases_edit replace (full re-render) — unchanged composer.
   — verified by `test_second_publish_edits_existing_canvas_with_full_replace`.
3. [x] The bookmark (023) becomes redundant — REMOVED from the create path; announce
   kept as a minimal one-time note; bookmarks:* scope + module left in place
   (harmless, documented in ADR-0005). — verified by
   `test_create_does_not_upsert_bookmark`.
4. [x] Best-effort + durable posture preserved: channel-canvas create/edit failures
   log and never break a button handler. — verified by
   `test_publish_swallows_create_failure_and_returns_none`,
   `test_publish_swallows_edit_failure_and_returns_none`,
   `test_conversations_info_failure_falls_through_to_create`,
   `test_update_board_helper_swallows_publish_failure`.
5. [x] Update ADR-0005 (now: channel canvas, not standalone) — superseding amendment
   added; 018/023 discovery mechanisms noted obsolete.
6. [x] Tests: channel-canvas create-vs-reattach, edit path unchanged, bookmark
   removal, best-effort. Existing coordinator tests updated. Zero warnings. — 34
   canvas tests + 401 unit suite green under filterwarnings=error.
7. [ ] [HUMAN] live: after make board, #exmouth-mutual-aid shows a "Community Cases"
   tab in the top bar (no manual add); clicking it opens the board in-app; buttons
   still update it. — NOT RUN (needs live sandbox + TTY; user runs `make board`).

## Out of scope
Resident-vs-coordinator canvas separation (the channel canvas is shared — fine for
the demo). Multi-channel boards.

## Log

### [SWE] 2026-06-13 — Pre-work research (channel-canvas API)

Verified against `slack_sdk` introspection (installed 3.42) and the live
`docs.slack.dev` reference pages (curl), not training data.

**`conversations.canvases.create`** — `WebClient.conversations_canvases_create(*, channel_id: str, document_content: Dict[str,str], **kwargs)` exists; posts to
`conversations.canvases.create`.
- Returns `{"ok": true, "canvas_id": "F1234ABCD"}` — same `canvas_id` key the
  standalone `canvases_create` returns, so the response handling is unchanged.
- On success Slack adds the channel-canvas tab (the docs: "the canvas icon in the
  upper right of the channel switch[es] to indicate that a channel canvas now
  exists") — this is the permanent top-bar tab the task wants. An empty
  `document_content` creates the canvas but does NOT flip the icon, so we always
  pass real markdown.
- A channel has exactly ONE canvas: calling create when one already exists returns
  `{"ok": false, "error": "channel_canvas_already_exists"}` (slack_sdk raises a
  `SlackApiError`). So create is NOT idempotent — we must find-or-create.

**Reattach / discovery** — `conversations.info` exposes the existing channel
canvas: the create reference says verbatim "You can find the ID of the canvas in
the `channel.properties.canvas` section in the response of a `conversations.info`
request." The canonical Slack shape of that block is
`properties.canvas = {"file_id": "F…", "is_empty": bool, "quip_thread_id": "…"}`.
The page's own sample response is an empty-properties channel so it does not inline
a populated block; I therefore read it defensively — prefer `file_id`, fall back to
`id`/`canvas_id` — so a subkey-name drift can't silently break reattach.

**Editing unchanged** — channel canvases are edited with the *same* `canvases_edit`
(replace op, no `section_id`) as standalone canvases; there is no
`conversations_canvases_edit`. So the whole-document replace composer is untouched.

**Scope** — `conversations.canvases.create` requires `canvases:write` (already
granted as a user scope; the standalone create used it too). No NEW scope. One extra
*membership* requirement, not a scope: the channel must be public, or the
app/user must be a member if private — no re-install needed. Access to a channel
canvas is tied to channel access (no canvas-share step), which is exactly why the
tab is the right native placement.

**Which channel id** — the board attaches to `CRISIS_CHANNEL` (a `C…` channel id),
read via the existing `listeners.channel_gate.designated_channel_id()` helper (not
a duplicated env read). The org/team id is NOT used for the create.

**Find-or-create design (implemented):**
1. Reattach to `canvas_store.load_canvas_id()` (the cross-process bridge) → `canvases_edit` it. Primary key.
2. Else discover the channel's existing canvas via `conversations.info`
   `channel.properties.canvas.file_id` → persist + `canvases_edit` it.
3. Else `conversations_canvases_create(channel_id=CRISIS_CHANNEL, …)` → persist the
   new id. If that races and returns `channel_canvas_already_exists`, fall back to
   the conversations.info discovery (step 2) so a concurrent create never crashes
   the board.
All best-effort: any failure logs and returns `None`; a button handler is never
broken (ADR-0005 degraded-state posture).

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `coordinator/canvas.py` — board is now the CRISIS_CHANNEL channel canvas. New
  find-or-create: `publish` loads the persisted id → else `_create_channel_canvas`
  discovers the channel's existing canvas via `conversations.info`
  (`properties.canvas.file_id`, with `id`/`canvas_id` fallbacks) and reattaches →
  else `conversations_canvases_create(channel_id=…)`; a `channel_canvas_already_exists`
  race re-discovers + reattaches. `recreate` deletes the old canvas then mints fresh
  via `_mint_channel_canvas` (no reattach). Bookmark upsert + `canvas_link` import
  REMOVED from the create path. Channel read via a module-level
  `designated_channel_id()` that lazily delegates to `listeners.channel_gate`
  (deferred import breaks the `listeners/__init__` ↔ `coordinator` cycle; patchable
  by name in tests). `BOARD_TITLE` import dropped (channel create takes no title;
  the title still appears inside the composed markdown). `_after_create` factors the
  persist + one-time announce shared by both create paths.
- `tests/unit/coordinator/test_canvas.py` — rewritten for the channel-canvas
  mechanism: create-on-channel, token override, edit unchanged, recreate (delete +
  fresh create), no-token/no-channel skips, best-effort swallow (create/edit/info),
  persisted-id reattach, conversations.info discovery, info-failure→create,
  create-race→discovery recovery, announce-once (create only, not on edit/reattach/
  discover), and `test_create_does_not_upsert_bookmark`.
- `tests/unit/coordinator/conftest.py` — dropped the obsolete
  `coordinator.canvas.upsert_board_bookmark` stub (no longer imported there).
- `docs/adr/0005-canvas-as-durable-board.md` — added a superseding "Amendment —
  channel canvas (task 025)" section: channel canvas as a permanent tab, find-or-
  create design, scope unchanged (`canvases:write` + channel membership), 018
  announce kept minimal / 023 bookmark obsoleted as discovery, restart reattach now
  solved (was deferred). Status header notes the amendment.
- `scripts/open_board.py` — docstring + success log updated (channel canvas / "the
  Community Cases tab in the top bar", find-or-create reuse semantics).

**What happened to bookmark / announce**
- **Bookmark (023):** REMOVED from the canvas create path — the permanent tab
  supersedes it. `coordinator/bookmark.py` + the `bookmarks:*` manifest scopes are
  LEFT in place (harmless, no runtime cost; ripping them out is unnecessary churn).
  `coordinator/__init__` still re-exports `upsert_board_bookmark`; the module's own
  tests still pass.
- **Announce (018):** KEPT as a minimal one-time "board tab is live" courtesy note,
  fired on a real create only (never on edit / reattach / discover). It is no longer
  the discovery mechanism (the tab is) — kept because it costs nothing.

**Signatures unchanged for callers** — `publish` / `update_board` / `recreate` still
take `(client, user_token, team_id=None, team_url=None)`; `CRISIS_CHANNEL` is read
internally. The three `crisis_buttons` handlers and `scripts/open_board.py` are
untouched.

**Tests**
- Unit: 401 passing, 0 failing (34 in `test_canvas.py`). Integration: N/A — no infra
  changes; the channel-canvas API is a live-only path (the [HUMAN] AC).
- Zero warnings (`filterwarnings = ["error"]`).

**End-to-end (mock-client drive, the live API is the [HUMAN] AC)**
- Create path: `publish` with no persisted id + empty `properties.canvas` →
  `conversations_canvases_create(channel_id="C_EXMOUTH", document_content=…, token=…)`
  called, `conversations.info` probed first, no bookmark touched.
- Discovery path: empty persisted id + `properties.canvas.file_id="F_PREEXISTING"` →
  reattaches + edits `F_PREEXISTING`, never creates.
- Edit path: second publish edits the held id.
- `import scripts.open_board; import coordinator; import listeners` → OK (no cycle).

**QA tail**
```
$ make format-check && make lint-check && make pre-commit
uv run ruff format --check
92 files already formatted
uv run ruff check
All checks passed!
...
============================= 401 passed in 2.18s ==============================
```

**Notes**
- AC7 [HUMAN] NOT RUN: live `make board` needs the sandbox + a TTY and the acting
  user must be a member of `CRISIS_CHANNEL` (channel-canvas requirement — public
  channel, or invited if private; no NEW scope, no re-install).
- The `properties.canvas` subkey is read defensively (`file_id` → `id` → `canvas_id`):
  the create reference names `properties.canvas` but its sample response is an
  empty-properties channel, so I could not pin the exact subkey from the page —
  `file_id` is Slack's canonical key, the fallbacks guard a drift.

### [Tester] 2026-06-13 14:50 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check`: 92 files formatted; `ruff check`: all passed; pre-commit suite 401 passed)
- Unit tests: 401 passed / 0 failed (34 in `test_canvas.py`)
- Integration tests: 5 passed / 1 skipped (no live provider key — expected) / 0 failed
- Warnings: 0 (`filterwarnings = ["error"]`)
- Double-run: stable — 401 passed both runs; `test_canvas.py` 34 passed twice. No singleton / canvas_store pollution.

**E2E adversarial pass** (mock-WebClient drive of the real `CoordinatorBoard`; live tab is AC7 [HUMAN])
- Happy path — create: `publish(client, user_token)` with no persisted id + empty `properties` → `conversations_canvases_create(channel_id="C_EXMOUTH", document_content={type:markdown}, token=user_token)`, no edit, returns the new id. (PASS)
- Happy path — discovery: `properties.canvas.file_id="F_PREEXISTING"` → reattaches + edits `F_PREEXISTING`, never creates. (PASS)
- Happy path — persisted-id: `load_canvas_id()="F_PERSISTED"` → edits it, `conversations.info` NOT probed, no create. (PASS)
- Break 1 (state edge — create race): `conversations_canvases_create` raises `channel_canvas_already_exists` → re-discovers via `conversations.info` and reattaches to `F_WON`, no crash, no dup. (PASS)
- Break 2 (failure mode — CRISIS_CHANNEL unset): `designated_channel_id()=None` → create skipped, returns `None`, logs "No CRISIS_CHANNEL configured … (handler unaffected)", no crash. (PASS)
- Break 3 (malformed input — `conversations.info` shapes): `properties` missing / `canvas=None` / `canvas={}` / `file_id=""` / no `channel` key → defensive read returns `None` → falls through to create; `id` / `canvas_id` alt keys → reattach. Every shape coherent, no exception. (PASS)
- Break 4 (state edge — button-handler update path): `update_board` create then 2× update on the held in-process id → 1 create, 2 edits, `conversations.info` probed only once (at create). Subsequent updates edit via the held id, never re-discover. (PASS)
- Break 5 (state edge — stale/deleted persisted id): `load_canvas_id()="F_STALE"` + `canvases_edit` raises `canvas_not_found` → degrades to `None`, never crashes; does NOT self-heal (re-load returns same stale id, edit fails again until the store is cleared). Honest note below — acceptable, not a regression.

**Acceptance criteria**
- [x] PASS — AC1 board created as CRISIS_CHANNEL channel canvas via `conversations_canvases_create`, find-or-create (persisted-id → conversations.info discovery → create). Evidence: `test_first_publish_creates_channel_canvas_with_markdown`, `test_discovers_existing_channel_canvas_via_conversations_info`, `test_first_publish_loads_persisted_id_and_edits_not_creates`, `test_create_race_recovers_via_discovery` all pass; create uses `channel_id=designated_channel_id()` (canvas.py:324,338,376,381 — single delegate, no duplicated env read) with `token=user_token` override (canvas.py:341). Tab placement is AC7 [HUMAN].
- [x] PASS — AC2 updates use `canvases_edit` replace, no `section_id`, whole-document recompose via `_compose_with_names` (names + situation still threaded). Evidence: `test_second_publish_edits_existing_canvas_with_full_replace`, `test_publish_resolves_names_and_threads_them_into_the_board`, `test_publish_reads_situation_and_threads_it_into_the_board`; `_replace` at canvas.py:442.
- [x] PASS — AC3 bookmark removed from create path; announce kept minimal (create-only). Evidence: `test_create_does_not_upsert_bookmark`, `test_edit_does_not_announce`, `test_reattached_id_does_not_announce`, `test_discovered_canvas_does_not_announce`; diff removes `upsert_board_bookmark` + `canvas_link` imports and the bookmark try-block; grep confirms no `upsert_board_bookmark`/`canvas_link`/standalone `canvases_create` in canvas.py. `coordinator/bookmark.py` + `bookmarks:*` manifest scopes left in place (manifest.json:44,46,61,62), `__init__` still re-exports `upsert_board_bookmark` — its own tests still pass (test_bookmark.py 10 passed).
- [x] PASS — AC4 best-effort: create/edit/conversations.info failures logged + swallowed, return None, never break a handler. Evidence: `test_publish_swallows_create_failure_and_returns_none`, `test_publish_swallows_edit_failure_and_returns_none`, `test_conversations_info_failure_falls_through_to_create`, `test_update_board_helper_swallows_publish_failure`, `test_publish_swallows_missing_canvas_id_in_response`, `test_announce_failure_does_not_break_publish`; reproduced live in adversarial breaks 2 & 5. `publish`/`update_board`/`recreate` signatures unchanged (canvas.py:187,240,462) — callers `crisis_buttons.py:246,280,314` and `recall_reply.py:130` use `update_board(client, user_token, team_id)`, stable.
- [x] PASS — AC5 ADR-0005 amended coherently. Evidence: docs/adr/0005 "Amendment — channel canvas (task 025)" section present (lines 117-173): channel canvas as permanent tab, find-or-create order, scope unchanged + membership, 018 announce kept minimal / 023 bookmark obsoleted as discovery, restart-reattach now solved (supersedes the deferred consequence), best-effort posture preserved. Status header notes the amendment (line 5).
- [x] PASS — AC6 tests cover create-vs-reattach, edit unchanged, bookmark removal, best-effort; existing coordinator tests updated; zero warnings. Evidence: 34 canvas tests + 401 unit suite green under `filterwarnings=error`, double-run stable. conftest dropped the obsolete `upsert_board_bookmark` stub.
- [ ] AC7 [HUMAN] — Awaiting human verification. NOT RUN: live tab appears in #exmouth-mutual-aid top bar / opens in-app / buttons update it. Needs live sandbox + TTY (`make board`); the acting user MUST be a member of CRISIS_CHANNEL (public channel, or invited if private — channel-canvas access requirement; no new scope, no re-install).

**Extra verifications requested**
- recreate deletes old THEN mints fresh (no reattach): `test_recreate_drops_id_and_creates_fresh_channel_canvas` + `test_recreate_still_creates_even_with_persisted_id` — `canvases_delete(canvas_id=old, token=user_token)` then `_mint_channel_canvas` (no load, no discovery), `canvases_edit` not called. PASS.
- No new manifest scope: `canvases:write` already present (manifest.json:43); `bookmarks:*` left harmless. PASS.
- Import cycle: `import scripts.open_board; import coordinator; import listeners` → OK (deferred `designated_channel_id` import breaks the listeners↔coordinator cycle). PASS.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
92 files already formatted
uv run ruff check
All checks passed!
============================= 401 passed in 1.81s ==============================

$ make integration-tests
========================= 5 passed, 1 skipped in 0.89s =========================

$ make unit-tests  (run 1) ... 401 passed in 1.59s
$ make unit-tests  (run 2) ... 401 passed in 1.69s   # double-run, no pollution
```

**Other issues found** (non-blocking)
- Stale-but-present persisted id (canvas deleted out from under the agent) does NOT self-heal: edit fails → degrades to None on every subsequent publish until the persisted store is cleared (re-discovery fires only on the create path / `channel_canvas_already_exists`, not on an edit failure). This is consistent with the find-or-create design as written and the ADR's restart-reattach claim (which covers a *lost id file*, not a *stale id*), and it never crashes a button handler — acceptable degraded state, not a regression. Worth a follow-up only if deleted-canvas recovery becomes a demo need.

**VERDICT: PASS** (AC1–AC6 verified with evidence; AC7 [HUMAN] awaiting live verification — note the make-board user must be a CRISIS_CHANNEL member.)
