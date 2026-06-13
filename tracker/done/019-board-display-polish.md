# 019 — Coordinator board display polish

W4 live verification (2026-06-13) confirmed the board lifecycle works
(Open → Connected → Resolved + activity log). Two cosmetic gaps to fix before
the demo video (W5):

1. **Raw user ids instead of names.** Case rows + activity lines render
   `<@U0BA67L9HRS>` literally — Slack canvas markdown does NOT resolve `<@id>`
   mention syntax the way chat messages do. Options: (a) resolve display names via
   `users.info` (cache per id; one lookup per distinct actor/offerer) and show the
   name, or (b) research whether canvas markdown has a mention syntax that resolves.
   Investigate (a) is most reliable. Best-effort — fall back to the id on lookup
   failure.
2. **Raw audit target `offer:<uuid>` in the activity log.** Show the human resource
   instead (e.g. "connected the camp-beds offer"). The board composer already
   receives the offers list, so `_activity_line` can resolve an `offer:<uuid>`
   target against it and render the resource_type; fall back to the bare target if
   the offer isn't found.

Both are pure-composition changes in coordinator/board.py (+ a names helper for #1).
Keep the sourcing/verify guardrails intact. Unit-test the name resolution + target
humanization with mocked lookups.

## Log

### [SWE] 2026-06-13 — Implementation

**Files modified**
- `coordinator/names.py` (new) — best-effort user-id -> display-name resolver via
  `users.info` on the user token (`token=` override); one call per distinct id,
  per-id isolation, never raises, empty map with no token.
- `coordinator/board.py` — `compose_board_markdown` takes an optional
  `names: dict[str,str]`; `_case_row` / `_activity_line` render the display name
  (bare id fallback) instead of `<@id>`; new `_humanize_target` resolves
  `offer:<uuid>` -> "the <resource_type> offer" (bare target fallback) and
  `offerer:<id>` -> name. Composer stays pure.
- `coordinator/canvas.py` — new `_person_ids` (offerers + audit actors + `offerer:`
  targets) and `_compose_with_names` (the impure boundary): resolves names with the
  user token and threads them into the composer; a names failure is swallowed so the
  board still renders bare ids. `publish` and `_publish_fresh` use it.
- `tests/unit/coordinator/test_names.py` (new) — resolution, token override,
  caching, field precedence, per-id degrade, no-token skip.
- `tests/unit/coordinator/test_board.py` — name rendering on rows + activity lines,
  target humanization (offer uuid -> resource, unknown -> bare, offerer -> name),
  names param optional/pure; updated two stale tests that asserted `<@id>` syntax.
- `tests/unit/coordinator/test_canvas.py` — publish resolves names + threads them,
  collects the full id set, swallows a names-lookup failure.

**Names-resolution design + auth**
- `users.info` is called once per distinct id, authenticated as the acting user via
  slack_sdk's per-call `token=` override — the SAME lesson as the canvas write
  (`coordinator/canvas.py` docstring): a manual `Authorization` header does NOT take
  effect for typed methods (slack_sdk resets Authorization from its own token after
  merging headers); `token=` is the override that works. Confirmed
  `WebClient.users_info(user=..., **kwargs)` accepts `token` via `**kwargs`, and the
  e2e render asserts `token == "xoxp-demo"` is what reaches the API.
- Display-name precedence: `profile.display_name` -> `profile.real_name` ->
  `real_name` -> `name` -> (omit -> caller renders bare id).
- Best-effort: per-id failure / malformed response / no usable name omits that id;
  the composer falls back to the bare id. With no user token the lookup is skipped.

**Tests**
- Unit: 341 passing, 0 failing (`make pre-commit` / `make unit-tests`). Zero warnings
  (`filterwarnings=error`). Coordinator subset: 72 passing.
- Integration: N/A — no infra changes; no live Slack/network touched (WebClient +
  `users_info` mocked).

**Acceptance criteria**
- [x] AC1 Resolve user ids to display names — `coordinator/names.py`;
  `tests/unit/coordinator/test_names.py` + `test_canvas.py::test_publish_resolves_names_and_threads_them_into_the_board`.
  Composer stays pure (names dict in); lookup at the canvas publish boundary.
- [x] AC2 Humanize audit targets — `_humanize_target` (offer uuid -> resource,
  offerer -> name, unknown -> bare);
  `test_board.py::test_activity_line_humanizes_offer_target_to_resource` and the
  offerer/fallback cases.
- [x] AC3 Guardrails intact — verify note + source + timestamp on every row, no
  safety assertion, no auto-action; `test_board.py::test_board_carries_verify_note_and_asserts_no_safety` still passes; e2e render shows all four.
- [x] AC4 Tests (mirror tree, mocked WebClient/users_info, zero warnings) — done.
- [ ] [HUMAN] AC5 Live AC — render the board in a live `slack run` / Block Kit
  Builder and confirm names + humanized targets on the real Canvas. NOT RUN
  (needs a real TTY for `slack run`; out of agent scope).

**Evidence**
```
$ make pre-commit
... 341 passed in 1.40s

$ # end-to-end render (realistic Exmouth state, mocked users.info, token= verified)
## Connected (1)
- *camp beds* in Exmouth — offered by Rosario Bennet · 2026-03-21 09:30 UTC

## Activity log
- Dana Lee dismissed Sam Okafor · 2026-03-21 09:30 UTC
- Rosario Bennet connected the camp beds offer · 2026-03-21 09:30 UTC
```
Before this change those rendered as `offered by <@U0BA67L9HRS>` and
`<@U...> connected ` + raw ``offer:3e2b788d-...`` / ``offerer:<id>``.

**Notes**
- Touched only `coordinator/names.py`, `coordinator/board.py`, `coordinator/canvas.py`
  and their tests. Did not touch `agent/agent.py`, `mocks/`, recall ranking, or the
  button state machine.
- `compose_board_markdown` is backward-compatible (`names` optional, defaults to bare
  ids); no caller outside `coordinator/` exists.
- Did NOT commit — handing off to the Tester.

### [Tester] 2026-06-13 14:30 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 86 files formatted; `ruff check` all passed; unit suite green)
- Unit tests: 341 passed / 0 failed (coordinator subset 72/72 in isolation)
- Integration tests: 5 passed / 1 skipped (live-provider key absent — expected) / 0 failed
- Warnings: 0 (`filterwarnings=["error"]` enforced; double-run + isolated subset all clean)

**E2E adversarial pass** (real composer + `resolve_display_names` + publish boundary, mocked WebClient, no live network)
- Happy path (realistic Exmouth state: camp-beds MATCHED + generator OPEN, connect + dismiss audit lines): board renders `Rosario Bennet` / `Dana Lee` / `Sam Okafor`, `the camp beds offer`, NO `<@...>` syntax, NO raw uuid, verify-note + `2026-03-21 09:30 UTC` timestamps present — PASS
- Break (a) boundary/state — users_info reports deleted user / no profile fields → `{}` resolved → row renders bare id `U_GONE`, no crash — PASS
- Break (b) failure mode — no user token → zero `users_info` calls, board renders all bare ids (`U_X`, `U_Y`) + verify note — PASS
- Break (c) malformed input — audit target neither `offer:` nor `offerer:` (`weird-raw-target`, empty string) → rendered verbatim, never dropped/blanked — PASS
- Break (d) large input — 500 offers / 5 distinct offerers → exactly 5 `users_info` calls (deduped), board renders fine — PASS
- Break (e) malformed responses — `None`, `{ok:False}`, `{user:"not-a-dict"}`, `{user:{profile:"nope"}}`, SDK `ValueError` → all degrade to `{}`, never raise — PASS
- Precedence — `display_name > profile.real_name > top-level real_name > name > omit` exhaustively verified — PASS
- Double-run / isolated-subset pollution — none; counts stable across runs — PASS

**Acceptance criteria**
- [x] AC1 PASS — Resolve user ids to display names. Composer pure (board.py imports only `datetime`/`entities`/`matching.audit`; no Slack/WebClient/token ref); `users_info` lives only in `coordinator/names.py:75`, fetched at the publish boundary `coordinator/canvas.py:84 _compose_with_names`. Token via `token=` override (`names.py:75`), asserted reaching the API by `test_names.py::test_uses_user_token_via_token_override` and `test_canvas.py::test_publish_resolves_names_and_threads_them_into_the_board` (call.args[1] == token). One call per distinct id: `test_one_lookup_per_distinct_id` + adversarial 500→5. Precedence + bare-id fallback: `test_falls_back_to_real_name_when_display_name_blank`, `test_failed_lookup_omits_that_id`, `test_case_row_falls_back_to_bare_id_when_name_unknown`.
- [x] AC2 PASS — Humanize audit targets. `_humanize_target` (board.py:128): `offer:<uuid>`→resource (`test_activity_line_humanizes_offer_target_to_resource`), unknown offer id→bare target (`test_activity_line_falls_back_to_bare_target_when_offer_absent`), `offerer:<id>`→name (`test_activity_line_resolves_offerer_target_to_name`), unknown prefix→verbatim (adversarial break c).
- [x] AC3 PASS — Guardrails intact. Every case row keeps source + timestamp; verify note at top; no safety assertion (`test_board_carries_verify_note_and_asserts_no_safety` passes); board reads audit trail only, no auto-action (composer pure, no state mutation). Confirmed visually in adversarial happy-path render.
- [x] AC4 PASS — Tests mirror tree (`tests/unit/coordinator/test_names.py` new), mocked WebClient/users_info, AAA, zero warnings.
- [ ] [HUMAN] AC5 — Live render on real Canvas via `slack run` / Block Kit Builder. NOT RUN — requires authed sandbox + real TTY + human visual confirmation; out of agent scope. `slack` CLI is on PATH but cannot drive an interactive live session non-interactively. Awaiting human verification.

**017/018 regression**
- Public signatures unchanged (`update_board(client, user_token, team_id)`, `publish`, `recreate` — git diff touches only internal `_compose_with_names`/`_person_ids`). Button handlers (connect/resolve/dismiss in `crisis_buttons.py:246,280,314`), offer-index refresh (`recall_reply.py:130`), and `scripts/open_board.py:67 recreate` all call the unchanged surface — board still updates on offer-index + button actions. All 72 coordinator + canvas tests pass.

**Evidence**
```
$ make pre-commit
86 files already formatted / All checks passed! / 341 passed in 1.43s
$ make unit-tests   → 341 passed (run 1) / 341 passed (run 2)
$ make integration-tests → 5 passed, 1 skipped (run 1 & 2)
$ uv run pytest tests/unit/coordinator → 72 passed in 0.14s
```

**Other issues found**
- None blocking. `code-review` plugin not configured (no `.claude/settings.json` entry) — advisory step N/A.
- Note (non-blocking): `resolve_display_names`'s broad `except Exception` is the intended degraded-state guardrail and the publish boundary double-wraps it (`_compose_with_names` try/except). Belt-and-braces, correct for "a names lookup never breaks a board refresh."

**VERDICT: PASS** (AC1–AC4 verified with evidence; AC5 is [HUMAN], correctly NOT RUN)
