# Crisis Resource Navigator

Standing context for Claude Code working in this repo. Read this first, every session.

# The Why

**Crisis Resource Navigator** is a Slack agent for community / mutual-aid workspaces during a disaster. A resident describes a need in plain language; the agent reasons over it, finds relevant prior offers and notices already in the workspace (Real-Time Search API), pulls live external info through MCP servers (road closures, evac centres, official warnings), and replies with ranked, source-stamped matches and one-tap actions. A human always confirms the match.

Built for the **Slack Agent Builder Challenge** (Devpost), "Slack Agent for Good" track. Deadline **2026-07-13**. Demo scenario: Exmouth WA isolated by Severe Tropical Cyclone Narelle (Mar 2026).

# The What

## Source of truth

`crisis_resource_navigator_design_doc.md` is authoritative for scope, architecture, the build plan, and what's out of scope. If a request conflicts with the design doc, flag it before acting. The architecture is in `crisis_resource_navigator_architecture.svg`; the demo script in `crisis_resource_navigator_demo_script.md`; the design→build bridge in `HANDOFF.md`.

## Key Components

- **Slack agent** (repo root) — Bolt for Python app on the native agent surface, scaffolded from `slack-samples/bolt-python-starter-agent --subdir pydantic-ai` (see [ADR-0002](docs/adr/0002-pydantic-ai-agent-template.md)). `app.py` is the socket-mode entry point; the reasoning loop is a pydantic-ai `Agent` in `agent/agent.py` (system prompt lives there — it's product code, guardrails included); Slack listeners in `listeners/`. Template specifics: [`docs/pydantic-ai-template-notes.md`](docs/pydantic-ai-template-notes.md).
- **Mock MCP servers** ([`mocks/`](mocks/)) — thin FastMCP servers backed by static JSON (`mocks/road_closures.json`, `mocks/evac_centres.json`, …). The integration *pattern* is what's judged; never wire real government feeds.
- **Tests** ([`tests/`](tests/)) — `tests/unit/` and `tests/integration/`, mirroring the source tree once it exists.
- **Process docs** ([`docs/`](docs/)) — agent-team pipeline (`docs/PROCESS.md`), ADRs (`docs/adr/`).

## Project Structure

```
crisis_resource_slack_nav/
├── CLAUDE.md                  # this file
├── crisis_resource_navigator_design_doc.md   # source of truth
├── HANDOFF.md                 # design → build bridge; current milestone
├── pyproject.toml             # uv-managed deps + ruff + pytest config
├── Makefile                   # all dev verbs (install/test/lint/format/...)
├── .env.example               # config surface; real values in .env (gitignored)
├── mocks/                     # mock MCP servers + their static JSON data
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   ├── PROCESS.md             # agent-team workflow (read before /day or /night)
│   └── adr/                   # architecture decision records
├── tracker/                   # file-based task tracker (+ done/ archive)
├── manifest.json              # Slack app manifest (scopes incl. RTS search, assistant surface, MCP)
├── app.py                     # socket-mode entry point (`slack run` starts this)
├── app_oauth.py               # OAuth entry point — not used for the sandbox demo
├── agent/                     # pydantic-ai Agent: agent.py (system prompt + run loop), deps.py, tools/
├── listeners/                 # Bolt listeners: events/ (assistant thread, mentions, messages), actions/, views/
├── thread_context/            # per-thread conversation history store
└── .slack/                    # Slack CLI project config (config.json, hooks.json)
```

## Critical guardrails (do not relax these)

These are product requirements, not nice-to-haves. They come from the design doc's safety section.

- **The agent surfaces and ranks; a human decides.** Every actionable match goes through a confirmation step (an action button), never an automatic action.
- **Never assert safety.** The agent must not state that a road is safe, that it's okay to travel, or make a placement decision. It presents options with sources and a "verify before relying on this" note.
- **Every item is sourced and timestamped** — both RTS matches (who/when posted) and MCP results (which feed/when fetched). Sourcing is a UX and trust requirement, shown on screen.
- **Degraded states are explicit.** If an MCP source is unavailable, the agent says so rather than going silent or guessing.
- Keep the system prompt that enforces the parse → plan → rank → compose loop and these rules in version control; treat changes to it like code.

## Key Python Design Choices

Distilled from the `python-backend`, `uv-python`, `pyproject`, `ruff-python`, and `fastmcp-server` specs (squid scaffold plugin) — see those for rationale and depth.

- Python 3.12+ minimum. `uv` is the only package manager (never pip/poetry); `ruff` the only formatter + linter.
- Async for I/O-bound work (Slack API calls, MCP queries), sync for CPU-bound parsing/ranking.
- Type-annotate everything, including `-> None`. PEP 585 built-ins (`list[int]`), never `typing.List`.
- Datetimes timezone-aware, UTC by default — reject naive datetimes at every boundary. (Source timestamps are a product guardrail; get them right.)
- Infrastructure (Slack SDK, FastMCP) is imported directly, not abstracted — no premature interfaces.
- Config via `pydantic-settings` from `.env`; every var listed in `.env.example` with a safe dummy value.
- Entry-point scripts call the logging bootstrap at module level before any project import. Never `print()` in library code.

### Mock MCP servers (FastMCP)

- Tool names `verb_noun` snake_case (`get_road_closures`); Pydantic models for every argument and return.
- Expected failures return structured error results, not exceptions — this is how "degraded states are explicit" gets implemented at the MCP layer.
- Unit-test tool bodies directly; integration-test the session via FastMCP's test client.

### Writing Tests

- `tests/` mirrors the source tree 1:1. Files `test_*.py`, functions `test_*`, AAA pattern.
- Shared fixtures in `conftest.py`; mocking via `pytest-mock` (`mocker`), never hand-rolled.
- `@pytest.mark.parametrize` for table tests. **Zero warnings** — `filterwarnings = ["error"]`.
- Unit tests never touch real Slack or real network; infrastructure belongs in integration tests.

## Tech Stack

- **Python 3.12+** — `uv`, `ruff`, `pytest` (+ `pytest-asyncio`, `pytest-mock`).
- **Bolt for Python** (`slack-bolt`) for events/listeners; **Block Kit** for all agent responses — the UI is composed Block Kit, not free-form.
- **Slack CLI** for scaffold + run; sandbox provisioned through the Slack Developer Program.
- **Real-Time Search API** for in-workspace recall.
- **FastMCP** for the thin mock MCP servers.

### Access Documentation

Use the `context7` MCP server (when available in the session) to look up current docs for `slack-bolt`, Block Kit, the Slack CLI, and FastMCP — Slack's agent surface APIs are new and training data lags.

# The How

All core commands live in the [`Makefile`](Makefile). Prefer `make <target>` over ad-hoc shell invocations. Dependency manager: `uv` (`uv add <pkg>` runtime, `uv add --group dev <pkg>` dev; `uv.lock` is committed).

## Repo conventions

- Work happens on `dev`. Keep commits small and scoped to a build-plan milestone.
- Secrets (Slack tokens, signing secret) go in `.env`, never committed. `.env` is gitignored; new env vars also go in `.env.example` with dummy values.
- After `slack run` / `slack create agent` produce real commands and paths, update the **Commands** section and **Project Structure** above — don't leave them stale.
- If the Slack CLI template ships a `requirements.txt`, migrate its deps into `pyproject.toml` via `uv add` during W1 — one dependency surface.

## Agent Team & Pipeline

Opinionated agent-team workflow in two modes. Canonical lifecycle and rules live in [`docs/PROCESS.md`](docs/PROCESS.md); read it before invoking either pipeline.

- **`/day [task]`** — supervised single-task pipeline. SWE → Tester → you commit.
- **`/night [feature]`** — unattended pipeline: PM groom → SWE → Tester → PM accept → push → On-Call CI + PR Reviewer.

**Tracker:** file-based — see [`tracker/README.md`](tracker/README.md). Tasks are `tracker/NNN-slug.{todo,groomed,in-progress}.md`, archived to `tracker/done/`.

**When to use which:** direct chat for trivial edits and questions; `/day` for a single milestone task with the Tester gate; `/night` for a full build-plan week's feature.

## Commands

| Target | What it does |
|---|---|
| `make install` | `uv sync` + install pre-commit hooks. |
| `make test` | Full pytest suite. (`make unit-tests` / `make integration-tests` for subsets.) |
| `make lint-check` / `make lint-fix` | `ruff check` / `ruff check --fix`. |
| `make format-check` / `make format-fix` | `ruff format --check` / `ruff format`. |
| `make pre-commit` | format-check + lint-check + unit tests. |
| `make ci` | Full pre-PR fan: install → format/lint checks → tests. |
| `make run` | `slack run` against the sandbox. |
| `make board` | (Re)create the coordinator board Canvas on demand (`scripts/open_board.py`). Needs `SLACK_USER_TOKEN` (user `canvases:write`). The board then auto-refreshes on every Connect / Resolve / Dismiss within the running agent process (task 017, ADR-0005). |

> **Manual QA order:** `format-fix → lint-fix → format-check → lint-check → pre-commit → unit-tests`. Fixers before checkers. CI runs the non-fix variants only.

Slack CLI (v4.2.0, installed at `~/.local/bin/slack`):

- `slack run` — start the agent in socket mode against the sandbox; injects `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` automatically. First run prompts to install the app into a workspace (needs a real TTY — run in your own terminal, not through an agent).
- `slack auth list` — verify auth. Logged into the `crisis-resource-nav` sandbox org (Team `E0B9Z77AX2R`).
- `slack manifest validate` — check `manifest.json` after editing scopes/events.
- `.env` needs `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) — pydantic-ai picks the model in `agent/agent.py:get_model()`.
- `CRISIS_CHANNEL` (optional, channel id; empty/unset = off) — enables passive listening (parse every top-level message, ack offers / answer needs) in that one channel only; everywhere else stays mention-gated (ADR-0004).

## Step-by-Step Verification

Standard per-change verification (format/lint, pre-commit, tests, running the feature) is enforced by the SWE and Tester contracts under `/day` and `/night`. Project-specific additions:

- **Any change to agent responses:** verify the Block Kit payload renders (Block Kit Builder or live `slack run`) — composed blocks, with source + timestamp on every item.
- **Any change to the agent system prompt:** it's version-controlled product code — test against live runs before committing.
- **Any change touching guardrails** (confirmation step, sourcing, degraded states): re-check the four guardrails above explicitly; a Tester PASS that skips them is a FAIL.

## Documentation Conventions

- **ADRs.** Architecture Decision Records live at [`docs/adr/`](docs/adr/) as `NNNN-kebab-title.md`, four-section Nygard template (Status / Context / Decision / Consequences). Every non-obvious architectural choice (matching-index location, RTS query strategy, MCP transport) ships with one. ADR-0001 explains the convention. Decisions already settled in the design doc don't need ADRs — only deviations and new forks do.

## Current milestone

See `HANDOFF.md`. Default starting point is **Week 1: scaffold via `slack create agent` + agent responding on the agent surface with a Block Kit reply skeleton.** Build order: W1 foundation → W2 reasoning + RTS → W3 MCP + actions → W4 polish + safety → W5 demo + submit.
