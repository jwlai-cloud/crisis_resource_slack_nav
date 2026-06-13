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
