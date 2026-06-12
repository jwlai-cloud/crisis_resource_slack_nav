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
