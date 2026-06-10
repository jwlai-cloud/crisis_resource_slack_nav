# CLAUDE.md

Standing context for Claude Code working in this repo. Read this first, every session.

## What this is

**Crisis Resource Navigator** — a Slack agent for community / mutual-aid workspaces during a disaster. A resident describes a need in plain language; the agent reasons over it, finds relevant prior offers and notices already in the workspace (Real-Time Search API), pulls live external info through MCP servers (road closures, evac centres, official warnings), and replies with ranked, source-stamped matches and one-tap actions. A human always confirms the match.

Built for the **Slack Agent Builder Challenge** (Devpost), "Slack Agent for Good" track. Deadline **2026-07-13**. Demo scenario: Exmouth WA isolated by Severe Tropical Cyclone Narelle (Mar 2026).

## Source of truth

`crisis_resource_navigator_design_doc.md` is authoritative for scope, architecture, the build plan, and what's out of scope. If a request conflicts with the design doc, flag it before acting. The architecture is in `crisis_resource_navigator_architecture.svg`; the demo script in `crisis_resource_navigator_demo_script.md`.

## Tech stack

- **Slack agent** scaffolded via the Slack CLI (`slack create agent`), running on the native agent surface.
- **Bolt for Python** for events/listeners.
- **Block Kit** for all agent responses — the UI is composed Block Kit, not free-form.
- **Real-Time Search API** for in-workspace recall.
- **MCP servers** for external directories. For the hackathon these are *thin mocks* (static JSON behind the MCP protocol) — the integration pattern is what's judged; do not wire real government feeds.
- Sandbox provisioned through the Slack Developer Program.

## Repo conventions

- Work happens on `dev`. Keep commits small and scoped to a build-plan milestone.
- Don't invent exact CLI commands or file paths before scaffolding — run `slack create agent`, then update the "Commands" section below with the real ones.
- Secrets (Slack tokens, signing secret) go in `.env`, never committed. Confirm `.env` is gitignored before the first commit that touches config.
- Mock MCP data lives under `mocks/` (e.g. `mocks/road_closures.json`, `mocks/evac_centres.json`).

## Critical guardrails (do not relax these)

These are product requirements, not nice-to-haves. They come from the design doc's safety section.

- **The agent surfaces and ranks; a human decides.** Every actionable match goes through a confirmation step (an action button), never an automatic action.
- **Never assert safety.** The agent must not state that a road is safe, that it's okay to travel, or make a placement decision. It presents options with sources and a "verify before relying on this" note.
- **Every item is sourced and timestamped** — both RTS matches (who/when posted) and MCP results (which feed/when fetched). Sourcing is a UX and trust requirement, shown on screen.
- **Degraded states are explicit.** If an MCP source is unavailable, the agent says so rather than going silent or guessing.
- Keep the system prompt that enforces the parse → plan → rank → compose loop and these rules in version control; treat changes to it like code.

## Commands

*(Fill in after scaffolding — placeholders until then.)*

- Install deps: `TBD`
- Run locally against sandbox: `TBD`
- Deploy / run the agent: `slack run` (verify)

## Current milestone

See HANDOFF.md for where we are. Default starting point is **Week 1: scaffold + agent responding on the agent surface with a Block Kit reply skeleton.**
