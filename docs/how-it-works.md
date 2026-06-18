# How it works — technical explainers

Plain-language answers to the questions people actually ask about the build. Source material for the Devpost write-up and the demo voiceover. Interactive version: [`docs/site/index.html`](site/index.html).

## "Slack AI" vs the model we run

The hackathon technology called **Slack AI capabilities & Agent Builder** is the agent *platform*, not a hosted LLM. Slack provides the native agent surface — split-view panel, assistant threads, suggested prompts, streaming, app-agent identity, the native feedback buttons — and the bounded-autonomy design guidance our guardrails follow. The reasoning engine inside that surface is bring-your-own: ours is pydantic-ai with runtime model selection (`agent/agent.py:get_model()` — Anthropic > OpenAI > Gemini, switchable via env). The *surface* is Slack's; the *brain* is ours and swappable.

## How the search works (no vector DB)

Two thin layers, neither a vector search on our side:

1. **Keyword query → Real-Time Search.** The LLM parses the message into a typed `Need`; `recall/client.py` builds a plain keyword query (literally `"{need_type} {location}"`, e.g. `water generator North Exmouth`) and calls `assistant.search.context` with a user token + `team_id`. Slack matches server-side and returns relevance-ranked messages with author, channel, timestamp, permalink. We trust Slack's ranking as a first pass; its internals are not documented and we only rely on observed behavior.
2. **Local domain re-rank.** `recall/ranking.py` — pure, deterministic: keyword overlap against the need's type+location tokens (weight 0.7) + linear 7-day recency (0.3). Zero-overlap matches are dropped entirely (recency alone once floated Wordle scores into a water-and-generator request). Top 5 render with source, timestamp, permalink, verify note.

Differences vs the search bar: the bar is classic interactive search (modifiers, pagination, sees your DMs); `assistant.search.context` is agent-built (structured payloads for LLM context, **public channels only** — observed concretely when DM-posted offers were invisible to it). Both run as a user, so visibility scopes to that user either way.

## How MCP fits (two distinct roles)

1. **Slack's own MCP server — live today.** The template wires an `MCPServerStreamableHTTP` toolset at `https://mcp.slack.com/mcp`, authorized with the user token. With the token present, the LLM gets workspace tools (search messages/files, read channels/threads, send messages, manage canvases) — which is why replies cite real sources and timestamps instead of inventing placeholders. It currently overlaps with the code-level RTS recall; task 005 unifies the paths.
2. **Our mock MCP servers — the W3 milestone**, the design doc's "external reach" pillar. Thin FastMCP servers backed by static JSON under `mocks/` (road closures, evac centres, official advice), simulating Main Roads WA / DFES / Emergency WA directories. The agent consumes them exactly like Slack's MCP server — additional pydantic-ai toolsets — so the integration pattern is identical to wiring a real government feed, which is what's judged. We never claim live feeds in the demo.

W3 conventions (locked in CLAUDE.md): tool names `verb_noun` snake_case with Pydantic models for every argument/return; expected failures return structured error results, not exceptions — that is how the "degraded states are explicit" guardrail lands at the MCP layer (a downed feed becomes a named, visible degradation, never silence); every MCP result rendered with feed/fetched-at stamping + verify note, mirroring RTS's who/when.

**Demo beat:** resident posts a need → agent surfaces a local match (RTS) and an official update (MCP) side by side, both sourced — the three-technology story (agent surface + RTS + MCP, each load-bearing) the submission claims.

## The human-in-the-loop actions (W3)

The agent surfaces and ranks; a person decides. Every workspace match carries two buttons — **Connect me** and **Not relevant** — and nothing happens until a human clicks. **Connect me** opens a group DM between the requester and the offerer with a short sourced intro ("X needs …, Y offered … — verify details before relying on it"), then the card flips to **Mark resolved**. The requester's identity comes only from the click, never from the button payload, so the agent structurally cannot act on someone's behalf. Resolving an offer takes it out of future matching. Every button press lands one line in an append-only audit trail (actor, action, target, time) — the record that the human-decides guardrail leaves a trail.

## The coordinator board (W4)

Coordinators read a live **Slack Canvas** — "Crisis Resource Navigator — Community Cases" — that the agent keeps current. It has three parts:

- **Cases by status** — every offer grouped Open / Connected / Resolved, each row sourced (offerer + when).
- **Activity log** — the audit trail rendered with real names and the human resource ("Rosario Bennet connected the camp beds offer"), not internal ids.
- **Situation** — the current official picture (road closures, evac centres, official advice) pulled from the MCP feeds, each row feed-stamped with the verify note; a feed that's down is named explicitly, never silently dropped.

The board refreshes on every state change (an offer indexed, a button pressed). Because a Slack Canvas is persisted by Slack, the board is the **durable** record (ADR-0005) — it survives an agent restart even though the in-memory matching index does not, which is the project's answer to "where does the state live." The board write authenticates as the coordinator (a `canvases:write` user scope) and every update is best-effort: a Canvas API hiccup logs and never breaks the button action it is hooked into.
