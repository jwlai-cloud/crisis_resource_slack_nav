# 018 — Coordinator board discoverability + cross-process canvas id

Gap surfaced landing 017 (SWE flagged it honestly): the standalone `make board`
script and the live agent each hold a process-local CoordinatorBoard.canvas_id, so
a script-created canvas is NOT the one the server updates on button actions — the
server lazily creates its OWN canvas on first action, which nobody has a link to.

Fix direction (small, demo-critical for the W4/W5 coordinator beat):
1. Persist the canvas id to a known location both processes read/write — e.g. a
   gitignored `.slack/board_canvas_id` file (or a tiny settings entry). publish()
   reads it on first call; create writes it. Both `make board` and the server then
   operate on the SAME canvas.
2. Discoverability: on server startup (app.py) OR on board creation, post the
   canvas permalink once to the designated coordinator channel (CRISIS_CHANNEL or a
   new COORDINATOR_CHANNEL) so a coordinator can open it. Idempotent — announce once.
3. Update scripts/open_board.py + README/CLAUDE.md so `make board` is the single
   "mint + announce" entry and the server reuses it.

Demo impact: without this the coordinator Canvas beat (demo 1:45–2:10) is awkward to
stage. Do before the video (W5), ideally in W4 right after 017.

## Log

### [SWE] 2026-06-13 11:21 — Implementation

**Id-persistence mechanism.** A new best-effort file store, `coordinator/canvas_store.py`,
owns a single gitignored file `.slack/board_canvas_id` that both processes share.
`_id_path()` resolves it relative to the package's repo root (stable regardless of
the launching `cwd` — script vs agent). `load_canvas_id()` returns `None` on a
missing / empty / whitespace-only / unreadable file (degrade → create); `save_canvas_id()`
mkdirs `.slack/` and writes the id. Both swallow `OSError` (log, never raise).
`CoordinatorBoard.publish()` now, on first call when its in-process `_canvas_id` is
`None`, reads the store *before* deciding to mint — so the `make board` script
creates+persists and the server's first refresh reads the same id and **edits** that
canvas (no duplicate). The existing `threading.Lock` still guards the
read-modify-write. `recreate()` deliberately bypasses the reattach (via a new private
`_publish_fresh`) so the demo "clean board" always mints + persists + announces fresh.

**Announce design.** New `coordinator/announce.py` mirrors `listeners/channel_gate.py`:
`COORDINATOR_CHANNEL` env (channel id; empty/unset = off, whitespace-trimmed).
`announce_board(client, *, canvas_id, team_id)` posts the board link **once**, hooked
only into `_create` (so it fires on create, never on the many edits — idempotent per
canvas). Link form is the standalone-canvas docs URL `https://slack.com/docs/{team}/{canvas}`
when a team id is known; without one it posts the bare canvas id (still discoverable).
Best-effort: a post failure is logged + swallowed. `team_id` is threaded
additively through `publish`/`recreate`/`update_board` (all keyword-default `None`,
signatures stable); button handlers pass `context.team_id`, the script resolves it
best-effort via `auth.test`.

**Files modified**
- `coordinator/canvas_store.py` (new) — cross-process canvas-id file store (load/save, best-effort).
- `coordinator/announce.py` (new) — `COORDINATOR_CHANNEL` env + announce-on-create board link post.
- `coordinator/canvas.py` — `publish` reattaches via the store before create; `_create` persists + announces; `recreate` mints fresh via `_publish_fresh`; `update_board`/`publish`/`recreate` take optional `team_id`.
- `coordinator/__init__.py` — export `announce_board`, `coordinator_channel_id`.
- `listeners/actions/crisis_buttons.py` — pass `context.team_id` to `update_board` (3 call sites).
- `scripts/open_board.py` — resolve team id (best-effort `auth.test`) + pass to `recreate`; docstring now states mint+persist+announce; mentions persisted-id reattach.
- `.gitignore` — ignore `.slack/board_canvas_id` (Slack CLI's own `.slack/.gitignore` doesn't cover it; verified with `git check-ignore`).
- `.env.example` — `COORDINATOR_CHANNEL` block mirroring `CRISIS_CHANNEL`.
- `CLAUDE.md` — `make board` row (mint+persist+announce, reattach) + `COORDINATOR_CHANNEL` env doc.
- Tests: `tests/unit/coordinator/test_canvas_store.py` (new), `tests/unit/coordinator/test_announce.py` (new), `tests/unit/coordinator/test_canvas.py` (+persistence/announce cases), `tests/unit/coordinator/conftest.py` + `tests/unit/listeners/actions/conftest.py` (autouse store/announce isolation → no real `.slack/` writes), `tests/unit/listeners/actions/test_crisis_buttons.py` + `tests/unit/scripts/test_open_board.py` (updated for the additive `team_id` arg).

**Tests**
- Unit: 317 passing, 0 failing (`make pre-commit`). Zero warnings (`filterwarnings=error`).
- Integration: N/A — no infra changes (all canvas/announce/file boundaries are mocked + tmp_path; no live Slack, no real `.slack/` writes).

**Acceptance criteria**
- [x] AC1 — Canvas id persisted to a shared gitignored `.slack/board_canvas_id`; both processes read/write it. `publish` loads on first call before create; `_create` saves after minting. Verified: `test_canvas_store.py` round-trip + degrade cases; `test_canvas.py::test_create_persists_canvas_id_to_shared_store`, `::test_first_publish_loads_persisted_id_and_edits_not_creates`, `::test_missing_store_degrades_to_create`, `::test_persisted_id_loaded_only_once_not_on_every_publish`. Thread-safe (existing lock); best-effort (file errors logged, never raised).
- [x] AC2 — `COORDINATOR_CHANNEL` env (empty = off, mirrors channel_gate); link posted once on create, not on edit; best-effort. Verified: `test_announce.py` (off/on, once, no-team fallback, swallow failure, link form); `test_canvas.py::test_create_announces_board_link_once`, `::test_edit_does_not_announce`, `::test_reattached_id_does_not_announce`, `::test_announce_failure_does_not_break_publish`.
- [x] AC3 — `scripts/open_board.py` mints + persists + announces via the same `recreate` path; CLAUDE.md + .env.example updated for `COORDINATOR_CHANNEL`. Verified: `test_open_board.py::test_recreate_called_with_resolved_token_and_team_id`, `::test_team_id_failure_degrades_to_none_without_aborting`.
- [x] AC4 — Tests (mirror tree): id-file round-trip + missing/corrupt degrade, announce once-on-create / not-on-edit, `COORDINATOR_CHANNEL` empty = no announce. WebClient + filesystem mocked (tmp_path); no live API, no real `.slack/` writes. Zero warnings.
- [ ] [HUMAN] Live AC — **NOT RUN.** Live verification (run `make board` against the sandbox with a real `SLACK_USER_TOKEN`, confirm the agent's first button action edits the *same* canvas rather than creating a duplicate, and that the link posts once to `COORDINATOR_CHANNEL`) needs a real TTY + sandbox auth and cannot run in this environment.

**Evidence**

`make pre-commit` tail:
```
tests/unit/scripts/test_open_board.py .....                              [ 90%]
tests/unit/test_app_home_opened.py ..                                    [ 90%]
tests/unit/test_system_prompt.py .........................               [ 98%]
tests/unit/test_view_builders.py ....                                    [100%]
============================= 317 passed in 1.92s ==============================
```

Gitignore verification:
```
$ git check-ignore -v .slack/board_canvas_id
.gitignore:36:.slack/board_canvas_id	.slack/board_canvas_id
```

E2E cross-process smoke (mocked WebClient, tmp `.slack/`):
```
PROCESS 1 (make board): created F_FROM_SCRIPT; canvases_create=1; persisted file=F_FROM_SCRIPT; announce posts=1
  announce text: :pushpin: The Community Cases board is open — <https://slack.com/docs/T_TEAM/F_FROM_SCRIPT|open the coordinator board> (canvas F_FROM_SCRIPT). ...
PROCESS 2 (server first publish): returned F_FROM_SCRIPT; canvases_create=0; canvases_edit=1 (canvas_id=F_FROM_SCRIPT); announce=0
COORDINATOR_CHANNEL empty: announce posts=0
```

**Notes**
- Constraints honoured: 017 button-state-machine tests and the coordinator tests all green; `publish`/`update_board` signatures are stable (new `team_id` is keyword-default `None`, additive). No touch to `agent/agent.py` SYSTEM_PROMPT, `mocks/`, or `recall/`.
- `_id_path()` resolves via `Path(__file__).parent.parent` (repo root), not `cwd`, because the script and agent may launch from different working dirs — both still hit the same file.
- ADR-0005 consequence "the canvas handle is not durable / reattaching across restarts is deferred" is now *partially* addressed for the cross-process case (script↔server) via the id file. Full restart-rehydration of the index is still out of scope (unchanged). No ADR edit made (PM territory) — flagging for PM in case ADR-0005's Consequences want a follow-up note.
- Two autouse conftest fixtures (coordinator + actions) point the store at `tmp_path` and stub `announce_board` so no test ever writes the real `.slack/` or posts to Slack; tests asserting those contracts re-patch over them.
- DO NOT COMMIT — handing to Tester.

### [Tester] 2026-06-13 14:05 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` → 317 passed)
- Unit tests: 317 passed / 0 failed (double-run: 317/317 both runs, no state pollution)
- Integration tests: 5 passed / 1 skipped (live-provider key absent) / 0 failed
- Warnings: 0 (`filterwarnings=error` in effect)
- Isolation: no real `.slack/board_canvas_id` written by any test or by my e2e harness
  (`ls .slack/board_canvas_id` → absent; `git status` shows no `.slack` changes). Both
  autouse conftests point the store at `tmp_path` and stub `announce_board`.

**E2E adversarial pass** (ran the real modules with a tmp store + mocked WebClient/announce)
- Happy path — cross-process: process A `recreate()` → created `F_FROM_SCRIPT`, creates=1, persisted file=`F_FROM_SCRIPT`, announce posts=1; fresh process B `publish()` → returned `F_FROM_SCRIPT`, creates=0, edits=1 (canvas_id=`F_FROM_SCRIPT`), announce=0. PASS — server reattaches + edits, no duplicate, single announce on A only.
- Break path 1 (degrade — missing/empty/whitespace/unreadable file): `load_canvas_id()` → `None` in all four cases; `save_canvas_id` under `write_text` OSError → swallowed, no raise; `publish()` with an unwritable store still created the canvas (id returned, creates=1). PASS — board never breaks on a bad id file.
- Break path 2 (recreate bypasses reattach): store pre-seeded `F_OLD_PERSISTED`; `recreate()` with a `load_canvas_id` spy → load_calls=0, minted `F_FRESH_RECREATE`, creates=1, edits=0, store overwritten to fresh id. PASS — recreate does NOT read the store; `_publish_fresh` goes straight to `_create`.
- Break path 3 (announce off/best-effort/once): unset and whitespace `COORDINATOR_CHANNEL` → 0 posts; `chat_postMessage` raising `channel_not_found` → publish still returned the id (swallowed); 1 create + 2 edits → creates=1, edits=2, announce=1. PASS — fires once on create, never on edit, never raises into the handler.
- Break path 4 (thread-safety): 20 threads first-publish on one board → creates=1, edits=19, announce=1, all threads returned the same `F_T1`, store=`F_T1`. PASS — the lock serialises the read(store)→modify→write; exactly 1 create + 1 persist + 1 announce.
- Break path 5 (adversarial a — canvas deleted server-side): persisted `F_DELETED`, `canvases_edit` raises `canvas_not_found` → publish returned `None`, no re-create, `_canvas_id` stays `None`, store unchanged. Degrades sanely (never raises). NOT auto-recreate. Bonus: because `_canvas_id` stays `None` on a failed edit, the NEXT publish re-reads the store — verified self-healing once the operator reruns `make board` (store→`F_REPAIRED`, next publish edits `F_REPAIRED`). Honest note, not an AC gap.
- Break path 6 (adversarial b — team_id None): announce text is the bare-id form (`canvas \`F_NOTEAM\``, no `slack.com/docs` deep link). PASS — still discoverable, no broken link.
- Break path 7 (adversarial c — two servers reattach same id): both `publish()` on store=`F_SHARED` → both creates=0, edits=1, announce=0. PASS — both edit, no create, no double-announce.
- Break path 8 (no user_token): `publish(None)` → returned `None`, creates=0, announce=0, store untouched. PASS — skip path is clean.
- `_id_path()` real resolution: `<repo>/.slack/board_canvas_id`, resolved via `Path(__file__).resolve().parent.parent` (cwd-independent). PASS.

**Acceptance criteria**
- [x] AC1 PASS — canvas id persisted to shared gitignored `.slack/board_canvas_id`; both processes read/write; `publish` loads the store before minting when `_canvas_id is None`, `_create` saves after minting.
      Evidence: `coordinator/canvas.py:120-130` (load-before-create inside the lock), `:197` (`save_canvas_id` in `_create`); `coordinator/canvas_store.py:48-80`; tests `test_canvas_store.py` (8/8: round-trip, missing/empty/whitespace/unreadable→None, save OSError swallowed, `_id_path` under `.slack`), `test_canvas.py::test_first_publish_loads_persisted_id_and_edits_not_creates`, `::test_create_persists_canvas_id_to_shared_store`, `::test_missing_store_degrades_to_create`, `::test_persisted_id_loaded_only_once_not_on_every_publish`; e2e break paths 1, 4, 7.
- [x] AC2 PASS — `COORDINATOR_CHANNEL` env (empty/unset = off, whitespace-trimmed); link posted once on create, never on edit; best-effort (post failure logged, swallowed). Hook is in `_create` only.
      Evidence: `coordinator/announce.py:34-88`; hook at `coordinator/canvas.py:198-204` inside `_create` (not `_replace`); tests `test_announce.py` (8/8), `test_canvas.py::test_create_announces_board_link_once`, `::test_edit_does_not_announce`, `::test_reattached_id_does_not_announce`, `::test_announce_failure_does_not_break_publish`; e2e break path 3.
- [x] AC3 PASS — `scripts/open_board.py` mints + persists + announces via the same `recreate` path; resolves team id best-effort via `auth.test`; CLAUDE.md + .env.example updated for `COORDINATOR_CHANNEL`. `.slack/board_canvas_id` gitignored.
      Evidence: `scripts/open_board.py:60-90` (`_resolve_team_id` + `recreate(client, user_token, team_id)`); `git check-ignore -v .slack/board_canvas_id` → `.gitignore:36`; `.env.example` + `CLAUDE.md` diffs reviewed; tests `test_open_board.py::test_recreate_called_with_resolved_token_and_team_id`, `::test_team_id_failure_degrades_to_none_without_aborting` (auth.test failure → team_id=None, still exits 0).
- [x] AC4 PASS — tests mirror the source tree; id-file round-trip + degrade, announce once-on-create / not-on-edit, channel-off; WebClient + filesystem mocked (tmp_path); no live API, no real `.slack/` writes; zero warnings.
      Evidence: new `tests/unit/coordinator/test_canvas_store.py`, `test_announce.py`; `test_canvas.py` +13 cases; autouse isolation in both conftests; full suite 0 warnings (`filterwarnings=error`).
- [ ] AC5 [HUMAN] — NOT RUN. Live verification (run `make board` against the sandbox with a real `SLACK_USER_TOKEN`; confirm the agent's first button action EDITS the same canvas, not a duplicate; confirm the link posts once to `COORDINATOR_CHANNEL`) needs a real TTY + sandbox auth. Awaiting human verification.

**017 regression**
- All coordinator + button + script tests green (targeted run: 77 passed). `publish`/`recreate`/`update_board` signatures additive (`team_id: str | None = None` keyword-default — `coordinator/canvas.py:91,136,226`). All 3 button call sites pass `context.team_id` (`crisis_buttons.py:246,280,314`). No `print()` in `coordinator/`, `listeners/`, `scripts/`.

**Evidence**
```
$ make pre-commit
============================= 317 passed in 3.91s ==============================
$ make unit-tests   # double-run
============================= 317 passed in 1.35s ==============================
============================= 317 passed in 1.63s ==============================
$ make integration-tests
========================= 5 passed, 1 skipped in 0.99s =========================
$ git check-ignore -v .slack/board_canvas_id
.gitignore:36:.slack/board_canvas_id	.slack/board_canvas_id
$ ls .slack/board_canvas_id        # after full suite + e2e harness
ls: .slack/board_canvas_id: No such file or directory   # no real id file written
```

**Other issues found** (none blocking)
- (Note, not a defect) A failed edit on a reattached id returns `None` and does NOT auto-recreate; the canvas stays stuck until the store points at a live canvas. Mitigated by the self-healing property above (a failed edit leaves `_canvas_id=None` so the next publish re-reads the store). Acceptable for the W4/W5 demo scope; flagging only so the PM/SWE are aware. Not an AC requirement.
- SWE's flag re ADR-0005 Consequences (cross-process reattach now partially addresses the deferred-handle note) is a reasonable PM follow-up; out of Tester scope.

**VERDICT: PASS** — all four non-HUMAN ACs verified with code + test + live-module e2e evidence; full suite green, 0 warnings; 8 adversarial break paths all green; 017 regression clean; no real `.slack/` writes; gitignore confirmed. AC5 awaits human live verification.
