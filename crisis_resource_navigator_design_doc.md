# Crisis Resource Navigator — Design Doc

*Slack Agent Builder Challenge · Track: Slack Agent for Good · Deadline: Jul 13, 2026*

*Status: **shipped as v1.0.0**, deployed always-on in the judging sandbox — [live agent](https://app.slack.com/client/E0BBDPVAA06/C0BBCTGUKU5) · [field-guide page](https://jwlai-cloud.github.io/crisis_resource_slack_nav/) · [code](https://github.com/jwlai-cloud/crisis_resource_slack_nav).*

---

## Abstract

When a disaster isolates a community, coordination collapses into chaotic group chats. Offers of help, official advice, and urgent needs all scroll past each other in the same channel, and the person who needs a generator never sees that someone three streets over offered one an hour ago.

**Crisis Resource Navigator** is a Slack agent for community and mutual-aid workspaces during emergencies. A resident or volunteer describes a need in plain language; the agent reasons over it, finds what the workspace *already* knows using the Real-Time Search API, pulls live external information (road closures, evacuation centres, official warnings) through MCP servers, and replies with ranked, source-stamped matches and one-tap actions to connect people. Every resolved case feeds back into the workspace's searchable memory, so the community gets faster at helping itself the longer the crisis runs.

It is grounded in a real event: in March 2026, Severe Tropical Cyclone Narelle cut Exmouth, WA off from the outside world — the only sealed road impassable, power and water down, the airport destroyed. That is the scenario the demo recreates.

### One-liner (for the Devpost text field)
> A Slack agent that turns a disaster-struck community's chaotic group chat into a coordinated relief operation — matching needs to local offers via Real-Time Search and to official resources via MCP, with a human always in the loop.

---

## 1. Problem

In an isolated-community emergency, the coordination surface is almost always an existing chat tool, not a purpose-built system. That surface has three failure modes:

- **Offers and needs don't meet.** Both are posted as free text, minutes apart, and scroll out of view. Matching is manual and depends on someone happening to remember.
- **Official information is fragmented.** Road status, evac-centre capacity, and weather warnings live across separate government sites that a stressed resident on a bad connection won't check.
- **Knowledge isn't reused.** A problem solved on day one is re-solved from scratch on day three because nobody can find the earlier thread.

A generic chatbot doesn't fix this — the value isn't conversation, it's *retrieval and matching over live context*.

## 2. Solution overview

The agent does three things a chatbot can't:

1. **Reasons** over a plain-language need and decomposes it into structured fields (need type, location, urgency, household size).
2. **Remembers** — searches the live workspace for relevant prior offers, coordinator notices, and resolved cases.
3. **Reaches out** — queries external directories for official, time-sensitive information.

It then ranks the results, composes a single Block Kit reply with each item's source and timestamp, and offers one-tap actions. A human always confirms the actual match; the agent surfaces and ranks, it does not decide.

## 3. How it uses the three required technologies

The design maps one technology to each capability, so the project can credibly claim all three (only one is required).

- **Slack AI capabilities / Agent Builder — the reasoning + interface layer.** Built as a Slack agent on the native agent surface (split-view, text streaming, suggested prompts). This is what interprets free-text needs and runs the plan/rank/compose loop, following Slack's trust / transparency / bounded-autonomy design guidance.
- **Real-Time Search API — in-workspace memory.** Surfaces prior offers, coordinator updates, and resolved cases already in the workspace. This is the self-maintaining knowledge layer; there is no wiki to curate.
- **MCP servers — external directories.** Bring live external data into the agent's toolset: DFES / Emergency WA advice, Main Roads WA closures, BoM feeds, evac-centre capacity, 211-style service listings.

Combining MCP + RTS to reason over live workspace context is exactly what the hackathon resources nudge experienced devs toward, and it is the strongest claim for the **Best Technological Implementation** prize.

## 4. Architecture

See `crisis_resource_navigator_architecture.svg`. Flow summary:

```
Agent surface (need posted)
        ↓
Crisis Navigator Agent  [Slack AI]
   parse → plan → rank & compose → (human confirms)
        ↓                    ↓
RTS API  [workspace]     MCP servers  [external]
   prior offers,            road closures,
   coordinator notices,     evac centres,
   resolved cases           DFES/BoM feeds
        ↓                    ↓
        →  Block Kit response (sourced, timestamped, actionable)  →
                 ↓
        resolved cases loop back into RTS
        Coordinator Canvas + audit log
```

**As shipped.** Two real MCP integrations run on every reply: Slack's own MCP server (`mcp.slack.com`, via `MCPServerStreamableHTTP` + the user token) and our official-directories server (FastMCP), the latter kept **warm over HTTP inside the container** so each turn hits a live server instead of a cold subprocess. The agent runs **always-on** on a free-tier GCE e2-micro (Socket Mode = one long-lived outbound worker, ~200 MiB RAM). If an MCP source is unreachable it retries without that toolset and states the degradation explicitly — the official cards still render. The matching index is in-memory and repopulates from channel history on start. **~540 tests, zero-warning CI.** The MCP *data* is simulated (static JSON — live Main Roads WA / DFES feeds aren't public); the *integration* is real.

## 5. Core user flows

**Resident requests help.** Posts "Family of 4, North Exmouth, no power — need water and a generator." Agent parses, queries RTS (finds a generator offer 2h ago) and MCP (finds the nearest open water point), replies with both, ranked, each sourced. Resident taps **Connect me**, which DMs the offerer. On success, taps **Mark resolved**.

**Volunteer offers a resource.** Posts "I've got a spare 2kW generator in town." Agent acknowledges, structures and indexes the offer so RTS can match future needs against it.

**Coordinator oversight.** A Canvas shows the live board of open / matched / resolved needs. Every agent action is logged with its source, giving an audit trail appropriate to a high-stakes context.

## 6. Lightweight data model

The agent stays mostly stateless and leans on the workspace as the store, but a thin index helps matching:

- **Need**: id, requester, need_type, location, urgency, household_size, status (open/matched/resolved), source_ts.
- **Offer**: id, offerer, resource_type, location, availability, status, source_ts.
- **Resolution**: need_id, offer_id, confirmed_by, timestamp.

RTS handles free-text recall over the channel history; the index exists only to make need↔offer ranking fast and to drive the coordinator Canvas.

## 7. Build plan (≈5 weeks to Jul 13)

| Week | Milestone | Output |
|------|-----------|--------|
| **W1 (Jun 10–16)** | Foundation | Dev Program sandbox provisioned; `slack create agent` scaffold running; agent responds in-thread on the agent surface; Block Kit reply skeleton renders. |
| **W2 (Jun 17–23)** | Reasoning + RTS | Need/offer parsing into structured fields; RTS integration retrieving and ranking prior offers/notices; offer indexing on post. |
| **W3 (Jun 24–30)** | MCP + actions | One or two mock MCP servers (road closures, evac centres as JSON behind the MCP protocol); action buttons (Connect / Mark resolved / Escalate / Log) wired end-to-end. |
| **W4 (Jul 1–7)** | Polish + safety | Coordinator Canvas + audit log; sourcing/timestamps/"verify" framing on every item; bounded-autonomy confirm step; seed the Exmouth scenario data. |
| **W5 (Jul 8–13)** | Demo + submit | Record 3-min video (first 60s = the cyclone scenario, need→match→connect); architecture diagram final; write-up; grant sandbox access to the required reviewer emails; submit. |

Buffer is deliberately front-loaded into W1–W2 because sandbox/agent-surface setup is the most likely place to lose time; the mock MCP servers in W3 are intentionally thin.

**Delivered.** All five milestones shipped and were verified live in the sandbox at each step (W2–W4 landed ahead of schedule). The demo runs in a personal Slack Developer **event sandbox** with the agent deployed always-on, so judges can interact with it directly.

## 8. Demo plan

~3 minutes. Open cold on the real scenario — a few seconds of the Narelle headlines, then cut straight to the workspace. Show a resident posting a need and the agent returning a *local* match (RTS) and an *official* update (MCP) side by side, sourced. Tap Connect, show the DM fire. Tap Mark resolved, show it land on the coordinator Canvas. Close on the feedback loop: a second, similar need now resolves faster because the first case is in RTS. Keep the first 60 seconds entirely on the working product — judges weigh those most.

## 9. Risks & mitigations

- **No real public MCP servers for DFES/Main Roads by the deadline.** Stand up thin mock MCP servers backed by static JSON. The integration *pattern* is what's judged; do not claim live government feeds in the video.
- **Accuracy / liability in a real emergency.** The agent surfaces and ranks vetted options with sourcing and a "verify before relying" note; it never asserts a route is safe or makes a placement decision. This is baked into the prompt and the demo script, and aligns with Slack's bounded-autonomy guidance.
- **RTS recall quality on sparse early data.** Seed the demo workspace with realistic offers/notices so matching has something to work with; show the cold-start case honestly.
- **Scope creep.** Anything beyond need↔offer matching + official lookup + the Canvas is out for v1 (see below).

## 10. Out of scope for v1

Multi-language support, SMS/voice fallback for residents off Slack, real government data partnerships, predictive resource allocation, and authentication of offerers' identities. All are credible "what's next" talking points for the write-up without being build commitments.

## 11. Judging-criteria alignment

- **Technological Implementation** — uses all three required technologies, each load-bearing; clean separation of reasoning / memory / external data.
- **Design** — native agent surface, Block Kit responses, coordinator Canvas; balanced front/back end.
- **Potential Impact** — disaster-response coordination is high-stakes and broadly applicable beyond any one town; measurable (needs matched, time-to-match, cases reused).
- **Quality of Idea** — not a chatbot wrapper; the RTS-as-community-memory + feedback loop is the novel core.
