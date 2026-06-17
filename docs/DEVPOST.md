# Crisis Resource Navigator — Devpost submission

*Slack Agent Builder Challenge · Track: Slack Agent for Good*

Source-of-truth draft for the Devpost text fields, the video voiceover, and the
README pitch. Paste sections into the matching Devpost fields at submission.

---

## Elevator pitch (Devpost tagline field)

A Slack agent that turns a disaster-struck community's chaotic group chat into a
coordinated relief operation — matching needs to nearby offers via Real-Time Search
and to official resources via MCP, with a human always in the loop.

---

## Inspiration

In March 2026, Severe Tropical Cyclone Narelle cut Exmouth, Western Australia off
from the outside world: the only sealed road impassable, power and water down, the
airport destroyed. In an emergency like that, the coordination surface is almost
always the chat tool people already use — not a purpose-built system. And a group
chat has three failure modes exactly when they cost the most:

- **Offers and needs don't meet.** Both are free text, posted minutes apart, and
  scroll out of view. The family that needs a generator never sees that someone three
  streets over offered one an hour ago.
- **Official information is fragmented.** Road status, evac-centre capacity, and
  warnings live across separate government sites a stressed resident on a bad
  connection won't check.
- **Knowledge isn't reused.** A problem solved on day one is re-solved from scratch on
  day three because nobody can find the earlier thread.

A generic chatbot doesn't fix this. The value isn't conversation — it's *retrieval
and matching over live context*.

## What it does

A resident or volunteer describes a need (or an offer) in plain language, right in the
channel. The agent:

1. **Reasons** — parses the message into structured fields (need type, location,
   urgency, household size), distinguishing a *resource* need ("we need water") from an
   *information* need ("is the road to Learmonth safe?").
2. **Remembers** — searches the live workspace via the **Real-Time Search API** for
   relevant prior offers, coordinator notices, and resolved cases.
3. **Reaches out** — queries external official directories (road closures, evacuation
   centres, warnings) through **MCP servers**.

It replies with **one** Block Kit message: the parsed understanding, ranked workspace
matches (each stamped with who posted it and when), an "Official information" section
of source-and-timestamp cards, and **one-tap Connect / Mark resolved / Not relevant
buttons**. A human always confirms the actual match — the agent surfaces and ranks, it
does not decide.

Every confirmed action lands on a **coordinator Canvas** — a permanent "Community
Cases" tab showing every case by status (Open → Connected → Resolved), a dated
activity log of human-confirmed actions, and the current official situation. And every
resolved case feeds back into the workspace's searchable memory, so the community gets
*faster* at helping itself the longer the crisis runs.

## How we built it

- **Slack agent surface** — Bolt for Python on the native agent surface; all responses
  are composed **Block Kit**, never free text. Suggested prompts and a branded App Home
  dashboard make the first touch crisis-specific.
- **Reasoning** — a `pydantic-ai` Agent runs a parse → plan → rank → compose loop; the
  system prompt (version-controlled product code, guardrails included) drives it.
  Provider-agnostic (Claude / GPT / Gemini-via-Vertex).
- **Memory** — the **Real-Time Search API** (`assistant.search.context`) *is* the
  database. No vector store on our side: we build a keyword query from the parsed need,
  let Slack rank server-side, then re-rank for the crisis domain (need-fit first,
  7-day recency second, the requester's own echoes and the bot's posts filtered out).
- **External reach (two real MCP integrations).** (1) The agent wires **Slack's own
  MCP server** (`mcp.slack.com`, via `MCPServerStreamableHTTP` with the user token) as
  a toolset. (2) For the official directories it consumes our own **FastMCP** servers
  over `MCPServerStdio` — real MCP tools (`get_road_closures` / `get_evac_centres` /
  `get_official_advice`) the agent calls in its reasoning loop. **The MCP integration
  is real; the *data* is simulated** — the servers are backed by static JSON because
  live Main Roads WA / DFES feeds aren't publicly available, so the wiring is exactly
  what a real government feed would use. **We never claim live government data.** MCP is
  load-bearing: it carries the entire official-information half of every answer (the
  road-closure advisory, the water point, the evac centres) and the whole
  safety-question response — remove it and the agent can't tell you a road is closed.
  A downed feed returns a structured error, surfaced as an explicit "feed unavailable"
  line, never silence.
- **Durable board** — the coordinator Canvas is the channel canvas of the crisis
  channel; it survives restarts even though the matching index is in-memory, and
  repopulates from channel history on startup.

### The four safety guardrails (product requirements, pinned by regression tests)

1. **A human decides.** Every actionable match ends at a confirmation button — never
   an automatic action.
2. **Never assert safety.** Asked "is the road safe?", the agent refuses to make the
   call and instead surfaces the official closure status verbatim ("CLOSED",
   "UNDER ASSESSMENT") with a verify-before-relying note. It relays facts; it never
   says a road is safe or makes a placement decision.
3. **Everything is sourced and timestamped** — workspace matches (who/when) and
   official items (which feed / fetched-at), shown on screen.
4. **Degraded states are explicit** — a down feed or an empty result is stated plainly,
   never papered over with a guess.

## Challenges we ran into

- **Socket Mode vs serverless.** The agent runs an outbound WebSocket, so it can't
  scale to zero on a request-driven platform — it needs an always-on worker. We ship a
  one-image, two-target (GCE free-tier / Fly.io) deploy that's push-button.
- **Telling information needs from resource needs.** "Where can I get water?" *is*
  answerable by a neighbour's offer (resource); "is the road safe?" is not (official
  only). Conflating them surfaced irrelevant offers and a nonsensical Connect button —
  fixed by routing information needs to official sources only.
- **Real-Time Search is keyword, public-channel, and ~1-minute-lagged.** We learned to
  build it into the architecture honestly rather than fight it: RTS for recall, channel
  history for the durable board.

## Accomplishments we're proud of

All three required technologies are **load-bearing** — remove any one and the product
breaks. The safety posture is real, not cosmetic: the agent will refuse to tell you a
road is safe, every time, and every claim on screen carries its source. ~510 tests,
zero-warning CI on every change, each guardrail change re-verified.

## What's next

Multi-language support; SMS/voice fallback for residents off Slack; real government
data partnerships replacing the mock feeds (the single `read_situation` module is the
swap point); measurable impact metrics (needs matched, time-to-match, cases reused).

## Built with

Python 3.13 · Slack Bolt for Python · native Slack agent surface · Block Kit · Slack
Real-Time Search API · Model Context Protocol — Slack's MCP server + our own FastMCP
servers · pydantic-ai · Vertex AI / Anthropic / OpenAI · uv · ruff · pytest.
