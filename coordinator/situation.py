"""Read the official feeds into a board-renderable "situation" snapshot — the
*impure* fetch boundary for the coordinator board's Situation section (task 020).

The coordinator board (task 017) shows community cases + the audit log. This module
adds the other half of the coordinator picture: the current **official** situation —
road closures, water points, and evacuation centres — so a resident's reply can
point at the board instead of repeating the whole official dump.

**The coordinator -> mocks coupling (read this before swapping the data source).**
For the demo the *mock* feeds ARE the official data source. The three feed functions
in :mod:`mocks.server` (``get_road_closures`` / ``get_evac_centres`` /
``get_official_advice``) load static Exmouth / Cyclone Narelle JSON and return a
typed :class:`~mocks.server.FeedResult` (feed name + aware-UTC ``fetched_at`` +
records) or a :class:`~mocks.server.FeedError`. This reader calls those functions
*directly* — the JSON loader, not an MCP round trip (the board composes synchronously
and a stdio MCP session is the agent's path, not the board's). That direct call is
the deliberate, documented coupling: **when real MCP feeds replace the mocks, this
reader is the one module that changes** (point it at the MCP toolset / a feed
client). The rest of the board — the pure composer — only ever sees the normalized
:class:`SituationSnapshot` below, so nothing downstream has to change. We do not
abstract that swap behind an interface today (no premature abstraction — CLAUDE.md):
the coupling lives here, named, in one place.

**Best-effort, never raises** (the degraded-state guardrail, mirroring
:mod:`coordinator.names`). The feed functions already *return* a ``FeedError`` for
an expected outage rather than raising, but this reader also wraps every call so an
*unexpected* error still degrades that one feed to an explicit "unavailable" marker
instead of breaking the snapshot. A feed that is down becomes a named
:class:`SituationFeed` with ``available=False`` — never silence (guardrail 4); the
composer renders an explicit "feed unavailable" line for it.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from mocks.server import (
    EvacCentre,
    FeedError,
    FeedResult,
    OfficialAdvice,
    RoadClosure,
    get_evac_centres,
    get_official_advice,
    get_road_closures,
)

logger = logging.getLogger(__name__)

# A feed record is one of the three official-directory models.
FeedRecord = RoadClosure | EvacCentre | OfficialAdvice


@dataclass(frozen=True)
class SituationFeed:
    """One official feed, normalized for the board: stamped, or explicitly down.

    Carries the feed name and — on success — the aware-UTC ``fetched_at`` stamp and
    the records the composer renders (each itself carrying its own ``updated_at``).
    A feed that returned a :class:`~mocks.server.FeedError` (expected outage) or
    raised unexpectedly has ``available=False``, no ``fetched_at``, no records, and a
    human ``detail`` — the composer turns that into an explicit "feed unavailable"
    line rather than dropping the feed (guardrail 4).
    """

    feed: str
    available: bool
    fetched_at: datetime | None = None
    records: tuple[FeedRecord, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class SituationSnapshot:
    """The official situation at compose time: one :class:`SituationFeed` per source.

    The board composer receives this (passed in from the :mod:`coordinator.canvas`
    boundary, mirroring the names dict) and renders the Situation section. Fields are
    named for what they carry on screen: closures, evac centres, and the advice notices
    (water points are surfaced from whichever of evac centres / advice carries them).
    Every feed is always present — a down feed is a :class:`SituationFeed` with
    ``available=False``, never a missing attribute — so the section is never silently
    short a source.
    """

    road_closures: SituationFeed
    evac_centres: SituationFeed
    official_advice: SituationFeed


def _read_feed(feed: str, fetch: Callable[[], FeedResult | FeedError]) -> SituationFeed:
    """Call one feed function and normalize its result to a :class:`SituationFeed`.

    A :class:`~mocks.server.FeedResult` becomes an available feed carrying the
    fetch stamp and records; a :class:`~mocks.server.FeedError` (the expected outage
    path) becomes an explicit unavailable marker with its detail. An *unexpected*
    exception is caught and likewise degraded to unavailable — the snapshot is
    best-effort and never raises, so a single bad feed cannot break the board.
    """
    try:
        result = fetch()
    except Exception as exc:
        logger.warning("Situation feed %r raised unexpectedly; marking unavailable: %s", feed, exc)
        return SituationFeed(feed=feed, available=False, detail=f"Could not read the {feed} feed.")

    if isinstance(result, FeedError):
        logger.info("Situation feed %r unavailable: %s", feed, result.error)
        return SituationFeed(feed=feed, available=False, detail=result.detail)

    return SituationFeed(
        feed=result.feed,
        available=True,
        fetched_at=result.fetched_at,
        records=tuple(result.records),
    )


def read_situation() -> SituationSnapshot:
    """Read all three official feeds into a normalized, board-renderable snapshot.

    Calls the mock feed functions directly (see the module docstring on the
    coordinator -> mocks coupling and the real-MCP swap point) and normalizes each to
    a :class:`SituationFeed`. Best-effort throughout: a feed that is down — whether it
    *returned* a ``FeedError`` or raised — is recorded as an explicit unavailable
    marker, never dropped, so the composer can show the degraded source by name
    (guardrail 4). Never raises.
    """
    return SituationSnapshot(
        road_closures=_read_feed("road_closures", get_road_closures),
        evac_centres=_read_feed("evac_centres", get_evac_centres),
        official_advice=_read_feed("official_advice", get_official_advice),
    )
