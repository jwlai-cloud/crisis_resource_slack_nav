# 008 — Match-card visual parity with the landing page mock

The landing page demo (docs/site/index.html) renders the target reply UX; live replies should match it. User-confirmed direction (2026-06-12). Build alongside / right after the W3 action buttons since the buttons live on these cards.

Gap to close:
1. Parse summary as structured fields — section block with `fields` (need_type / location / urgency / household) instead of LLM prose bullets. Composed by code from the parsed Need, not by the model.
2. Match cards with colored left bar — use message `attachments` (color: green workspace / blue official MCP / red advisory), one attachment per match, blocks inside. Attachments are legacy-but-supported and the only way to get the color bar.
3. Rank label context line per card: `MATCH n · WORKSPACE · REAL-TIME SEARCH` / `· OFFICIAL · MCP FEED`.
4. Action buttons on workspace matches: Connect me / Not relevant (W3 actions task wires the handlers; this task owns the visual placement).
5. Keep: source/ts/permalink/contact/verify line (already live), single streamed reply (005).

Acceptance: side-by-side screenshot of landing-page card vs live Slack card — recognisably the same design.

## Log

### [SWE] 2026-06-12 21:34 — Implementation

**Delivery-surface investigation (color bar: attachments vs alternative)**

The task asks for a colored left bar via message `attachments` *if the delivery
surface allows*. It does **not**. Two independent blockers, evidenced from the
installed SDK:

1. The single streamed reply (task 005) finalises through
   `ChatStream.stop(...)` (`listeners/reply.py:52`). `ChatStream.stop` accepts
   only `markdown_text` / `chunks` / `blocks` / `metadata` and forwards `**kwargs`
   to `chat.stopStream`
   (`.venv/.../slack_sdk/web/chat_stream.py:135-204`). `WebClient.chat_stopStream`
   has no `attachments` field (`channel/ts/markdown_text/blocks/metadata/chunks`
   only). Passing `attachments` via `**kwargs` would bet on an undocumented field
   on a brand-new streaming API — fragile and untestable.
2. Even if it serialized, the 010 action handlers
   (`listeners/actions/crisis_buttons.py:_update_card` / `_replace_action_row`)
   rewrite a card by matching `block_id` inside `body["message"]["blocks"]` — the
   message's **top-level** blocks. Attachment blocks are not in `message.blocks`,
   so burying each `ActionsBlock` inside an attachment would break
   Connect→Resolve / Dismiss rewriting. The buttons must stay top-level blocks.

**Decision:** render the colored left bar as a leading colored-square emoji on
the per-card rank line — `🟩 *MATCH n* · WORKSPACE · REAL-TIME SEARCH` (green =
workspace, matching the mock's workspace card bar). This keeps every element a
top-level block (010 state machine intact) and stays within documented APIs.
Constant `WORKSPACE_BAR_EMOJI` is shared so the offer ack reuses the same cue.
Blue/red MCP-card variants are explicitly future work (AC 3).

**Files modified**
- `recall/blocks.py` — added `WORKSPACE_BAR_EMOJI` + `_RANK_LABEL`; new
  `_parse_summary_block(need)` (code-composed `fields`: need_type/location/
  urgency/household, unknown fields omitted, no placeholders); new
  `_rank_label_block(index)`; `_match_blocks` now leads each card with the rank
  label; `build_recall_blocks(result, *, need=None)` opens the structured region
  with the parse summary on every branch (matches / empty / degraded).
- `recall/__init__.py` — export `WORKSPACE_BAR_EMOJI`.
- `listeners/recall_reply.py` — pass `need=need` into `build_recall_blocks`.
- `matching/blocks.py` — offer ack opens with the aligned `INDEXED_RANK_LABEL`
  (`🟩 *INDEXED* · WORKSPACE MEMORY`), same cue as the recall cards; still no
  action buttons.
- `tests/unit/recall/test_blocks.py` — extended for parse-summary fields,
  rank labels, no-placeholder omission, field/structure caps; existing source/
  buttons assertions retargeted by content (two context blocks per card now).
- `tests/unit/matching/test_matching_blocks.py` — rank-label cue assertion.
- `tests/unit/listeners/test_reply.py` / `test_recall_reply.py` — parse-summary
  leads the single reply; section-text scans skip the fields section.

**Tests**
- Unit: 197 passing, 0 failing — `make pre-commit` tail attached below. Zero
  warnings (`filterwarnings=error`).
- Integration: N/A — Block Kit composition only; no Slack/MCP infra touched.

**Acceptance criteria (orchestrator scope)**
- [x] AC1 parse-summary `fields` (need_type/location/urgency/household), code-
  composed from the Need, unknown fields omitted — `tests/unit/recall/test_blocks.py::test_parse_summary_opens_structured_region_with_fields`,
  `::test_parse_summary_fields_composed_by_code_not_llm`,
  `::test_parse_summary_omits_unknown_fields_no_placeholders`,
  `tests/unit/listeners/test_reply.py::test_need_reply_opens_with_code_composed_parse_summary`.
- [x] AC2 per-card rank label + colored-bar cue (emoji, justified above),
  divider grouping preserved — `::test_each_match_has_a_workspace_rank_label`,
  `::test_rank_label_uses_colored_square_as_left_bar_cue`,
  `::test_multiple_matches_are_divider_separated`.
- [x] AC3 official MCP items stay LLM prose — not intercepted; this task styles
  only code-composed workspace blocks + parse fields. Blue/red MCP-card
  composition noted as future work in `recall/blocks.py` module docstring + the
  `WORKSPACE_BAR_EMOJI` comment.
- [x] AC4 every existing element kept — source/ts/permalink/Contact/verify
  (`::test_every_match_has_source_timestamp_and_verify`,
  `::test_every_match_has_contact_mention`), buttons + 010 state machine
  untouched (`::test_every_match_card_carries_action_buttons`,
  `::test_button_value_*`), top-5 cap + "Showing top N of M"
  (`::test_rank_label_numbering_caps_with_rendered_matches`), degraded/empty
  blocks (`::test_degraded_and_empty_have_no_rank_labels`,
  `::test_*_has_no_action_buttons`).
- [x] AC5 tests updated/extended, zero warnings — see above.
- [ ] [HUMAN] AC (Acceptance line) side-by-side screenshot of landing-page card
  vs live Slack card — **NOT RUN**: requires `slack run` against the sandbox in
  a real TTY (out of scope for the SWE harness). Payload-level parity verified
  instead (rank labels, parse fields, emoji cue, limits — Evidence below).

**Slack-limit verification (run against a worst-case 7-match payload + feedback row)**
- Top-level blocks: 28 (cap 50). Parse-summary fields: 4 (cap 10). Action rows
  stay top-level with stable `block_id`s (`crisis_actions_0..4`). Degraded /
  empty / partial-Need branches serialize cleanly; `location="unknown"` and
  `household_size=0` are omitted (no placeholder, no `?`).

**Evidence**
```
$ make pre-commit
uv run ruff format --check
65 files already formatted
uv run ruff check
All checks passed!
uv run pytest tests/unit || test $? -eq 5
...
tests/unit/recall/test_blocks.py ..........................        [ 65%]
tests/unit/matching/test_matching_blocks.py ....                   [ 43%]
============================= 197 passed in 1.18s ==============================

$ uv run python - <<'PY'  (full-payload limit check)
=== TOTAL TOP-LEVEL BLOCKS: 28 (Slack cap 50) ===
parse-summary fields count: 4 (Slack cap 10)
   field: '*need_type*\nwater · generator'
   field: '*location*\nNorth Exmouth'
   field: '*urgency*\nhigh'
   field: '*household*\n4'
=== RANK LABELS ===
   🟩 *MATCH 1* · WORKSPACE · REAL-TIME SEARCH   (… through MATCH 5)
=== ACTION ROWS (top-level for 010 chat_update) ===
   block_id: crisis_actions_0 actions: ['crisis_connect', 'crisis_not_relevant']  (… 0..4)
=== OFFER ACK ===
   ctx: 🟩 *INDEXED* · WORKSPACE MEMORY
ALL LIMITS OK
```

**Notes**
- Guardrails re-checked (CLAUDE.md): source/ts/Contact/verify still on every
  match (AC4 tests); buttons remain the only actionable surface and the human-
  confirms state machine is untouched (010 tests green); degraded/empty stay
  explicit and now still lead with the parse summary; the parse summary is
  code-composed, never LLM-authored.
- The streamed reply still finalises in one `stop(blocks=...)` call (005) — the
  parse summary + restyled cards + feedback ride that one message, no second
  surface.
- Did NOT touch `agent/agent.py`, `mocks/`, `matching/index.py` (constraint).
- [HUMAN]/Tester: render the live payload in Block Kit Builder or `slack run`
  for the side-by-side screenshot; the emoji left-bar cue is the intentional
  substitute for the mock's CSS `border-left` (justified above).

### [Tester] 2026-06-12 22:40 — QA

**Test summary**
- Format / lint / pre-commit: PASS (`make pre-commit` — 65 files formatted, ruff clean, 197 unit passed)
- Unit tests: 197 passed / 0 failed (double-run identical: pre-commit run + `make unit-tests`)
- Integration tests: 5 passed / 1 skipped (`test_parsing_live` — no live provider key, expected) / 0 failed
- Warnings: 0 (`filterwarnings=["error"]` active; zero-warning policy met)

**SWE attachment-blocker claims — independently verified against the installed SDK (slack_sdk 3.x, py3.13)**
- Blocker 1 CONFIRMED: `ChatStream.stop()` signature exposes only
  `markdown_text / chunks / blocks / metadata / **kwargs` — no `attachments`.
  Underlying `WebClient.chat_stopStream` also has no `attachments` (body =
  `channel/ts/markdown_text/blocks/metadata/chunks`; the literal "attachments"
  does not appear in its source). `reply.py:52` finalises via
  `streamer.stop(blocks=trailing_blocks)`. Attachments are genuinely unreachable
  on the streamed-reply surface — the decision stands.
- Blocker 2 CONFIRMED: `crisis_buttons._update_card` reads
  `body["message"]["blocks"]` (top-level) and `_replace_action_row` matches
  `block.get("block_id") == block_id`. Attachment-nested blocks never appear in
  `message.blocks`, so burying the action row in an attachment would break the
  010 state machine. The emoji-cue decision is correct, not a shortcut.

**E2E adversarial pass**
- Happy path: `build_recall_blocks([3 matches], need=full Need)` → parse-summary
  section (need_type/location/urgency/household) leads, then header, then 3 cards
  each `🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH` + snippet + sourcing + actions. (PASS)
- Break path 1 (boundary: Need with all optional fields unknown — need_type="",
  location="unknown", household_size=0): fields section renders only
  `*urgency*\nlow`; no empty/placeholder fields, no "?". Sane. (PASS)
- Break path 2 (boundary: empty/"unknown"/whitespace location, any case):
  location omitted entirely, no placeholder, known fields still render. (PASS)
- Break path 3 (malformed: household_size=-3): household field omitted (treated
  as unknown), no negative leaks into payload. (PASS)
- Break path 4 (state edge: zero matches + need): parse summary leads, no-matches
  section follows; no rank labels, no actions. Consistent. (PASS)
- Break path 5 (state edge: degraded RecallError + need): parse summary leads,
  "couldn't search the workspace" section follows; no actions, no rank label. (PASS)
- Break path 6 (large input: 8 matches): exactly 5 cards numbered MATCH 1..5,
  action block_ids crisis_actions_0..4, truncation line "Showing the top 5 of 8
  matches." — rank numbers stay aligned. (PASS)
- Break path 7 (hostile input: location="Sandy Bay <script>", need_type="WATER &
  ICE"): values copied verbatim from the Need into mrkdwn (Block Kit escapes on
  render); composed by code from Need attributes only, never from LLM text. (PASS)
- Break path 8 (boundary: match with no permalink + no author_id): "View message"
  and "Contact:" omitted (no broken `<@>`/empty link); still carries Posted-by +
  channel + UTC ts + verify note. (PASS)

**010 regression — traced `_update_card` against the NEW block layout**
- All 17 `test_crisis_buttons.py` tests pass.
- New top-level layout (3 matches): `section`(parse) → `header` → per card
  `context`(rank) → `section`(snippet) → `context`(sourcing) → `actions`. The
  action rows remain top-level with stable block_ids `crisis_actions_0..N`.
- Connect on `crisis_actions_1` via `_replace_action_row`: exactly one block
  changes (index 10), swapped to a `crisis_resolve` button; other action rows
  untouched. Resolve→muted context, Dismiss→muted context all resolve by
  block_id regardless of the inserted rank-label/parse blocks. State machine intact.

**Slack caps**
- Worst case (7 matches → top-5 + truncation line + feedback row): 27 recall
  blocks + 1 feedback = 28 top-level blocks (cap 50). Parse-summary fields: 4
  (cap 10). Both comfortably under.

**Sourcing guardrail (CLAUDE.md) — re-checked after restyle**
- Every match card's sourcing context carries: Posted-by author, `#channel`,
  UTC timestamp, permalink (`View message`), tappable `Contact: <@id>`, and the
  `Verify before relying on this.` note. 3/3 cards in the multi-match probe. PASS.
- Workspace label scope: `WORKSPACE · REAL-TIME SEARCH` appears only on match
  cards; the empty/degraded replies carry no rank label. Offer ack uses the
  distinct `INDEXED · WORKSPACE MEMORY` label. Correct scoping.

**Acceptance criteria**
- [x] PASS — AC1 code-composed parse-summary `fields` (need_type/location/urgency/
      household) from the Need, unknown fields omitted, no placeholders, ≤10 fields
      — `recall/blocks.py:105-130`; tests `test_blocks.py::test_parse_summary_*`
      (5 tests) + `test_reply.py::test_need_reply_opens_with_code_composed_parse_summary`;
      adversarial break paths 1-3,7 confirm omission/verbatim behaviour.
- [x] PASS — AC2 per-card rank label `🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH` +
      colored-square left-bar cue, divider grouping preserved — `recall/blocks.py:199-230`;
      tests `test_each_match_has_a_workspace_rank_label`, `::test_rank_label_uses_colored_square_as_left_bar_cue`,
      `::test_rank_label_numbering_caps_with_rendered_matches`, `::test_multiple_matches_are_divider_separated`;
      break path 6 confirms numbering MATCH 1..5 + truncation.
- [x] PASS — AC3 official MCP items stay LLM prose (not intercepted by this module);
      blue/red MCP-card variants are documented future work — `recall/blocks.py:16-26,52-63`.
      No regression: this task only styles code-composed workspace blocks + parse fields.
- [x] PASS — AC4 every existing element kept — source/ts/permalink/Contact/verify on
      every card (sourcing-guardrail probe + `test_every_match_has_source_timestamp_and_verify`,
      `::test_every_match_has_contact_mention`); action buttons + 010 state machine
      untouched (17/17 crisis-button tests + `_update_card` trace above); top-5 cap +
      "Showing top N of M"; degraded/empty stay explicit and now lead with the parse summary.
- [x] PASS — AC5 tests updated/extended, zero warnings — 197 unit passed,
      `filterwarnings=error`; offer ack opens with aligned `INDEXED` label, no actions
      (`test_matching_blocks.py::test_ack_opens_with_indexed_workspace_rank_label`,
      `::test_ack_has_no_action_buttons`; break path "offer ack" confirms).
- [ ] [HUMAN] — Acceptance line: side-by-side screenshot of landing-page card vs
      live Slack card. AWAITING HUMAN VERIFICATION — requires `slack run` against the
      sandbox in a TTY. Payload-level parity verified: the mock (`docs/site/index.html`)
      specifies MATCH 1/2, WORKSPACE + Real-Time Search, need_type/location/urgency/
      household, Connect me/Not relevant, Contact, verify-before, INDEXED, border-left —
      the implemented payload mirrors every textual element. The one delta (CSS
      `border-left` color bar → leading colored-square emoji) is the documented,
      SDK-justified substitution (no attachments hook on the streamed reply).

**Evidence**
```
$ make pre-commit
uv run ruff format --check  → 65 files already formatted
uv run ruff check           → All checks passed!
uv run pytest tests/unit    → 197 passed in 1.37s

$ make unit-tests           → 197 passed in 1.25s   (double-run, identical)
$ make integration-tests    → 5 passed, 1 skipped in 0.87s
$ pytest tests/unit/listeners/actions/test_crisis_buttons.py → 17 passed (010 state machine)

$ adversarial probes (build_recall_blocks / build_offer_ack_blocks):
  all-unknown Need        → fields=['*urgency*\nlow']           (sane, no placeholder)
  empty/unknown location  → location omitted, no '?'
  household_size=-3       → household omitted
  zero matches + need     → [section(parse), section(no-matches)]
  degraded + need         → [section(parse), section(unavailable)], no actions
  8 matches               → MATCH 1..5, crisis_actions_0..4, "Showing the top 5 of 8 matches."
  hostile location/text   → verbatim from Need (code-composed)
  worst-case payload      → 28 top-level blocks (<50), 4 fields (<10)
  010 _update_card trace  → Connect@crisis_actions_1 swaps exactly 1 block; others untouched
  offer ack               → ['context'(🟩 INDEXED · WORKSPACE MEMORY),'section','context'], no actions
```

**Other issues found**
- None blocking. Note (non-blocking): `_parse_summary_block` can never return
  `None` in practice because `urgency` is a required `StrEnum` (always renders a
  field). The `if not fields: return None` guard is therefore dead in the current
  data model — harmless defensive code, not a defect. Flagging for the orchestrator
  to optionally route as a tidy-up; does not affect behaviour.

**VERDICT: PASS**
