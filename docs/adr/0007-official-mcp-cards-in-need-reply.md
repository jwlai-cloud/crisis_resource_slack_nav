# 0007. Official MCP results render as sourced cards in the need reply

**Status:** Accepted
**Date:** 2026-06-13

## Context

The need reply renders **workspace** recall hits as source-stamped Block Kit match
cards (`recall/blocks.py`): rank label, snippet, a who/where/when sourcing line, the
verify note, and the Connect / Not-relevant buttons. **Official** MCP feed results —
road closures, evac centres, water points, advice — reached the resident only as
**LLM prose** (system prompt §OFFICIAL DIRECTORIES instructed the model to call the
mock MCP tools and weave two or three pruned items into the reply text, rendered as
`feed / fetched-at`). `recall/blocks.py` even reserved the blue/red emoji cues as
"future work" for exactly this.

The landing demo (`docs/site/index.html`) shows official results as ranked,
source-stamped **cards** ("match 2 · official · MCP feed: Water point open…" and the
safety "warn card") — which is the design doc's stated intent ("ranked,
source-stamped matches" from external feeds) but was not built. Two problems with the
prose-only approach:

- **Sourcing/timestamp/degraded-state guarantees were model-dependent.** The four
  guardrails (sourced + timestamped, degraded loud, never assert safety, human
  decides) on the official items rode entirely on the LLM following the prompt. A
  drifting model could drop a feed stamp or an unavailable-feed line and nothing
  structural caught it.
- **Demo-vs-app divergence.** The shipped product looked materially different from the
  page selling it.

Task 029/030 (landed) broadened parsing so a crisis-relevant information/safety
question ("is the road to X safe?") classifies as a `Need` with `is_information=True`
and routes official-only (no workspace offer-recall, no Connect). That made the
headline safety scenario reach the reply pipeline — 028 then upgrades the official
answer for *both* the information path and the resource path from prose to cards.

The forks considered:

- **Rendering medium.** Slack message *attachments* (with a real colored left bar) vs
  a leading colored-square **emoji cue** in top-level blocks. The streamed reply
  finalises through `ChatStream.stop(blocks=...)`, which exposes no `attachments`
  hook, and the action-button state machine (task 010) rewrites cards by `block_id`
  within top-level blocks — burying rows in an attachment would break it. The
  workspace cards already use the emoji cue (🟩) for this reason. (User decision
  2026-06-13: keep the streamed unified reply; no attachments/CSS-bar rework.)
- **Who composes the cards.** LLM-emitted structured cards vs **deterministic** code
  composition from the situation snapshot. Deterministic wins the guardrails: the
  feeds the board already reads (`coordinator.situation.read_situation()` →
  `SituationSnapshot`, each `SituationFeed` carrying feed name + aware-UTC
  `fetched_at` + typed records, or `available=False` + `detail`) give code-guaranteed
  sourcing, timestamps, and degraded states.
- **Placement.** Interleave official items into the single workspace ranking vs a
  separate, labelled **"Official information"** section beneath the matches. A single
  cross-source ranking implies a comparability the two sources do not have (a road
  closure is not "ranked against" a neighbour's spare generator); a labelled section
  is honest and clearer.

## Decision

Render the relevant official feed items as a deterministic, sourced **"Official
information"** card section in the need reply, composed by code from the situation
snapshot — not emitted by the LLM.

- **New pure renderer** `recall/official_blocks.py`:
  `build_official_blocks(need, situation) -> list[Block]`. A pure
  `(Need, SituationSnapshot) -> blocks` function (no I/O), unit-testable, that applies
  a need_type → feed relevance map, selects up to ~3 relevant records, and composes
  emoji-cue cards under an "Official information" header.
- **Emoji-cue style, not attachments.** Each card opens with a leading colored-square
  cue — 🟦 blue for info (evac centres / water points / advice), 🟥 red for advisories
  (road closures / warnings) — the official counterpart to the workspace 🟩. Card =
  the item text (the feed's own fields verbatim, including a road's own status word)
  + a context line `feed: <name> · fetched <ABSOLUTE UTC, %Y-%m-%d %H:%M UTC>` + the
  standing verify note. **No action buttons** — you do not "Connect" to a road closure
  (guardrail 1). The section sits **beneath** the workspace matches.
- **Relevance map** (mirrors the system prompt + board logic): water / drinking /
  supply → water point(s) (evac services + water/supply advice); travel / road / drive
  / safety → road closure(s); shelter / evac / somewhere-to-stay → evac centre(s);
  official-warning → advice. Capped at ~3 items. **No relevant feed → no section**
  (`[]`) — never a dump of the full official picture (the no-noise rule, task 012).
- **Both route paths get cards.** The information-need branch (task 030, previously
  empty blocks) now renders the official cards *as* its structured content (the LLM
  prose leads). The resource-need branch appends the official cards beneath the
  workspace match blocks. `listeners/recall_reply.py` reads the situation best-effort
  (wrapped like the board's `_read_situation_best_effort`) on both paths.
- **Degraded feeds stay loud (guardrail 4).** A feed relevant to the need but
  `available=False` renders an explicit "⚠ `<feed>` unavailable — `<detail>`" card,
  never dropped. A read failure (or an unexpected raise) degrades to *no* official
  section — never breaking the need reply (the workspace matches + LLM prose always
  stand).
- **Prose defers to the cards.** The system prompt OFFICIAL DIRECTORIES section is
  trimmed: the model still consults the directories in its *plan* and applies the same
  relevance map, but it DEFERS the official *specifics* to the rendered cards rather
  than re-listing closures / centres / water points in prose. The plan-step consult
  and the degraded-by-name honesty are retained. A new SAFETY QUESTIONS rule makes a
  road/travel SAFETY question LEAD with an explicit "I can't tell you whether it is
  safe — I don't make that call" refusal before the official info — scoped to
  road/travel safety, not over-applied to plain where/what/status info needs.

## Consequences

- **The four guardrails on official items are now code-guaranteed, not
  model-dependent.** Every official card is sourced (feed name) + timestamped
  (absolute UTC fetched-at) + verify-noted, carries no action button (human decides),
  relays the feed's own status word verbatim (never an own-judgement safety
  assertion), and a relevant-but-down feed renders an explicit unavailable card. These
  hold whatever the LLM writes.
- **The app now matches the demo's official-card intent.** The page's honesty pass
  aligns the demo's official item shape (emoji-cue, absolute UTC) with what ships.
- **The situation snapshot is the single official-data swap point.** The cards read
  from `coordinator.situation.read_situation()`, the same reader the board uses, so
  when real MCP/government feeds replace the mocks, that one module changes and both
  the board and the cards follow — no second coupling (ADR consistent with
  `coordinator/situation.py`'s documented coupling).
- **No new dependency, no new scope, no persistence.** Pure render over an existing
  snapshot; the LLM still plans and composes its reasoning + the workspace-match
  narrative.
- **Best-effort, additive.** The official section never breaks the need reply: no
  relevant feed → no section; a read failure → no section. The workspace matches and
  the prose are the floor of the reply.
- **Parse broadening stays in 029/030.** This ADR assumes information/safety questions
  already parse as needs; it does not touch `agent/parsing.py` or `Need.is_information`.
