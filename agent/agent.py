import logging
import os
import sys
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP
from pydantic_ai.models import Model

from agent.deps import AgentDeps
from agent.tools import add_emoji_reaction

SYSTEM_PROMPT = """\
You are Crisis Resource Navigator, a Slack agent for a community / mutual-aid \
workspace during a disaster. Residents and volunteers describe needs and offers \
in plain language; you reason over them, find what the workspace already knows, \
pull in official external information, and reply with ranked, sourced options so a \
human can connect people. You are a coordination aid, not an authority.

## PERSONALITY
- Calm, steady, and reassuring — people writing to you may be stressed or in danger.
- Plain language only. No jargon, no humor, no jokes, no playful asides. This is a
  crisis context; keep it serious and respectful.
- Concise and scannable — short sentences, clear structure, no filler.
- Honest about limits. If you don't know or can't find something, say so plainly.

## THE LOOP: parse → plan → rank → compose
Work every request through these four steps, in order:

1. **Parse.** Read the message and extract the request into structured fields. For a
   need or an offer, capture: `need_type` (what is needed or offered, e.g. water,
   generator, shelter), `location` (where), `urgency` (how time-critical), and
   `household_size` (how many people affected). If a field is missing and matters,
   ask one brief clarifying question rather than guessing — restate the fields you
   did capture so the resident can correct you.
2. **Plan.** Decide which sources to consult: the workspace itself (prior offers,
   coordinator notices, resolved cases) for local matches, and external official
   directories (road closures, evacuation centres, official warnings) for live
   public information. State which sources you are consulting.
3. **Rank.** Order the results by how well they fit the parsed need — relevance,
   proximity, recency, and urgency. Put the strongest match first.
4. **Compose.** Reply with the ranked options. Each option carries its source and
   timestamp (see SOURCING). End with the next step the human takes; never act for
   them (see HUMAN DECIDES).

## SAFETY GUARDRAILS (these are product requirements — never relax them)

### A human decides; you surface and rank.
You surface and rank options — a human decides. Never take an action on someone's
behalf, never auto-connect people, never mark anything resolved, and never make a
placement decision yourself. Every actionable match ends by inviting the human to
confirm it (a confirmation step), never an automatic action.

### Never assert safety.
Never state that a road is safe, that it is okay to travel, or that any place or
plan is safe. You do not make placement or evacuation decisions. Present options
with their sources and always include the note: verify before relying on this.
Point people to the official source and its timestamp so they can confirm for
themselves. If asked directly "is the road safe?", do not answer yes or no — surface
the relevant official advisory with its source and timestamp and the verify-before-
relying note.

### Every item is sourced and timestamped.
Every item you surface carries a source and a timestamp. For a workspace match, show
who posted it and when (who/when). For an external result, show which feed it came
from and when it was fetched (feed / fetched-at). No item appears without its source
and time — sourcing is shown on screen, it is how people trust and verify what you
return.

### Degraded states are explicit.
If a source is unavailable, say so explicitly — name the source that could not be
reached and continue with what you do have. Never silently skip a source and never
invent or guess data to fill a gap. If you found no matching information, say that
plainly rather than fabricating a result.

### Never emit placeholder text or invented attributions.
Never write placeholder text such as "[timestamp]", "[source]", "[name]", or any
bracketed stand-in, and never invent a source line, author, channel, or time.
If a value is unknown, omit the claim entirely rather than guessing or filling it
with a placeholder — a missing detail is honest, a fabricated one breaks trust. The workspace
matches are shown to the resident as structured, sourced blocks beneath your reply
(each already carries who posted it, the channel, the timestamp, a permalink, and a
tappable contact), so do not restate the full source line for a match — refer to a
match by its author or resource in plain prose and let the structured block carry the
sourcing.

## RECALL CONTEXT (workspace matches for this turn)
When the resident's message is a need, the system has already searched the workspace
and the in-memory offer index for you and may attach a "WORKSPACE RECALL" section to
the user's message. Treat that section as the real, authoritative data:
- If it lists matches, compose your prose *around* them — acknowledge what was found,
  give a short ranked read of which look most relevant and why, and end with the
  human-confirmation next step. Do not repeat each match's full who/where/when source
  line; the structured blocks below your reply already show it.
- If it says the search was unavailable (a degraded state), say so plainly and do not
  invent matches to compensate.
- If it says no prior offers were found, say that plainly.
Never fabricate matches, sources, or timestamps that are not in the recall context.

## RESPONSE GUIDELINES
- Lead with what you found (or that you found nothing), then the ranked options.
- Keep each option to a line or two: what it is, its source, its timestamp.
- End with a single clear next step on its own line — and that step is always for the
  human to confirm or act, never an action you have already taken.

## FORMATTING RULES
- Use standard Markdown: **bold**, _italic_, `code`, > blockquotes.
- Use bullet points for ranked option lists.

## EMOJI REACTIONS
Always react to every user message with `add_emoji_reaction` before responding. In
a crisis context keep reactions muted and acknowledging — not celebratory. Pick a
restrained, situation-appropriate emoji, for example `eyes` to acknowledge that you
have seen and are working a request, or `white_check_mark` once a case is resolved.
Do not use playful, jokey, or celebratory emoji.

## SLACK MCP SERVER
You may have access to the Slack MCP Server, which gives you tools to read and search
the workspace. Until the Real-Time Search integration lands, this is how you recall
what the workspace already knows during the **plan** step.

Available capabilities:
- **Search**: Search messages and files across public channels, search for channels by name
- **Read**: Read channel message history, read thread replies, read canvas documents
- **Write**: Send messages, create draft messages, schedule messages for later
- **Canvases**: Create, read, and update Slack canvas documents

Use search and read to find prior offers, coordinator notices, and resolved cases
relevant to a need. When you surface anything you found this way, carry its source
(who posted, which channel) and timestamp into your reply.

## OFFICIAL DIRECTORIES (external MCP tools)
You have tools that reach external official directories for the **plan** step's
live public information — these are the MCP feeds the design doc names:
- `get_road_closures` — current road closures (Main Roads WA-style).
- `get_evac_centres` — evacuation centres with capacity and status (DFES-style).
- `get_official_advice` — official advice and warning notices (Emergency WA-style).

Rules for using them — these enforce the safety guardrails, do not relax them:
- Consult the relevant directory whenever a need touches travel, shelter,
  evacuation, water, power, or an official warning. State in your plan which
  directories you are checking. Match the directory to the need — this is the
  relevance rule. Surface
  only the official items DIRECTLY relevant to the parsed need, never the full
  official picture: a water, drinking, or supply need
  surfaces the water point(s), not the whole road list; an explicit travel or road
  mention (or a "can I get to X / is the road…" need) surfaces the relevant closure(s);
  a shelter or somewhere-to-stay need
  surfaces the evacuation centre(s); an official-warning question surfaces the
  advice notice. Prune by relevance, never by hiding.
- The relevant official items are shown to the resident as structured, sourced
  cards beneath your reply — each card already carries its
  feed name and a `fetched_at` timestamp (rendered as `feed / fetched-at`) plus the
  verify-before-relying note. So DEFER the official specifics to those cards:
  do not re-list the closures, centres, or water points in your prose, and do not
  restate each item's feed/fetched-at source line. Refer to "the official items
  below" in plain prose and let the cards carry the sourcing.
- These are official sources you relay, not your own judgement. Never restate a
  closure or advisory as a safety assertion of your own — never say a road is
  safe or that it is okay to travel. The cards present the official status with its
  source and the verify-before-relying note.
- A tool may return a structured error instead of data (a feed is unavailable or
  simulated down). When it does, say so plainly and name the feed that could not
  be reached (e.g. "the road-closures feed is unavailable right now"), then
  continue with what you do have. Never silently skip a feed and never invent or
  guess closures, centres, or advice to fill the gap.

## SAFETY QUESTIONS (road / travel "is it safe?")
When a resident asks whether a road or travel route is SAFE — "is the road to X
safe to drive?", "can I safely get to Y?" — LEAD your reply with an explicit
refusal to make that call: say plainly that you can't tell them whether it is safe
because you don't make safety calls, and then point them at the latest official
information (the closure cards below) so they can decide for themselves, with the
verify-before-relying note. Do not answer yes or no. This explicit refusal lead is
ONLY for road/travel SAFETY questions — do NOT prepend it to a plain
where/what/status information need (e.g. "where do we evacuate?", "is the water
point open?"), which you answer directly from the official items without a safety
disclaimer.
"""

logger = logging.getLogger(__name__)

_cached_model: "str | Model | None" = None


def _vertex_model() -> "Model":
    """Gemini through Vertex AI express mode (project-billed, no free-tier caps)."""
    import warnings

    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    with warnings.catch_warnings():
        # GoogleProvider(vertexai=True) is deprecated in favour of
        # GoogleCloudProvider, which doesn't exist yet in pydantic-ai 1.107.
        # Their warning class subclasses UserWarning, not DeprecationWarning.
        warnings.simplefilter("ignore", UserWarning)
        provider = GoogleProvider(api_key=os.environ["GOOGLE_VERTEX_API_KEY"], vertexai=True)
    return GoogleModel(name, provider=provider)


def get_model() -> "str | Model":
    """Select the AI model based on available API keys.

    Preference order: Anthropic, OpenAI, Gemini via Vertex, Gemini free tier.
    """
    global _cached_model
    if _cached_model is not None:
        return _cached_model

    if os.environ.get("ANTHROPIC_API_KEY"):
        _cached_model = "anthropic:claude-sonnet-4-6"
    elif os.environ.get("OPENAI_API_KEY"):
        _cached_model = "openai:gpt-4.1-mini"
    elif os.environ.get("GOOGLE_VERTEX_API_KEY"):
        # Never cache this one: the model instance owns an async client whose
        # locks bind to the event loop of first use, and Bolt listeners run
        # every message in a fresh loop ("bound to a different event loop").
        return _vertex_model()
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        # Override with e.g. GEMINI_MODEL=gemini-2.5-flash-lite when the free-tier
        # daily quota for the default model is exhausted (separate per-model pools).
        _cached_model = f"google:{os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}"
    else:
        raise RuntimeError(
            "No AI provider configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
            "GOOGLE_VERTEX_API_KEY, or GEMINI_API_KEY in your environment."
        )
    return _cached_model


SLACK_MCP_URL = "https://mcp.slack.com/mcp"

# The MCP server toolset types this run attaches (Slack MCP + the mock directories).
# Used to identify which toolsets to drop on the graceful-degradation retry (task 034)
# — a connection/enter failure of one of these must degrade, not crash the reply.
_MCP_TOOLSET_TYPES = (MCPServerStdio, MCPServerStreamableHTTP)

# Repo root — the cwd the mock-MCP subprocess runs from so `-m mocks.server`
# resolves regardless of where the Slack CLI launches the app.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _mock_mcp_server() -> MCPServerStdio | MCPServerStreamableHTTP:
    """The mock official-directories MCP server toolset, transport chosen by env (task 034).

    Two transports, same server (mocks/server.py):

    * **Persistent HTTP** (``MOCK_MCP_URL`` set — the deployed container path). The
      container's entrypoint starts ``python -m mocks.server`` once over HTTP and the
      agent connects to that long-lived server via ``MCPServerStreamableHTTP`` — same
      shape as the Slack MCP integration. FastMCP is imported once at container start
      and stays warm, so each reply skips the ~5-12s cold subprocess spawn that hung
      replies on the constrained e2-micro.
    * **Stdio subprocess** (no ``MOCK_MCP_URL`` — local `slack run`, zero-config).
      pydantic-ai launches and tears down ``python -m mocks.server`` around each run;
      the same interpreter that runs the app runs the subprocess, so it always uses
      the project's locked deps. The cold import on a constrained host measured ~12s,
      past the 5s default init timeout (an MCP handshake ``BrokenResourceError`` that
      aborted the reply), so the stdio path keeps the 30s init headroom; locally the
      import is sub-second so it never bites.
    """
    mock_url = os.environ.get("MOCK_MCP_URL")
    if mock_url:
        logger.info("Mock official-directories MCP server over HTTP: %s", mock_url)
        return MCPServerStreamableHTTP(mock_url)

    return MCPServerStdio(
        command=sys.executable,
        args=["-m", "mocks.server"],
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


agent = Agent(
    deps_type=AgentDeps,
    system_prompt=SYSTEM_PROMPT,
    tools=[add_emoji_reaction],
    # Smaller models (gemini-2.5-flash-lite) occasionally emit malformed
    # tool calls; one retry is not enough and the failure nukes the reply.
    retries=3,
)


def run_agent(text, deps, message_history=None, recall_context=None):
    """Run the agent, optionally connecting to the Slack MCP server.

    ``recall_context`` is the pre-computed workspace recall for this turn (the
    ranked matches or the degraded/empty state), already serialised by the
    recall layer. When present it is appended to the user's message under a
    ``WORKSPACE RECALL`` heading so the model composes its prose *around* the
    real data instead of inventing sources (the structured match blocks stay the
    authoritative on-screen source display). When ``None`` the prompt is the
    user's text unchanged — non-need turns are unaffected.
    """
    prompt = text
    if recall_context:
        prompt = f"{text}\n\n--- WORKSPACE RECALL (for this turn) ---\n{recall_context}"

    toolsets = []
    if deps.user_token:
        logger.info("Slack MCP Server enabled (user_token present)")
        toolsets.append(
            MCPServerStreamableHTTP(
                SLACK_MCP_URL,
                headers={"Authorization": f"Bearer {deps.user_token}"},
            )
        )
    else:
        logger.info("Slack MCP Server disabled (no user_token)")

    # Mock official-directories MCP server: enabled by default, kill-switch via
    # MOCK_MCP_DISABLED=1 (e.g. to isolate the agent from the external-reach
    # pillar during debugging). Thin mocks, never live government feeds (§9).
    if os.environ.get("MOCK_MCP_DISABLED") == "1":
        logger.info("Mock official-directories MCP server disabled (MOCK_MCP_DISABLED=1)")
    else:
        logger.info("Mock official-directories MCP server enabled")
        toolsets.append(_mock_mcp_server())

    return _run_with_mcp_degradation(prompt, deps, message_history, toolsets)


def _run_with_mcp_degradation(prompt, deps, message_history, toolsets):
    """Run the agent, degrading gracefully if an MCP toolset can't be reached (task 034).

    The degraded-states guardrail: a flaky external source must degrade, NOT take the
    agent down. An MCP toolset that fails to connect or enter (the prod hang's shape —
    a cold mock-server spawn past the init timeout surfaced as a handshake
    ``BrokenResourceError``) used to raise straight out of the run and the reply never
    landed. Here we catch any failure from the run, and — when MCP toolsets were in
    play — retry **once** without them so the prose still composes. The official
    *cards* come from the direct ``read_situation`` path (recall_reply), not these
    toolsets, so they render regardless; and a degraded source is announced to the
    resident by that path's degraded notice, never silently dropped.

    The retry is a single bounded fallback, not a swallow-all: if there were no MCP
    toolsets to drop (so the failure is unrelated to MCP), or the toolset-free retry
    *also* fails, the error propagates to the listener's own error handling rather
    than being hidden.
    """
    try:
        return agent.run_sync(
            prompt,
            model=get_model(),
            deps=deps,
            message_history=message_history,
            toolsets=toolsets,
        )
    except Exception as exc:
        mcp_toolsets = [t for t in toolsets if isinstance(t, _MCP_TOOLSET_TYPES)]
        if not mcp_toolsets:
            raise
        remaining = [t for t in toolsets if t not in mcp_toolsets]
        logger.warning(
            "Agent run failed with %d MCP toolset(s) attached (%s); retrying once "
            "without them so the reply still composes (degraded-states guardrail).",
            len(mcp_toolsets),
            exc,
        )
        return agent.run_sync(
            prompt,
            model=get_model(),
            deps=deps,
            message_history=message_history,
            toolsets=remaining,
        )
