# 023 — Persistent quick link to the coordinator board

UX problem (user-observed): the board link is only in a channel message that scrolls
away, and the slack.com/docs/... URL unfurls into an ugly generic "Slack Login"
card. Coordinators need an always-visible quick link.

## Direction
1. **Channel bookmark** (the persistent quick link): on board create/recreate, add or
   update a bookmark in CRISIS_CHANNEL pointing at the board canvas — the bookmark
   bar sits at the top of the channel, one click, never scrolls. Use bookmarks_add /
   bookmarks_edit (slack_sdk has them); add `bookmarks:write` to the manifest (note
   the re-install). Idempotent: update the existing "Community Cases board" bookmark
   rather than adding duplicates (bookmarks_list to find it). Best-effort — a
   bookmark failure never breaks the board create (mirror the announce posture).
2. **Suppress the announce unfurl**: the announce chat_postMessage should pass
   unfurl_links=False, unfurl_media=False so it stops rendering the login card.
3. **Verify the canvas URL form** for this enterprise org: the slack.com/docs/{team}/
   {canvas} link unfurled to a login card — confirm the URL that actually opens the
   canvas for a member (canvases_create response may carry a URL; or construct from
   the team domain crisis-resource-nav.enterprise.slack.com). Use the working URL for
   both the bookmark and the announce link.
4. (App Home board link is task 022 — complementary, also persistent.)

## Acceptance criteria
1. [x] bookmarks:write scope added; on board create/recreate a single "Community Cases
   board" channel bookmark is added/updated (no duplicates on re-run), best-effort.
2. [x] Announce no longer unfurls (no login card); the link form is the one that opens
   the canvas for members.
3. [x] Tests: bookmark add-vs-update logic (mocked bookmarks_list/add/edit), unfurl flags
   on the announce call, URL construction. Zero warnings.
4. [ ] [HUMAN] live: after make board, #exmouth-mutual-aid shows a top-bar bookmark that
   opens the board; the announce message has no login-card unfurl. — NOT RUN (needs a
   live `slack run` re-install to apply the new scope; manual verification).

## Out of scope
Making the board a channel-tab canvas (a larger redesign of 017's standalone-canvas
approach; revisit only if bookmarks prove insufficient).

## Log

### [SWE] 2026-06-13 14:55 — Implementation

**Canvas-URL finding**
- `canvases.create` returns only `{"ok": true, "canvas_id": "F..."}` — **no** `url`/
  `permalink` field (the existing test mock already reflects this). There is no
  response URL to prefer; the link must be constructed.
- Kept the `https://slack.com/docs/{team}/{canvas}` form. That form *opens* for a
  logged-in member who clicks it; the only problem was the **unfurl** — Slack's
  link-preview crawler is unauthenticated, can't see the canvas, and fell back to
  the generic "Slack Login" card. AC #2's real fix is suppressing the unfurl, not
  changing the URL. So both the bookmark and the announce use this same form, and
  the announce now passes `unfurl_links=False, unfurl_media=False`. (The enterprise
  team-domain form `crisis-resource-nav.enterprise.slack.com/docs/...` is an
  alternative if a member ever finds the slack.com/docs form doesn't open — that's
  the [HUMAN] live check; if it fails, swap the one constant in `announce.canvas_link`.)

**Bookmark auth choice**
- `slack_sdk` exposes `bookmarks_add` / `bookmarks_list` / `bookmarks_edit`
  (verified signatures); all accept a `token=` override that flows through
  `api_call` → token resolution (the same first-class mechanism the canvas write
  uses — NOT a manual `Authorization` header).
- The bookmark write forwards the **user token** via `token=` when given, falling
  back to the client's own (bot) token otherwise. Reason: the demo entry point is
  `make board` (a standalone script process that carries **only** the user token —
  `slack run` injects the bot token into the agent, not the script). The live agent
  reattaches to the persisted canvas id and never re-hits `_create`, so the bookmark
  must be addable from the script path → it must authenticate as the user. The agent
  path (a button-triggered first create) still works via the bot token fallback.
- `bookmarks:write` added to **both** bot and user scopes in `manifest.json` (AC #1
  names bot scope — bot is the natural channel-bookmark owner; user scope is what
  the script path actually authenticates with). **A `slack run` re-install is
  required to apply the new scope** before the live [HUMAN] AC can pass.

**Files modified**
- `coordinator/bookmark.py` (new) — `upsert_board_bookmark`: idempotent add-or-edit
  of the single "📋 Community Cases board" channel bookmark in `COORDINATOR_CHANNEL`;
  best-effort, never raises; user-token override.
- `coordinator/canvas.py` — `_create` now calls `upsert_board_bookmark` alongside
  `announce_board`, isolated in its own best-effort try/except; imports `canvas_link`
  to share the announce's link form.
- `coordinator/announce.py` — `announce_board`'s `chat_postMessage` now passes
  `unfurl_links=False, unfurl_media=False`.
- `coordinator/__init__.py` — export `upsert_board_bookmark`.
- `manifest.json` — `bookmarks:write` added to bot and user scopes.
- `tests/unit/coordinator/test_bookmark.py` (new) — 9 tests: skip-when-off,
  skip-when-link-None, add-when-absent, edit-when-present, re-run-no-duplicate,
  user-token forwarding, no-token-when-absent, swallow list/add failures.
- `tests/unit/coordinator/test_announce.py` — added unfurl-suppression test.
- `tests/unit/coordinator/test_canvas.py` — added 3 tests: create upserts bookmark
  with the deep link + user token, edit does not re-upsert, bookmark failure never
  breaks the create.
- `tests/unit/coordinator/conftest.py` — autouse stub for `upsert_board_bookmark`
  (mirrors the existing `announce_board` stub) so canvas tests stay isolated.

**Tests**
- Unit: 395 passing, 0 failing — full `make pre-commit` suite. Touched-module subset
  (bookmark + announce + canvas): 50 passing.
- Integration: N/A — no infra changes (no live Slack/network; all mocked).

**Acceptance criteria**
- [x] AC1 — `bookmarks:write` in manifest; bookmark add/update on create/recreate,
  no duplicates. Verified by `tests/unit/coordinator/test_bookmark.py::test_adds_bookmark_when_absent`,
  `::test_edits_bookmark_when_present`, `::test_re_run_does_not_duplicate`, and
  `tests/unit/coordinator/test_canvas.py::test_create_upserts_board_bookmark_with_deep_link`.
- [x] AC2 — announce no longer unfurls; link form opens for members. Verified by
  `tests/unit/coordinator/test_announce.py::test_announce_suppresses_unfurl` and
  `::test_canvas_link_constructs_docs_url_with_team`.
- [x] AC3 — tests cover add-vs-update, unfurl flags, URL construction; zero warnings
  (`filterwarnings=error` passed).
- [ ] [HUMAN] AC4 — NOT RUN. Needs a live `slack run` re-install (new scope) + manual
  check that #exmouth-mutual-aid shows the top-bar bookmark and the announce has no
  login-card unfurl.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
92 files already formatted
uv run ruff check
All checks passed!
... 395 passed in 3.95s

$ uv run pytest tests/unit/coordinator/test_bookmark.py tests/unit/coordinator/test_announce.py tests/unit/coordinator/test_canvas.py -q
.................................................. (50)
50 passed in 1.74s

$ # end-to-end (mocked WebClient): create -> bookmarks_add, recreate-with-existing -> bookmarks_edit
bookmarks_add: {'channel_id': 'C_COORD_DEMO', 'title': '📋 Community Cases board', 'type': 'link',
                'link': 'https://slack.com/docs/T0B9Z77AX2R/F_LIVE', 'token': 'xoxp-user'}
bookmarks_edit: {'bookmark_id': 'Bk1', 'channel_id': 'C_COORD_DEMO',
                 'link': 'https://slack.com/docs/T0B9Z77AX2R/F_LIVE2', 'title': '📋 Community Cases board',
                 'token': 'xoxp-user'}
announce: unfurl_links=False, unfurl_media=False, link in text
```

**Notes**
- Touched only `coordinator/` (announce.py, canvas.py, new bookmark.py, __init__.py)
  + `manifest.json` + tests. agent/, recall/, matching/, listeners/ untouched.
- `announce_board` / `update_board` / `publish` signatures unchanged — the bookmark
  is internal to the create path.
- Did NOT commit (per contract — awaiting Tester PASS + PM ACCEPT).
- One scope nuance for the Tester: `bookmarks:write` is in both bot and user scope
  lists. AC #1 says "bot scopes"; I added it to bot **and** user because the demo's
  `make board` script authenticates as the user, and that's the path that actually
  needs to add the bookmark for the live AC. Flagging in case the team wants it
  bot-only.

### [Tester] 2026-06-13 16:20 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 92 files formatted; `ruff check` all passed; `make pre-commit` 395 passed)
- Unit tests: 395 passed / 0 failed (double-run: 395 passed again, no order pollution)
- Integration tests: 5 passed / 1 skipped (live-provider key absent — expected) / 0 failed
- Warnings: 0 (`filterwarnings = ["error"]` active; clean run)

**E2E adversarial pass** (exercised `coordinator.bookmark` + `canvas._create` against a mocked `WebClient`)
- Happy path: `_create` with `team_id="T_TEAM"` → `bookmarks_add(channel_id=C_COORD, title="📋 Community Cases board", type=link, link=https://slack.com/docs/T_TEAM/F_X, token=xoxp-user)` + announce posted with unfurls off (PASS)
- Break (a) `COORDINATOR_CHANNEL` unset → no `bookmarks_list/add/edit` call at all (PASS — feature off, mirrors announce)
- Break (b) existing bookmark, **same title / different url** → `bookmarks_edit(bookmark_id=Bk_BOARD, link=…/NEW)`, `bookmarks_add` NOT called (PASS — url updated, no dup)
- Break (c) two rapid creates (list: absent→present) → `add` count 1, `edit` count 1 (PASS — idempotent, single bookmark). Confirmed at canvas layer too: create adds 1, subsequent edit-publish re-touches 0.
- Break (d) `bookmarks_add` raises (and separately `bookmarks_edit` raises, `bookmarks_list` raises) → logged "(board unaffected)" and swallowed, never re-raised. Full `_create` with add-raise → returns `F_LIVE`, canvas persisted, announce still posted (PASS)
- Break (e) malformed `bookmarks_list`: missing `bookmarks` key / `bookmarks=None` → falls to add; entry with matching title but **missing `id`** → `KeyError` swallowed by best-effort guard, no add/edit, never raises (PASS — robust against malformed payload)
- Double-run pollution: 2× `make unit-tests` both 395 passed; touched subset `-p no:randomly` 50 passed (PASS)

**Acceptance criteria**
- [x] PASS — AC1: `bookmarks:write` scope added (bot + user); single "📋 Community Cases board" bookmark add/update on create/recreate, no dup, best-effort.
      Evidence: `manifest.json` scopes — JSON valid, `bookmarks:write` in both `user` and `bot`, no other scope/setting changed (diff is the two insertions only). Tests `test_bookmark.py::{test_adds_bookmark_when_absent,test_edits_bookmark_when_present,test_re_run_does_not_duplicate}`; `test_canvas.py::test_create_upserts_board_bookmark_with_deep_link`. Best-effort verified by live probe (add/edit/list raise → swallowed) + `test_swallows_{list,add}_failure` + `test_canvas.py::test_bookmark_failure_does_not_break_publish`. Idempotency proven on both branches via mocked `bookmarks_list` (absent→add, present→edit). Auth uses `token=` override (NOT manual `Authorization`): `test_forwards_user_token` / `test_no_token_override_when_user_token_absent`; token threading from `_create` confirmed live (`xoxp-USERTOK` flows to list+add). Channel-off skip: `test_skipped_when_channel_off`.
- [x] PASS — AC2: announce no longer unfurls; link form opens for members.
      Evidence: `announce.py:98-104` passes `unfurl_links=False, unfurl_media=False`; `test_announce.py::test_announce_suppresses_unfurl` asserts both `is False`; live probe confirms both False on the real `chat_postMessage`. Link form `https://slack.com/docs/{team}/{canvas}` shared by bookmark + announce via `canvas_link` (`test_canvas_link_constructs_docs_url_with_team`). URL-form correctness for the enterprise org is the [HUMAN] live item (AC4).
- [x] PASS — AC3: tests cover add-vs-update (mocked list/add/edit), unfurl flags, URL construction; zero warnings.
      Evidence: `test_bookmark.py` (9 tests), `test_announce.py::test_announce_suppresses_unfurl`, `test_canvas.py` (+3). `filterwarnings=error` clean across 395 unit tests.
- [ ] [HUMAN] AC4 — Awaiting human verification. NOT RUN: requires a live `slack run` re-install to apply the new `bookmarks:write` scope, then manual check that #exmouth-mutual-aid shows a top-bar bookmark opening the board and the announce shows no login-card unfurl. Correctly left unchecked.

**Regression (017/018/020)**
- Full coordinator + board-script + button suite: 132 passed (`tests/unit/coordinator/`, `test_open_board.py`, `test_crisis_buttons.py`).
- `_create` still creates + persists (`save_canvas_id`) + announces — confirmed live (canvas persisted True, announce posted True even when bookmark fails).
- Edit path does not re-touch bookmark/announce — only create does (`test_edit_does_not_upsert_bookmark`; live: edit re-touch 0).
- Public signatures stable: `announce_board`, `canvas_link`, `update_board`, `publish`, `recreate` unchanged; bookmark is internal to `_create`. All annotated incl. `-> None`. New `upsert_board_bookmark` exported in `__all__`.

**Guardrail re-check (CLAUDE.md)** — bookmark/announce are discoverability layers, not actions; both are best-effort and degrade explicitly via logs ("board unaffected") rather than going silent or breaking the create. No safety assertion, no auto-action introduced. Sourcing/confirmation guardrails untouched.

**Evidence**
```
$ make pre-commit
uv run ruff format --check  → 92 files already formatted
uv run ruff check           → All checks passed!
... 395 passed in 3.39s

$ make unit-tests  → 395 passed (run 1)  |  395 passed (run 2)
$ make integration-tests → 5 passed, 1 skipped in 3.69s

$ # live adversarial (mocked WebClient)
(a) channel off  → list/add/edit not called
(b) same title, new url → bookmarks_edit(link=…/NEW), no add
(c) two creates  → add=1, edit=1
(d) add/edit/list raise → swallowed; _create returns F_LIVE, persisted, announced
(e) missing 'id' in list entry → KeyError swallowed, no raise
token threading → bookmarks_list/add token = xoxp-USERTOK
announce → unfurl_links=False, unfurl_media=False, token=xoxp-user
```

**Other issues found**
- None blocking. Note (non-blocking): `_find_board_bookmark_id` accesses `entry["id"]` directly; a malformed list entry with a matching title but no `id` raises `KeyError`, but the upsert's best-effort `try/except` swallows it cleanly (verified live) — no add/edit happens, no exception leaks. Behavior is correct; the team may optionally prefer `entry.get("id")` for clarity. Not a defect.

**VERDICT: PASS**

### [SWE] 2026-06-13 15:10 — Fixes (Tester non-blocking nit)

Addressed the Tester's one non-blocking observation proactively, ahead of the PR
Reviewer.

**Change**
- `coordinator/bookmark.py` — `_find_board_bookmark_id` now reads `entry.get("id")`
  and skips a title-matching entry that has no id (falls through to the add path)
  instead of `entry["id"]`. The outer best-effort guard still catches anything else;
  this just makes the foreseeable malformed-payload case explicit rather than relying
  on the try/except to swallow a `KeyError`.
- `tests/unit/coordinator/test_bookmark.py` — added
  `test_malformed_matching_entry_without_id_falls_through_to_add` (regression): a
  title-match with no id → no `bookmarks_edit`, exactly one `bookmarks_add`, no raise.

**Tests**
- Unit: 396 passing (was 395; +1 regression), 0 failing — `make pre-commit`.
- format-check + lint-check clean.

**Notes**
- No behavior change to the happy path; signatures unchanged. Still uncommitted —
  awaiting PM ACCEPT.
