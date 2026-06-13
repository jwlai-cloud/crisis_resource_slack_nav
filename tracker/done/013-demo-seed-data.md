# 013 — Seed the Exmouth scenario (demo-ready workspace)

Make the sandbox read as a real Cyclone Narelle mutual-aid operation so the demo
video + judges see a populated, credible workspace (design doc demo plan; "Pre-seed
the workspace before recording").

## Decided design (from live probes, 2026-06-13)
- **Matchable offers are posted via the user token (SLACK_USER_TOKEN) as the
  operator account.** Live-verified: such posts are RTS-matchable (~1 min indexing
  lag) and RTS attributes them to the real user, so the recall noise filter keeps
  them. They carry a bot_id on the raw event so the passive listener skips them
  (no ack spam — exactly what we want for seed). Trade-off: every matchable offer
  shows the operator as offerer (we can't author as the 7 seeded personas — no
  tokens; chat:write.customize posts are bot-authored and get filtered from recall).
  Accept this; the demo narration still works.
- **Texture (coordinator notices, chatter) MAY use chat:write.customize** for varied
  persona names/avatars in the "noisy channel" scroll — these are non-matchable
  (bot-authored) which is fine for flavor. Requires the `chat:write.customize` bot
  scope (add to manifest + note re-install) IF used; otherwise post texture as the
  operator too. SWE: keep it simple — operator-posted texture is acceptable if the
  scope adds friction.

## Acceptance criteria
1. [x] `scripts/seed_demo.py` (+ `make seed-demo`): posts into CRISIS_CHANNEL
   (C0BA6LCKK42) via the user token —
   - 5–6 believable offers (e.g. 2kW generator, 20L water, two camp beds, baby
     formula, a spare room, a first-aid kit), spread across Exmouth/North
     Exmouth/Learmonth, matching the demo script beats;
   - 1–2 coordinator notices (SES/DFES-style update);
   - a few lines of believable chatter for the "before" scroll.
2. [x] **Idempotent**: tag seeded messages (a trailing hidden marker, or record posted
   ts to a gitignored file) and skip on re-run — running twice does not duplicate.
   A `--reset`/`--fresh` flag may delete prior seeds for a clean re-seed.
3. [x] Document the RTS indexing lag (offers are matchable ~1 min after seeding) and the
   operator-attribution limitation in the script docstring + CLAUDE.md commands.
4. [x] Unit tests: message-building (the scenario content + marker), idempotency logic
   (skip when marker present) — mock the WebClient, NO live posting in tests.
   filterwarnings=error, zero warnings.
5. [ ] [HUMAN] live: run `make seed-demo`; confirm the channel is populated; wait ~1 min;
   post a need; confirm a seeded offer matches in the reply + appears on the board.

## Out of scope
The Mara/second-account path (abandoned — domain-locked invites). Persona-authored
matchable offers (impossible without their tokens).

## Log
DECISION 2026-06-13: self-account seeding (live-probed RTS-matchable). Mara dropped.

### [SWE] 2026-06-13 13:05 — Implementation

**Files modified**
- `scripts/seed_demo.py` — new one-shot seeder: typed `SCENARIO` (4 chatter + 2
  notices + 6 offers), marker/idempotency helpers (`with_marker`,
  `is_seeded_message`, `pending_messages`), history-scan + delete + post
  orchestration, env-guarded `main()`. Posts via `SLACK_USER_TOKEN` as the
  per-call `token=` override (mirrors `coordinator/canvas.py`).
- `tests/unit/scripts/test_seed_demo.py` — 15 unit tests: scenario content
  (counts, resources, localities, SES/DFES notice, "Offering:" phrasing), marker
  building/detection, idempotency decision, and env-guard + post/skip/`--fresh`
  orchestration with a mocked WebClient (no live posting, no real scan).
- `Makefile` — `seed-demo` target (+ `.PHONY`); `make seed-demo ARGS=--fresh`.
- `CLAUDE.md` — `make seed-demo` Commands row (idempotency + ~1-min RTS lag +
  operator-attribution noted); `CRISIS_CHANNEL` bullet notes it's the seed target.
- `.env.example` — `SLACK_USER_TOKEN` comment notes the seeder's chat:write +
  channels:history scopes.

**Idempotency mechanism**
- Trailing literal marker `·crn-seed` (middle dot + tag) appended to every seeded
  message. A run scans the last 200 channel messages via `conversations_history`
  (user token), collects marked texts, and posts only scenario messages not already
  present — running twice never duplicates. `--fresh`/`--reset` first deletes every
  marker-bearing message (and ONLY those — ordinary chatter is never touched) via
  `chat_delete`, then reposts the full scenario clean. Chose the in-Slack marker over
  a gitignored ts-file: self-contained, survives across machines/checkouts, and the
  `--fresh` cleanup is a single greppable scan. History scan is best-effort (API
  error → treated as "no prior seed", logged).

**Texture posting choice**
- Operator-posted texture only — NO `chat:write.customize`. Per the task's
  "keep it simple", avoids a new manifest scope + re-install. All messages
  (offers, notices, chatter) post as the operator; offer text names the offerer
  ("Jo on the North Exmouth side") so narration reads naturally despite attribution.

**Tests**
- Unit: 382 passing (15 new), 0 failing — `make pre-commit` tail below.
- Integration: N/A — no infra changes; unit tests mock the WebClient, no live Slack.

**Acceptance criteria**
- [x] AC1 scenario + `make seed-demo` — `test_scenario_has_expected_message_counts`,
  `test_offers_cover_the_demo_resources`, `test_offers_spread_across_the_three_localities`,
  `test_coordinator_notice_reads_like_an_ses_dfes_update`, `test_offers_are_phrased_as_mutual_aid_posts`,
  `test_fresh_run_posts_every_scenario_message_with_marker`.
- [x] AC2 idempotency + `--fresh` — `test_pending_messages_skips_already_posted`,
  `test_rerun_skips_already_seeded_messages`, `test_fresh_flag_deletes_prior_seed_then_reposts`,
  `test_fresh_flag_does_not_delete_unmarked_messages`.
- [x] AC3 docs (RTS lag + operator attribution) — script docstring + CLAUDE.md row + `.env.example`.
- [x] AC4 unit tests, mocked WebClient, no live posting, filterwarnings=error zero warnings.
- [ ] [HUMAN] AC5 live seed + ~1-min RTS match — NOT RUN (requires live sandbox + tokens; do not post live from CI/agent).

**Evidence**
```
$ uv run python -m scripts.seed_demo --help
usage: seed_demo [-h] [--fresh]
Seed the Cyclone Narelle / Exmouth scenario into CRISIS_CHANNEL.
options:
  -h, --help        show this help message and exit
  --fresh, --reset  Delete every prior seeded message before re-seeding (clean demo re-run).

$ # fail-fast env guards (offline, load_dotenv mocked, vars cleared):
ERROR:scripts.seed_demo:SLACK_USER_TOKEN is not set — ... retry.   -> rc 1, no post
ERROR:scripts.seed_demo:CRISIS_CHANNEL is not set — ... retry.     -> rc 1, no post

$ make pre-commit
uv run ruff format --check
90 files already formatted
uv run ruff check
All checks passed!
...
tests/unit/scripts/test_seed_demo.py ...............                     [ 90%]
...
============================= 382 passed in 9.26s ==============================
```

**Notes**
- Did not run the happy-path live post (AC5 is [HUMAN]) — posting into the real
  sandbox channel from the agent is out of bounds. Verified end-to-end via `--help`,
  the `make seed-demo` ARGS passthrough, and both fail-fast guards offline.
- Constraint honoured: touched only `scripts/`, `Makefile`, `CLAUDE.md`,
  `.env.example`, and `tests/` — no changes to agent/recall/matching/coordinator/listeners.
- No commit (per contract — awaiting Tester PASS).

### [Tester] 2026-06-13 14:20 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`ruff format --check` 90 files OK; `ruff check` all passed)
- Unit tests: 382 passed / 0 failed (double-run: 382 both times, no pollution)
- Integration tests: 5 passed / 1 skipped (live parsing, no provider key) — no regression
- Warnings: 0 (`filterwarnings=["error"]` in effect)
- `code-review` plugin: not configured in `.claude/settings.json` — N/A

**E2E adversarial pass** (WebClient mocked throughout; no live posting, no real channel scan)
- Happy path: `uv run python -m scripts.seed_demo --help` → usage + `--fresh/--reset`, rc=0 (PASS)
- Fail-fast (boundary: missing env, load_dotenv mocked): no `SLACK_USER_TOKEN` → clear ERROR, rc=1, 0 posts; token set + no `CRISIS_CHANNEL` → clear ERROR, rc=1, 0 posts (PASS)
- Break path 1 (failure mode: history-scan `SlackApiError`): WARNING logged, degrades to "no prior seed", still posts all 12 best-effort, 0 deletes, rc=0 — matches documented behavior (PASS)
- Break path 2 (state edge: `--fresh` with nothing to delete): 0 deletes, 12 clean posts, rc=0 (PASS)
- Break path 3 (state edge: partial prior seed, 3 of 12 present): only the missing 9 post, none of the 3 reposted, rc=0 — idempotency proven, no duplicates (PASS)
- Break path 4 (hostile/coincidental input: real human message containing literal `·crn-seed`): normal run unaffected (coincidental text ≠ any scenario text, all 12 post); `--fresh` *would* delete it (marker-scoped delete catches the coincidental marker). Reasoned + documented as no-realistic-false-positive; middle-dot+tag substring is not plausible human chatter (PASS-with-note)
- Break path 5 (malformed payload: no `messages` key): handled via `.get("messages", []) or []`, posts all 12, rc=0 (PASS)

**Acceptance criteria**
- [x] PASS — AC1 scenario + `make seed-demo`: 6 offers (2kW generator, 20L water, two camp beds, baby formula, spare room, first-aid kit), 2 SES/DFES notices, 4 chatter; localities Exmouth/North Exmouth/Learmonth all present. Evidence: data audit (offers=6, notices=2, chatter=4; all 6 resources + 3 localities matched); `tests/unit/scripts/test_seed_demo.py::test_scenario_has_expected_message_counts|test_offers_cover_the_demo_resources|test_offers_spread_across_the_three_localities|test_coordinator_notice_reads_like_an_ses_dfes_update|test_offers_are_phrased_as_mutual_aid_posts`; `make seed-demo` target present in `Makefile:50`.
- [x] PASS — AC2 idempotent + `--fresh`: marker `·crn-seed` appended to every message; re-run scans `conversations_history` and posts only missing scenario messages; `--fresh` deletes ONLY marked messages (`chat_delete` ts filtered to marker-bearing), then reposts. Evidence: live adversarial break paths 3+4 (partial-seed posts only 9; unmarked chatter never deleted) + `test_rerun_skips_already_seeded_messages`, `test_fresh_flag_deletes_prior_seed_then_reposts`, `test_fresh_flag_does_not_delete_unmarked_messages`, `scripts/seed_demo.py:193` (`_delete_prior_seed` scoped to `_scan_seeded`).
- [x] PASS — AC3 docs: RTS ~1-min lag + operator-attribution in script docstring (`scripts/seed_demo.py:11-26`), `make seed-demo` row in `CLAUDE.md`, and `.env.example` scope note. Verified present.
- [x] PASS — AC4 unit tests, mocked WebClient, no live posting, zero warnings: 15 tests pass in isolation and in full suite; WebClient + `load_dotenv` mocked, history fed canned responses; `filterwarnings=error` green. token=user_token override used for all 3 API calls (no manual Authorization header) — `scripts/seed_demo.py:180,203,218`; verified via `test_fresh_run_posts_every_scenario_message_with_marker` asserting `call.kwargs["token"] == "xoxp-user"`.
- [ ] [HUMAN] AC5 live seed + ~1-min RTS match — Awaiting human verification. NOT RUN (live sandbox posting out of bounds for the agent).

**Entry-point conventions** (CLAUDE.md): `logging.basicConfig` at module level (`:52`) before project imports (`agent.deps :58`, `listeners.channel_gate :59`, `# noqa: E402`); `load_dotenv` in `main()`; no `print()` in script; all functions fully type-annotated incl. `-> int`/`-> None`; fail-fast rc=1 with clear message + 0 posts on missing env. All verified PASS.

**Evidence**
```
$ make pre-commit
uv run ruff format --check
90 files already formatted
uv run ruff check
All checks passed!
... tests/unit/scripts/test_seed_demo.py ............... [ 90%] ...
============================= 382 passed in 4.01s ==============================
$ make unit-tests   # second run
============================= 382 passed in 4.79s ==============================
$ make integration-tests
========================= 5 passed, 1 skipped in 2.70s =========================
```

**Other issues found** (non-blocking, for SWE/orchestrator judgment)
- Minor robustness smell: `_scan_seeded` (`scripts/seed_demo.py:187`) reads `m["ts"]` (hard subscript) while reading text defensively with `m.get("text", "")`. A message object lacking `ts` raises `KeyError` in both the scan and the `--fresh` delete path. NOT a user-reachable defect — Slack's `conversations_history` always returns `ts` on every message object, so this is theoretical-only on a payload the live API never emits. A one-line `m.get("ts")` guard (skip if absent) would close the asymmetry. Flagging only; not a FAIL.
- The `·crn-seed` marker delete under `--fresh` will catch any message literally containing the substring, including a (vanishingly unlikely) real human message. Behavior is documented and reasoned in the docstring; acceptable as designed.

**VERDICT: PASS**

### [Orchestrator] 2026-06-13 — AC5 live verification (PASS)
Ran `make seed-demo` against the sandbox: 12 messages posted into C0BA6LCKK42
(6 offers, 2 SES/DFES notices, 4 chatter). Verified RTS-matchable — baby formula /
spare room / first-aid kit all returned by assistant.search.context within seconds.
Workspace is demo-populated. (Note: pre-existing live-test debris also sits in the
channel; a final cleanup with `make seed-demo ARGS=--fresh` + manual debris removal
is a W5 pre-recording step.)
