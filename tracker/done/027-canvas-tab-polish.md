# 027 — Channel-canvas tab polish: title it, reuse-don't-delete, fix discovery

Task 025 made the board a channel canvas (a top-bar tab) but live testing exposed
three defects, all rooted in a wrong assumption ("a channel has ONE canvas"):

1. **Tab shows "Untitled."** `conversations_canvases_create` takes no `title` param in
   our call, and the markdown `# H1` is NOT used as the tab label, so the tab reads
   "Untitled". **Verified fix (2026-06-13):** passing `title="Community Cases"` as a
   kwarg to `conversations_canvases_create` (it flows into the JSON body via
   `**kwargs`) sets the tab `label` to "Community Cases". Confirmed live.
2. **Discovery reads the wrong key.** `_discover_channel_canvas_id` reads
   `channel.properties.canvas.file_id`, but live `conversations.info` returns
   `properties.canvas = None`; the canvas tabs live under
   `properties.tabs` as entries `{"type":"canvas","id":"Ct...","label":...,
   "data":{"file_id":"F..."}}`. A channel can have MULTIPLE canvas tabs (not one).
   So discovery never finds the existing tab → the persisted-id store is the only
   thing preventing a duplicate, and the restart-reattach AC is effectively broken.
3. **Deletes orphan tabs + announce spam.** `recreate` (and repeated `make board
   --fresh`) DELETE the canvas then create a new one — but **deleting a canvas does
   NOT remove its channel tab**; it leaves a "Deleted file" tombstone tab, and there
   is **no app-usable API to remove a tab** (`conversations.removeTab` exists but
   returns `not_allowed_token_type` for bot/user tokens — it's browser-session only;
   `canvases.access.delete` only revokes access). So every recreate piles up dead
   tabs. Separately, `_after_create` posts an announce message on every create, so
   repeated creates spammed the channel with board-link messages (several now point
   at deleted canvases).

## Design decisions (locked)

- **Title on create.** Add a `title` (default `"Community Cases"` — a new short
  constant in coordinator/board.py, distinct from the long `BOARD_TITLE` H1) passed to
  `conversations_canvases_create`. The H1 inside the document stays `BOARD_TITLE`.
- **Never delete; always reuse + edit.** The one titled tab is permanent. Drop the
  delete-then-create from `recreate`: a "fresh" board is just a full-replace edit of
  the existing tab's content (which, with an empty index, already renders the empty
  board). `recreate` becomes "reattach (persisted id → tabs discovery) and replace;
  create titled only if none exists" — i.e. it converges with `publish`. Keep the
  public method names/signatures (`publish`, `recreate`, `update_board`) stable;
  callers (button handlers, scripts/open_board) are unchanged. `make board` and
  `make board ARGS=--fresh` may now behave identically (both reuse) — update the
  Makefile help + open_board docstring to say so, or keep `--fresh` as "force a clean
  empty re-render" (no delete). NO canvas deletion remains in the create/refresh path.
  (`canvases_delete` may stay imported only if some explicit admin path needs it; the
  board lifecycle must not call it.)
- **Discovery reads `properties.tabs`.** Rewrite `_discover_channel_canvas_id` to scan
  `channel.properties.tabs` for entries with `type == "canvas"` and return the first
  `data.file_id` (defensively: also accept `data.id`/top-level `file_id`). Prefer the
  persisted id first (unchanged), then this tabs scan. Keep the
  `channel_canvas_already_exists` race handler but re-discover via the tabs scan.
- **Drop the announce.** Remove the announce from the create path (`_after_create`):
  the titled permanent tab is the discovery mechanism — an announce message is now
  pure noise and was the source of the spam. Persist the id (still needed to bridge
  processes), but post nothing. `coordinator/announce.py` and `COORDINATOR_CHANNEL`
  become unused by the board; leave the module (harmless) but stop calling it, and
  note it obsolete in the ADR. (Do NOT delete announce.py / its tests in this task —
  just stop wiring it; a later cleanup task can remove it.)
- **Tombstone tab cleanup is manual / out of scope.** No API can remove the existing
  dead tabs; the operator removes them once in the UI. Document this in the ADR so
  it's not re-investigated. Going forward, never-delete means no new tombstones.

## Acceptance criteria

1. [x] The channel canvas is created with `title="Community Cases"` (new
   `BOARD_TAB_TITLE` constant) so the tab is labelled, not "Untitled". — unit test
   asserts the `conversations_canvases_create` call includes `title=BOARD_TAB_TITLE`.
2. [x] `_discover_channel_canvas_id` reads `properties.tabs` (first `type=="canvas"`
   entry's `data.file_id`), with defensive fallbacks; `properties.canvas` is no longer
   relied on. — unit tests: tabs with a canvas entry → returns its file_id; no canvas
   tab → None; malformed/missing tabs → None (no raise).
3. [x] No canvas-deletion in the board lifecycle. `recreate` reattaches (persisted id,
   else tabs discovery, else create-titled) and full-replaces; it never calls
   `canvases_delete`. — unit tests: `recreate` with an existing persisted id edits (no
   create, no delete); with none, creates titled. grep: no `canvases_delete` in the
   publish/recreate/create paths.
4. [x] The create path no longer announces (no `announce_board` call); the id is still
   persisted. — unit test asserts `announce_board` is NOT called on create; `save_canvas_id`
   still is. Update/replace the announce-on-create tests accordingly.
5. [x] Public surface stable: `publish`, `recreate`, `update_board`, and
   `scripts/open_board` signatures unchanged; all existing callers compile and pass. —
   suite green.
6. [x] ADR-0005 amended again (or an ADR-0007): channel allows MULTIPLE canvas tabs;
   title-on-create; reuse-not-delete (tab tombstones can't be API-removed); discovery
   via `properties.tabs`; announce/`COORDINATOR_CHANNEL` obsolete for the board;
   manual one-time UI cleanup of existing tombstones noted.
7. [x] CLAUDE.md updated where it describes the board canvas / announce / `make board`
   behavior (e.g. the `make board` and `COORDINATOR_CHANNEL` rows) to match
   reuse-not-delete + no-announce.
8. [x] `make pre-commit` + unit + integration green, zero warnings, double-run stable.
9. [ ] [HUMAN] Live: after the operator removes the existing tombstone tabs in the UI,
   `make board` (and `--fresh`) keeps exactly ONE titled "Community Cases" tab, never
   adds a tab, and edits in place on Connect/Resolve/Dismiss.

## BDD scenarios

- Given no persisted id and a channel whose `properties.tabs` has a canvas entry for
  F_EXISTING, When `publish` runs first, Then it reattaches to F_EXISTING and edits
  (no create, no new tab).
- Given no persisted id and no canvas tab, When `publish` runs, Then it creates with
  `title="Community Cases"` and persists the id, and does NOT announce.
- Given a persisted id, When `recreate` runs, Then it edits that canvas in place and
  never calls `canvases_delete`.
- Given a `channel_canvas_already_exists` error on create, When it is handled, Then it
  re-discovers via `properties.tabs` and reattaches.

## Out of scope
- Removing existing tombstone tabs (no API — manual UI, documented).
- Deleting announce.py / bookmark.py / their tests (leave; just stop calling announce).
- The offer-index backfill (task 026) — independent.

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `coordinator/board.py` — added `BOARD_TAB_TITLE = "Community Cases"` (the tab
  label), distinct from the long `BOARD_TITLE` H1.
- `coordinator/canvas.py` — pass `title=BOARD_TAB_TITLE` on every
  `conversations_canvases_create`; rewrote `_discover_channel_canvas_id` to scan
  `properties.tabs` (first `type=="canvas"` → `data.file_id`, fallbacks
  `data.id`/top-level `file_id`, wrapped so malformed tabs return `None`); made
  `recreate` reuse + replace by delegating to `publish` (removed `_publish_fresh` +
  `_mint_channel_canvas`, dropped `canvases_delete`); removed the `announce_board`
  import and the announce call from `_after_create` (now persists id only).
- `scripts/open_board.py` — docstring/help/log updated to reuse-not-delete +
  no-announce (routing unchanged: default→`publish`, `--fresh`→`recreate`).
- `Makefile` — `board` help line reflects reuse-not-delete + clean re-render.
- `docs/adr/0005-canvas-as-durable-board.md` — added the task-027 amendment
  (multiple canvas tabs; title-on-create; reuse-not-delete + tombstone reasoning;
  `properties.tabs` discovery; announce/`COORDINATOR_CHANNEL` obsolete; manual
  tombstone cleanup noted).
- `CLAUDE.md` — `make board` row + `COORDINATOR_CHANNEL` row updated.
- `tests/unit/coordinator/test_canvas.py` — retitled module doc; added
  `_info_with_canvas_tab` helper; AC1 title assertion; rewrote recreate tests
  (reuse/never-delete); replaced `properties.canvas` discovery tests with
  `properties.tabs` tests incl. fallbacks + a parametrized malformed-tabs table;
  rewrote announce tests to assert announce is NOT called (patched in
  `coordinator.announce`); added `test_create_never_deletes`.
- `tests/unit/coordinator/conftest.py`, `tests/unit/listeners/actions/conftest.py`
  — dropped the now-invalid `mocker.patch("coordinator.canvas.announce_board")`
  (canvas.py no longer imports it).
- `tests/unit/scripts/test_open_board.py` — wording updated to reuse-not-delete
  (assertions unchanged).

**Tests**
- Unit: 411 passing, 0 failing (`make unit-tests` / `pytest tests/unit`). Ran twice
  with `-W error` — zero warnings, double-run stable.
- Integration: 5 passing, 1 skipped (live-provider parse test; no key) — no infra
  changed.

**Acceptance criteria**
- [x] AC1 (title-on-create) — `test_first_publish_creates_channel_canvas_with_markdown`
  (asserts `kwargs["title"] == BOARD_TAB_TITLE`).
- [x] AC2 (`properties.tabs` discovery + fallbacks + no-raise) —
  `test_discovers_existing_channel_canvas_via_properties_tabs`,
  `test_discovery_uses_data_id_fallback_when_no_file_id`,
  `test_discovery_uses_top_level_file_id_fallback`,
  `test_no_canvas_tab_falls_through_to_create`,
  `test_empty_properties_falls_through_to_create`,
  `test_malformed_tabs_does_not_raise_and_falls_through_to_create` (parametrized).
- [x] AC3 (no deletion; recreate reattach+replace) —
  `test_recreate_reuses_in_process_canvas_and_never_deletes`,
  `test_recreate_reuses_persisted_id_and_never_deletes`,
  `test_recreate_with_no_existing_canvas_creates_titled`, `test_create_never_deletes`;
  grep confirms no `canvases_delete` call in canvas.py.
- [x] AC4 (no announce; id still persisted) — `test_create_does_not_announce` (asserts
  `coordinator.announce.announce_board` not called and `save_canvas_id` called),
  `test_edit_does_not_announce`, `test_reattached_id_does_not_announce`,
  `test_discovered_canvas_does_not_announce`.
- [x] AC5 (signature stability) — full suite green; `scripts/open_board` routing tests
  unchanged (`test_default_reuses_board_via_publish`, `test_fresh_flag_recreates`).
- [x] AC6 (ADR amended) — ADR-0005 task-027 amendment section.
- [x] AC7 (CLAUDE.md) — `make board` + `COORDINATOR_CHANNEL` rows updated.
- [x] AC8 (pre-commit + unit + integration green, zero warnings, double-run stable) —
  see Tests + Evidence.
- [ ] [HUMAN] AC9 — live UI verification of the single titled tab after manual
  tombstone removal; left for the operator.

**Evidence**
```
$ make pre-commit
... 411 passed in 2.19s

$ make integration-tests
... 5 passed, 1 skipped in 1.32s

$ uv run pytest tests/unit -q -W error   # run 1
411 passed in 5.17s
$ uv run pytest tests/unit -q -W error   # run 2 (double-run stable)
411 passed in 2.63s

# Live (a real SLACK_USER_TOKEN was present in .env, so the script ran against the
# sandbox). Default, then --fresh, then default again — all reuse the SAME canvas
# via an EDIT, never delete, never create a new tab:
$ uv run python -m scripts.open_board
INFO:coordinator.canvas:Updated coordinator board canvas F0B9WFCGQ6T
$ uv run python -m scripts.open_board --fresh
INFO:coordinator.canvas:Updated coordinator board canvas F0B9WFCGQ6T
$ uv run python -m scripts.open_board
INFO:coordinator.canvas:Updated coordinator board canvas F0B9WFCGQ6T
```

**Notes**
- The live runs took the persisted-id reattach path (an id is already in
  `.slack/board_canvas_id`), so they exercised reuse-not-delete live. The
  title-on-create and `properties.tabs`-discovery paths are covered by unit tests
  (no clean-channel sandbox to exercise create live without first removing the
  existing tab — AC9's manual step).
- `coordinator/announce.py`, `coordinator/bookmark.py`, `COORDINATOR_CHANNEL`, and
  their tests are intentionally left in place (per task scope) — just unwired from
  the board. `coordinator/__init__.py` still re-exports `announce_board` /
  `coordinator_channel_id` (public surface unchanged).

### [Tester] 2026-06-13 14:50 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` → 411 passed)
- Unit tests: 411 passed / 0 failed (`make unit-tests`)
- Integration tests: 5 passed / 1 skipped (live-provider parse test, no key) / 0 failed
- Warnings: 0 — `pyproject.toml [tool.pytest.ini_options] filterwarnings = ["error"]`
  is in effect; 411-pass with `-W error` confirms zero warnings. Double-run stable
  (run1 411 passed 1.72s / run2 411 passed 1.88s).

**E2E adversarial pass** (real `CoordinatorBoard` driven against a mock `WebClient`;
live `make board` deliberately NOT run — it is a shared-Slack write under the user's
identity and is exactly AC9's [HUMAN] step. Entry point exercised via the no-token /
argparse degrade paths instead.)
- Happy path (entry point): `uv run python -m scripts.open_board --help` → renders
  usage with the updated `--fresh` help ("Force a clean re-render … no new tab"),
  exit 0. No-token run → `ERROR: SLACK_USER_TOKEN is not set …`, exit 1 (fast-fail, no
  canvas call). Bad flag → argparse error, exit 2. (PASS)
- Break path 1 (state edge — tabs-discovery reattach): no persisted id, `properties.tabs`
  has a canvas entry → reattaches to its `data.file_id`, EDITS, no create, no delete. (PASS)
- Break path 2 (state edge — no canvas tab): empty `properties` → falls through to
  `conversations.canvases.create` with `title="Community Cases"`, `channel_id=CRISIS`,
  no delete. (PASS)
- Break path 3 (state edge — persisted-id reuse): load_canvas_id returns an id →
  short-circuits before `conversations.info`, edits that id, no create, no delete. (PASS)
- Break path 4 (concurrency — `channel_canvas_already_exists` race): first info none →
  create 409s → re-discovers via `properties.tabs` → edits the winner `F_WON_RACE`,
  no delete. (PASS)
- Break path 5 (failure mode — race + re-discovery finds nothing): the 409 re-raises,
  is swallowed by `publish` → returns None, `canvas_id` stays None, no crash, no delete. (PASS)
- Break path 6 (malformed/hostile inputs — 7 tab shapes): `tabs="not-a-list"`,
  `["x",42,None]`, canvas tab with no id, `properties=None`, `channel=None`, no
  `channel` key, `{}` → every one returns None without raising and falls through to
  create. (PASS)
- Break path 7 (failure mode — dependency blowup): `conversations_canvases_create`
  raises `RuntimeError` → swallowed, returns None, never propagates out of `publish`
  (degraded-state guardrail; logged "handler unaffected"). (PASS)
- Break path 8 (concurrency — 8 parallel publishes, no persisted id): the
  `threading.Lock` serialises the find-or-create → exactly ONE create call, all 8
  converge on the same id. (PASS) — a path the unit suite does not stress.
- Break path 9 (state edge — `CRISIS_CHANNEL` unset): `designated_channel_id()` None
  → `RuntimeError` raised internally and swallowed → returns None, no create, no crash. (PASS)
- recreate (state edge): with a persisted id → reuses + edits, `canvases_delete` never
  called; with nothing to reattach → create-titled, still no delete. (PASS)
Adversarial summary: 10/10 break paths PASS.

**Acceptance criteria**
- [x] PASS — AC1 (title-on-create) — `conversations.canvases.create` is called with
      `title=BOARD_TAB_TITLE`; `coordinator/board.py:43` defines
      `BOARD_TAB_TITLE = "Community Cases"`, distinct from `BOARD_TITLE =
      "Crisis Resource Navigator — Community Cases"` (board.py:38). Driver confirmed
      `kwargs["title"] == "Community Cases"` on the create call;
      `test_first_publish_creates_channel_canvas_with_markdown` asserts it
      (test_canvas.py:108). `canvas.py:329` passes `title=BOARD_TAB_TITLE`.
- [x] PASS — AC2 (tabs discovery) — `_discover_channel_canvas_id` (canvas.py:350-380)
      reads `properties.tabs`, first `type=="canvas"` → `data.file_id`
      (fallbacks `data.id`, top-level `file_id`), wrapped so malformed/missing tabs
      return None without raising; `properties.canvas` appears only in comments
      (grep confirmed). Tests: tabs-discovery, data.id fallback, top-level file_id
      fallback, no-canvas-tab, empty-properties, 6-row parametrized malformed table,
      info-failure (test_canvas.py:601-741). Driver hit all 7 hostile shapes + raise. 
- [x] PASS — AC3 (no deletion; recreate reattach+replace) — grep: no `canvases_delete`
      call anywhere in `coordinator/canvas.py` (only docstrings + test
      `assert_not_called`). `recreate` (canvas.py:261-280) delegates to `publish`;
      `_publish_fresh`/`_mint_channel_canvas` fully removed (grep: 0 references, no
      stranded callers). Tests: recreate-reuses-in-process / persisted-id /
      creates-titled-with-no-existing / create-never-deletes (test_canvas.py:182-247,
      843-854). Driver: recreate + create paths never call `canvases_delete`.
- [x] PASS — AC4 (no announce; id still persisted) — `announce_board` import removed
      from canvas.py (grep: only `coordinator/__init__.py` re-export + announce.py
      itself remain); `_after_create` (canvas.py:382-393) calls only
      `canvas_store.save_canvas_id`. Tests inverted: `test_create_does_not_announce`
      patches `coordinator.announce.announce_board`, asserts not-called AND
      `save_canvas_id` called (test_canvas.py:776-794); plus edit/reattached/discovered
      no-announce variants. Both conftests dropped the obsolete
      `mocker.patch("coordinator.canvas.announce_board")`.
- [x] PASS — AC5 (public surface stable) — `publish`/`recreate`/`update_board`
      signatures unchanged (still accept `team_id`/`team_url`, now unused);
      `scripts/open_board` routing unchanged (default→`publish`, `--fresh`→`recreate`,
      open_board.py:90/92). All callers import + run: `listeners/actions/crisis_buttons`
      (3 `update_board` calls), `listeners/recall_reply`, `scripts/open_board` — full
      import check `import coordinator.canvas, coordinator.board, coordinator,
      scripts.open_board, listeners.actions.crisis_buttons, listeners.recall_reply` →
      "all imports OK". Regression suites green: announce 64-incl, crisis_buttons,
      recall_reply (button-handler refresh path intact).
- [x] PASS — AC6 (ADR amended) — `docs/adr/0005-canvas-as-durable-board.md` has the
      "Amendment — titled tab, reuse-not-delete, tabs discovery (task 027)" section
      covering: multiple canvas tabs, title-on-create, never-delete + tombstone
      reasoning, `properties.tabs` discovery, announce/`COORDINATOR_CHANNEL` obsolete,
      manual one-time UI tombstone cleanup. Header `Amended: … (task 027)` line added.
- [x] PASS — AC7 (CLAUDE.md) — `make board` row rewritten to reuse-not-delete +
      create-titled + no-announce + `--fresh` = clean re-render; `COORDINATOR_CHANNEL`
      row marked "obsolete for the board as of task 027". Makefile `board` help line
      and `open_board.py` docstring/help match.
- [x] PASS — AC8 (suite green, zero warnings, double-run) — see Test summary.
- [ ] [HUMAN] AC9 — live single-titled-tab verification after the operator manually
      removes the existing tombstone tabs. Awaiting human verification (live `make board`
      intentionally not run by QA — shared-Slack write). The create-titled,
      tabs-discovery, and reuse-not-delete branches that AC9 exercises live are all
      proven at the unit + driver level above.

**Evidence**
```
$ make pre-commit
... 411 passed in 2.60s

$ make unit-tests
... 411 passed in 1.77s

$ make integration-tests
... 5 passed, 1 skipped in 2.04s

$ uv run pytest tests/unit -q -W error   # run 1
411 passed in 1.72s
$ uv run pytest tests/unit -q -W error   # run 2 (double-run stable)
411 passed in 1.88s

$ grep -rn "canvases_delete" coordinator/canvas.py     # only docstrings, no call
coordinator/canvas.py:39: ... NEVER calls ``canvases_delete`` ...
coordinator/canvas.py:275: ... it NEVER calls ``canvases_delete`` ...

$ grep -rn "_publish_fresh\|_mint_channel_canvas" --include="*.py" .   # (empty — fully removed)

# Adversarial driver (real CoordinatorBoard, mock WebClient):
ADVERSARIAL SUMMARY: 10/10 passed

# open_board entry point (no live write):
no-token exit=1   bad-flag exit=2   --help exit=0
```

**Other issues found**
- None blocking. Note (non-blocking): `BOARD_TAB_TITLE` "Community Cases" is a
  substring of `BOARD_TITLE`; intentional and verified distinct (the long H1 lives in
  the document body, the short label on the tab). No action.
- Note (already in task scope, out of scope here): `coordinator/announce.py`,
  `coordinator/bookmark.py`, and `COORDINATOR_CHANNEL` are now dead-but-present; their
  tests still run (64 announce-incl green). A later cleanup task can remove them per
  the design decision.

**VERDICT: PASS**
