"""Mock MCP server for the Exmouth / Cyclone Narelle official directories.

One thin FastMCP server, three tools — one per official directory the design doc
names (design doc §3/§9):

* ``get_road_closures``   — Main Roads WA-style closures.
* ``get_evac_centres``    — DFES-style evacuation-centre list with capacity.
* ``get_official_advice`` — Emergency WA-style advice notices.

Each tool loads its static JSON from this package and returns a typed
:class:`FeedResult` carrying the **feed name**, an aware-UTC **fetched_at**, and
the **records** — the on-screen sourcing the composed reply renders as
``feed / fetched-at`` plus a verify note (guardrail 3). Expected failures are
*returned* as a structured :class:`FeedError`, never raised: a missing/corrupt
data file, or a feed named in ``MOCK_FEED_DOWN`` (the demo's degraded-state cue),
both come back as a typed error so the agent states the degraded source by name
rather than going silent (guardrail 4).

Transport: two ways to run the same server (task 034). By default this module is
launched as a stdio subprocess by pydantic-ai's ``MCPServerStdio`` from
``agent.agent.run_agent`` (``python -m mocks.server``) — zero-config, the path
local `slack run` uses. When ``MOCK_MCP_HTTP_PORT`` is set it instead serves over
**HTTP** on ``127.0.0.1:<port>`` (``mcp.run(transport="http", …)``), a persistent,
long-lived server the agent connects to via ``MCPServerStreamableHTTP`` — so the
deployed container imports FastMCP once at startup and stays warm, rather than
paying a cold per-reply subprocess spawn. The same tool bodies are unit-tested
directly and the session is integration-tested via FastMCP's in-memory ``Client``.
"""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from fastmcp import FastMCP
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent

# Single source of truth for the wired feed names. Keys are the tool's feed name
# (and the JSON filename stem); values are the record model for that feed.
# Populated below once the record models are defined.


def _ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC.

    Mirrors ``entities.models._ensure_aware_utc``: a feed record's ``updated_at``
    is shown on screen and is the source timestamp residents verify against, so a
    naive value (which silently assumes local time) is rejected at the boundary.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("updated_at must be timezone-aware (UTC); naive datetimes are rejected")
    return value.astimezone(UTC)


class RoadClosure(BaseModel):
    """One Main Roads WA-style closure record."""

    road: str
    segment: str
    status: str
    reason: str
    detour: str
    updated_at: datetime

    _validate_updated_at = field_validator("updated_at")(_ensure_aware_utc)


class EvacCentre(BaseModel):
    """One DFES-style evacuation-centre record with capacity/status."""

    name: str
    address: str
    status: str
    capacity: int
    occupancy: int
    services: list[str]
    updated_at: datetime

    _validate_updated_at = field_validator("updated_at")(_ensure_aware_utc)


class OfficialAdvice(BaseModel):
    """One Emergency WA-style advice notice."""

    title: str
    level: str
    area: str
    message: str
    advice: str
    updated_at: datetime

    _validate_updated_at = field_validator("updated_at")(_ensure_aware_utc)


class FeedResult(BaseModel):
    """A successful feed read: feed name, fetch stamp, and the typed records.

    ``fetched_at`` is set at call time (aware UTC) — distinct from each record's
    ``updated_at`` — so the reply can show *when this lookup ran* alongside *when
    the underlying record last changed* (sourcing guardrail).
    """

    feed: str
    fetched_at: datetime
    records: list[RoadClosure | EvacCentre | OfficialAdvice]


class FeedError(BaseModel):
    """A feed that could not be read — the typed "degraded" result.

    Returned, never raised. ``error`` is a short machine code (``feed_unavailable``
    for a missing/corrupt data file, ``feed_down`` for the ``MOCK_FEED_DOWN``
    simulation); ``detail`` is a human-readable line. The agent states the
    degraded source *by name* (``feed``) rather than going silent (guardrail 4).
    """

    feed: str
    error: str
    detail: str = ""


# feed name -> record model. The single source of truth for what is wired.
FEEDS: dict[str, type[RoadClosure | EvacCentre | OfficialAdvice]] = {
    "road_closures": RoadClosure,
    "evac_centres": EvacCentre,
    "official_advice": OfficialAdvice,
}


def _down_feeds() -> set[str]:
    """Feed names forced down via ``MOCK_FEED_DOWN`` (comma-separated, lenient)."""
    raw = os.environ.get("MOCK_FEED_DOWN", "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


def _load_feed(feed: str) -> FeedResult | FeedError:
    """Load one official directory's static JSON into a typed result.

    Returns a :class:`FeedResult` on success or a :class:`FeedError` for every
    expected failure (simulated-down, missing file, corrupt JSON, schema drift) —
    never raises for those. ``fetched_at`` is stamped at call time.
    """
    model = FEEDS[feed]

    if feed in _down_feeds():
        logger.info("Feed %r simulated down via MOCK_FEED_DOWN", feed)
        return FeedError(
            feed=feed,
            error="feed_down",
            detail=f"The {feed} feed is unavailable (simulated outage).",
        )

    path = DATA_DIR / f"{feed}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = [model.model_validate(item) for item in raw]
    except (OSError, ValueError) as exc:
        # OSError: file missing/unreadable. ValueError: invalid JSON or a record
        # that fails validation (covers corrupt data and schema drift).
        logger.warning("Feed %r could not be read: %s", feed, exc)
        return FeedError(
            feed=feed,
            error="feed_unavailable",
            detail=f"Could not read the {feed} feed: {exc}",
        )

    return FeedResult(feed=feed, fetched_at=datetime.now(UTC), records=records)


mcp: FastMCP = FastMCP(
    "crisis-official-directories",
    instructions=(
        "Mock official directories for the Exmouth / Cyclone Narelle scenario: "
        "road closures, evacuation centres, and official advice. Every result "
        "carries its feed name and a fetched-at timestamp; surface both with a "
        "verify-before-relying note. A feed may return a structured error — state "
        "the degraded source by name."
    ),
)


@mcp.tool
def get_road_closures() -> FeedResult | FeedError:
    """Get current road closures (Main Roads WA-style) for the Exmouth scenario.

    Returns a FeedResult with the feed name, a fetched-at timestamp, and the
    closure records, or a structured FeedError if the feed is unavailable. Every
    surfaced closure must carry the feed name + fetched-at and a verify note; this
    server never asserts that a road is safe or open for travel.
    """
    return _load_feed("road_closures")


@mcp.tool
def get_evac_centres() -> FeedResult | FeedError:
    """Get evacuation centres (DFES-style) with capacity/status for the scenario.

    Returns a FeedResult with the feed name, a fetched-at timestamp, and the
    evacuation-centre records (capacity, occupancy, services), or a structured
    FeedError if the feed is unavailable. Surface the feed name + fetched-at and a
    verify note for every centre.
    """
    return _load_feed("evac_centres")


@mcp.tool
def get_official_advice() -> FeedResult | FeedError:
    """Get official advice notices (Emergency WA-style) for the scenario.

    Returns a FeedResult with the feed name, a fetched-at timestamp, and the
    advice notices, or a structured FeedError if the feed is unavailable. Surface
    the feed name + fetched-at and a verify note for every notice; present advice
    as official guidance to verify, never as a safety assertion of your own.
    """
    return _load_feed("official_advice")


# Localhost only: the HTTP mock is reached solely by the agent in the SAME container
# (deploy/entrypoint.sh), never exposed off-host — there is no inbound port to the box.
_HTTP_HOST = "127.0.0.1"


def _run() -> None:
    """Run the mock MCP server, choosing transport from the environment (task 034).

    When ``MOCK_MCP_HTTP_PORT`` is set, serve persistently over HTTP on
    ``127.0.0.1:<port>`` (the deployed container's warm, long-lived server the agent
    reaches via ``MCPServerStreamableHTTP``); otherwise fall back to the **stdio**
    default — the zero-config transport pydantic-ai's ``MCPServerStdio`` launches for
    local `slack run`. The FastMCP banner is suppressed either way: on stdio it is
    noise in the host app's logs, and we keep the container logs clean too.
    """
    port = os.environ.get("MOCK_MCP_HTTP_PORT")
    if port:
        logger.info("Mock MCP server starting over HTTP on %s:%s", _HTTP_HOST, port)
        mcp.run(transport="http", host=_HTTP_HOST, port=int(port), show_banner=False)
    else:
        # Launched as a stdio subprocess by pydantic-ai's MCPServerStdio. The banner
        # goes to stderr (not the stdio JSON-RPC channel) but is still noise.
        mcp.run(show_banner=False)


if __name__ == "__main__":
    _run()
