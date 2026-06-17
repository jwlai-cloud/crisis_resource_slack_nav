"""Compose relevant official MCP feed items as sourced cards in the need reply.

The need reply renders **workspace** recall hits as source-stamped match cards
(:mod:`recall.blocks`). This module is the **official** equivalent (task 028,
ADR-0007): it renders the relevant *official* feed items — road closures, evac
centres / water points, advice — as their own "Official information" section
beneath the workspace matches.

It is a pure, deterministic ``(Need, SituationSnapshot) -> list[Block]`` render —
no I/O. The feeds it reads come from :func:`coordinator.situation.read_situation`
(the same snapshot the coordinator board renders), so sourcing, timestamps, and
degraded states are guaranteed by code, not by the model. The LLM still *plans*
and composes its prose; it no longer owns the official display.

Every guardrail the workspace cards honour, these honour too:

* **Every official item is sourced + timestamped.** Each card carries a context
  line ``feed: <name> · fetched <ABSOLUTE UTC>`` plus the standing verify note —
  the same who/when sourcing the workspace cards carry, but feed/fetched-at for an
  external source. The stamp is absolute UTC (``%Y-%m-%d %H:%M UTC``), never
  relative — it is the timestamp residents verify against.
* **Never assert safety.** The card relays the feed's own status word verbatim
  (e.g. a road "CLOSED"); this module never composes "safe to travel" of its own.
* **Degraded states are explicit.** A feed relevant to the need but
  ``available=False`` renders an explicit "⚠ <feed> unavailable — <detail>" card
  rather than being dropped (guardrail 4).
* **A human decides.** Official cards carry NO action buttons — you do not
  "Connect" to a road closure; they are informational only (guardrail 1).

**Relevance pruning by need_type** mirrors the system prompt's rule (agent/agent.py
OFFICIAL DIRECTORIES) and the board logic: a water/drinking/supply need surfaces
the water point(s); a travel/road/drive/safety need surfaces the road closure(s);
a shelter/evac/somewhere-to-stay need surfaces the evacuation centre(s); an
official-warning question surfaces the advice notice. If no feed is relevant to the
need, NO official section renders (``[]``) — never a dump of the full picture (the
no-noise rule, task 012).

The mock's colored *left bar* is rendered as a leading colored-square emoji, the
same top-level-safe cue :mod:`recall.blocks` uses for the green workspace card (the
streamed ``ChatStream.stop`` surface has no ``attachments`` hook). The official
variants reserved there are used here: 🟦 blue for info (evac centres / water points
/ advice), 🟥 red for advisories (road closures / warnings).
"""

from datetime import datetime

from slack_sdk.models.blocks import (
    Block,
    ContextBlock,
    HeaderBlock,
    MarkdownTextObject,
    PlainTextObject,
    SectionBlock,
)

from coordinator.situation import FeedRecord, SituationFeed, SituationSnapshot
from entities import Need
from mocks.server import EvacCentre, RoadClosure

# The standing verify-before-relying note, carried on every official card — the
# same wording the workspace cards use (:data:`recall.blocks.VERIFY_NOTE`).
VERIFY_NOTE = "Verify before relying on this."

# The explicit, plain user-facing alert for the WHOLE-path degraded-official case
# (task 034, Part C): the situation read failed entirely, or every official feed
# relevant to the need is down. Spoken in the resident's own terms — not a silent
# omission and not an implied-complete answer. It names the gap (the official
# directories are unreachable), refuses to judge current conditions, and points the
# resident to verify directly. Never asserts safety; never invents (guardrails 2/4).
OFFICIAL_UNAVAILABLE_ALERT = (
    "⚠ I couldn't reach the official directories right now, so I can't give you "
    "current road or official conditions. Please verify directly with the official "
    "source before relying on anything here."
)

# The section header the official cards sit beneath, distinct from the workspace
# matches header so the resident reads two clearly-labelled groups, not one
# cross-source ranking.
OFFICIAL_SECTION_HEADER = "Official information"

# Colored-square cues, the official counterparts to the green workspace bar
# (:data:`recall.blocks.WORKSPACE_BAR_EMOJI`). Blue = info (centres / water points /
# advice); red = advisory (road closures / warnings). The leading square stands in
# for the mock's colored left bar on the streamed reply surface.
OFFICIAL_INFO_BAR_EMOJI = "🟦"
OFFICIAL_ADVISORY_BAR_EMOJI = "🟥"

# The per-card rank/source label, the official counterpart to the workspace cards'
# `🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH`. The leading square is the bar cue;
# the kind word (INFO / ADVISORY) names which colour and the source is the MCP feed.
_RANK_LABEL = "{emoji} *OFFICIAL · {kind}* · MCP FEED"

# Cap on official items surfaced per need — keep the section to roughly two or
# three lines (the brevity rule mirrored from the system prompt), never the full
# picture. Applied across all relevant feeds combined.
_MAX_OFFICIAL_RECORDS = 3

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"


def _format_ts(ts: datetime) -> str:
    """Render an aware-UTC timestamp for on-screen display (deterministic, absolute)."""
    return ts.strftime(_TIMESTAMP_FORMAT)


def _need_keywords(need: Need) -> str:
    """The lowercased text the relevance map matches against.

    Drawn from the parsed need_type (what is being asked for) — the same field the
    system prompt's relevance rule keys on. Lowercased so the keyword tests below
    are case-insensitive.
    """
    return (need.need_type or "").lower()


# Relevance map (need_type keyword -> which feed answers it), mirroring the system
# prompt's OFFICIAL DIRECTORIES rule and the board logic. Each entry is a
# (keyword-set, feed-attribute) pair; a need whose keywords hit a set marks that
# feed relevant. Water/supply -> the water point lives on the evac centre's services
# (and any water/supply advice notice); travel/road/safety -> road closures;
# shelter/evac -> evac centres; official-warning -> advice.
_ROAD_KEYWORDS = (
    "road",
    "drive",
    "driving",
    "travel",
    "get to",
    "route",
    "safe",
    "safety",
    "passable",
)
_WATER_KEYWORDS = ("water", "drink", "drinking", "supply", "supplies", "thirsty")
_SHELTER_KEYWORDS = (
    "shelter",
    "evac",
    "evacuat",
    "stay",
    "sleep",
    "accommodation",
    "somewhere to",
    "refuge",
)
_WARNING_KEYWORDS = ("warning", "advice", "advisory", "alert", "official", "all clear")


def _matches(keywords: str, candidates: tuple[str, ...]) -> bool:
    """True if any candidate keyword is a substring of the need's keyword text."""
    return any(candidate in keywords for candidate in candidates)


def _is_water_relevant_advice(record: FeedRecord) -> bool:
    """True if an advice notice concerns water / drinking / supply (for a water need).

    A water need surfaces a water/supply advice notice (e.g. "Emergency water point
    now open") alongside the evac centre's water point — but not an unrelated notice
    (e.g. a generic power-outage warning). We test the notice's own title/advice text
    so the pruning stays content-driven, never a dump of every notice.
    """
    if not isinstance(record, RoadClosure | EvacCentre):
        haystack = f"{record.title} {record.message} {record.advice}".lower()
        return _matches(haystack, _WATER_KEYWORDS)
    return False


def _relevant_records(
    need: Need, situation: SituationSnapshot
) -> list[tuple[SituationFeed, FeedRecord]]:
    """Select the official records relevant to the parsed need, in display order.

    Returns ``(feed, record)`` pairs so each card can carry its feed's stamp. The
    relevance map (above) decides which feed answers the need; within a relevant
    available feed we take its records. Order is road (advisory) first when a travel
    need, then info feeds — but each need only pulls its mapped feeds, so a water
    need never surfaces the road list. Capped downstream to keep the section short.

    Available-but-empty feeds contribute nothing; a feed's *availability* (the
    degraded path) is handled separately in :func:`build_official_blocks` so a
    relevant-but-down feed is still named.
    """
    keywords = _need_keywords(need)
    pairs: list[tuple[SituationFeed, FeedRecord]] = []

    if _matches(keywords, _ROAD_KEYWORDS):
        feed = situation.road_closures
        if feed.available:
            pairs.extend((feed, record) for record in feed.records)

    if _matches(keywords, _WATER_KEYWORDS):
        evac = situation.evac_centres
        if evac.available:
            pairs.extend((evac, record) for record in evac.records)
        advice = situation.official_advice
        if advice.available:
            pairs.extend(
                (advice, record) for record in advice.records if _is_water_relevant_advice(record)
            )

    if _matches(keywords, _SHELTER_KEYWORDS):
        evac = situation.evac_centres
        if evac.available:
            # Avoid double-listing a centre already added by the water branch.
            existing = {id(record) for _, record in pairs}
            pairs.extend((evac, record) for record in evac.records if id(record) not in existing)

    if _matches(keywords, _WARNING_KEYWORDS):
        advice = situation.official_advice
        if advice.available:
            existing = {id(record) for _, record in pairs}
            pairs.extend(
                (advice, record) for record in advice.records if id(record) not in existing
            )

    return pairs


def _relevant_down_feeds(need: Need, situation: SituationSnapshot) -> list[SituationFeed]:
    """The feeds relevant to the need that are ``available=False`` (degraded, loud).

    A feed mapped to the need but down must be named explicitly (guardrail 4), not
    dropped. We collect each distinct relevant-but-down feed so the builder can
    render an explicit "unavailable" card for it. Order mirrors the relevance map.
    """
    keywords = _need_keywords(need)
    down: list[SituationFeed] = []
    seen: set[str] = set()

    def _consider(feed: SituationFeed) -> None:
        if not feed.available and feed.feed not in seen:
            seen.add(feed.feed)
            down.append(feed)

    if _matches(keywords, _ROAD_KEYWORDS):
        _consider(situation.road_closures)
    if _matches(keywords, _WATER_KEYWORDS):
        _consider(situation.evac_centres)
        _consider(situation.official_advice)
    if _matches(keywords, _SHELTER_KEYWORDS):
        _consider(situation.evac_centres)
    if _matches(keywords, _WARNING_KEYWORDS):
        _consider(situation.official_advice)

    return down


def _is_advisory(record: FeedRecord) -> bool:
    """True for an advisory-coloured (red) record: a road closure or a warning notice.

    Road closures are always advisory. An advice notice counts as an advisory when
    its own level reads as a warning (e.g. "Emergency Warning"); plain "Advice"
    notices and evac centres are info-coloured (blue). The card relays the feed's
    own words either way — the colour is a cue, never a safety judgement.
    """
    if isinstance(record, RoadClosure):
        return True
    if isinstance(record, EvacCentre):
        return False
    return "warning" in record.level.lower()


def _record_text(record: FeedRecord) -> str:
    """Render one feed record as its card's item text, dispatched by type.

    Mirrors the board's ``_row_for``: each record relays its own fields verbatim —
    the road's own status word + reason, the centre's status / occupancy / services
    (where a water point surfaces), the notice's level + advice line. This module
    states what the feed says; it never asserts of its own that a road is safe
    (guardrail 2).
    """
    if isinstance(record, RoadClosure):
        return f"*{record.road}* — {record.segment}: {record.status}. {record.reason}"
    if isinstance(record, EvacCentre):
        services = ", ".join(record.services) if record.services else "—"
        return (
            f"*{record.name}* ({record.address}) — {record.status}, "
            f"{record.occupancy}/{record.capacity}. Services: {services}"
        )
    return f"*{record.title}* ({record.level}) — {record.advice}"


def _feed_stamp(feed: SituationFeed) -> str:
    """The source line every official card carries: feed name + absolute-UTC fetched-at.

    This is the sourcing guardrail on the card — the feed it came from and when that
    lookup ran (aware UTC, absolute), the feed/fetched-at counterpart to the
    workspace card's who/when. A feed with no stamp (should not happen for an
    available feed) still names the feed.
    """
    if feed.fetched_at is None:
        return f"feed: {feed.feed}"
    return f"feed: {feed.feed} · fetched {_format_ts(feed.fetched_at)}"


def _rank_label_block(*, advisory: bool) -> ContextBlock:
    """The card's leading rank/source label: the colored-square cue + OFFICIAL · KIND.

    Blue/INFO for centres, water points, and plain advice; red/ADVISORY for road
    closures and warnings. The leading square stands in for the mock's colored left
    bar (the official counterpart to the workspace card's green bar).
    """
    emoji = OFFICIAL_ADVISORY_BAR_EMOJI if advisory else OFFICIAL_INFO_BAR_EMOJI
    kind = "ADVISORY" if advisory else "INFO"
    return ContextBlock(
        elements=[MarkdownTextObject(text=_RANK_LABEL.format(emoji=emoji, kind=kind))]
    )


def _record_card(feed: SituationFeed, record: FeedRecord) -> list[Block]:
    """The blocks for one official record: rank label, item text, source + verify line.

    The colored-square cue + `OFFICIAL · KIND` opens the card, then the relayed item
    text, then the source context line (feed + absolute-UTC fetched-at + the verify
    note). NO action block — official cards are informational (guardrail 1).
    """
    return [
        _rank_label_block(advisory=_is_advisory(record)),
        SectionBlock(text=MarkdownTextObject(text=_record_text(record))),
        ContextBlock(
            elements=[
                MarkdownTextObject(text=_feed_stamp(feed)),
                MarkdownTextObject(text=VERIFY_NOTE),
            ]
        ),
    ]


def _unavailable_card(feed: SituationFeed) -> list[Block]:
    """An explicit "feed unavailable" card for a relevant-but-down feed (guardrail 4).

    A feed mapped to the need but ``available=False`` is named, not dropped — the
    resident sees the source is down rather than a silently missing card. Rendered
    with the advisory (red) cue: a degraded source the resident was relying on is an
    advisory state, and it still carries the verify note.
    """
    detail = feed.detail or "No detail provided."
    return [
        _rank_label_block(advisory=True),
        SectionBlock(text=MarkdownTextObject(text=f"⚠ *{feed.feed}* unavailable — {detail}")),
        ContextBlock(elements=[MarkdownTextObject(text=VERIFY_NOTE)]),
    ]


def is_official_fully_unavailable(need: Need, situation: SituationSnapshot) -> bool:
    """True when official info is *fully* unavailable for this need (task 034, Part C).

    The whole-path degraded case: the need maps to at least one official feed, but
    every relevant feed is down — so there is NOT a single available, relevant record
    to surface. The reply must then carry the explicit :data:`OFFICIAL_UNAVAILABLE_ALERT`
    rather than imply a complete answer (guardrail 4).

    Distinguished from the *no-official-answer* case: a need that maps to no feed at all
    (e.g. "baby formula") has no relevant down feed either, so this is ``False`` — there
    is simply nothing official to say, not a degraded source. And an available-but-empty
    relevant feed is likewise ``False`` (it read fine, it just has nothing to report).
    """
    return not _relevant_records(need, situation) and bool(_relevant_down_feeds(need, situation))


def build_official_unavailable_blocks(need: Need) -> list[Block]:
    """The explicit alert section when the situation read failed *entirely* (task 034).

    Used by the need-reply composer when :func:`coordinator.situation.read_situation`
    could not be read at all (no snapshot) — there are no per-feed cards to render, so
    without this the reply would be silent on the official picture and *imply* a
    complete answer. Instead we render a loud, plain alert (the
    :data:`OFFICIAL_UNAVAILABLE_ALERT`) under the standing "Official information" header,
    carrying the verify note and NO action buttons (guardrail 1). Pure render, no I/O.
    Never asserts safety; never invents a status (guardrails 2/4).
    """
    return [
        HeaderBlock(text=PlainTextObject(text=OFFICIAL_SECTION_HEADER)),
        _rank_label_block(advisory=True),
        SectionBlock(text=MarkdownTextObject(text=OFFICIAL_UNAVAILABLE_ALERT)),
        ContextBlock(elements=[MarkdownTextObject(text=VERIFY_NOTE)]),
    ]


def build_official_blocks(need: Need, situation: SituationSnapshot) -> list[Block]:
    """Compose the "Official information" section for a need from the situation snapshot.

    Pure ``(Need, SituationSnapshot) -> list[Block]``: applies the need_type -> feed
    relevance map, selects up to :data:`_MAX_OFFICIAL_RECORDS` relevant records, and
    renders them as emoji-cue cards (blue info / red advisory) under an "Official
    information" header — each carrying its feed + absolute-UTC fetched-at + the
    verify note, and NO action buttons.

    A feed relevant to the need but ``available=False`` renders an explicit
    "unavailable" card rather than being dropped (guardrail 4). When EVERY relevant
    feed is down (no available relevant record at all), the section also leads with the
    explicit whole-path :data:`OFFICIAL_UNAVAILABLE_ALERT` so the reply states the gap
    loudly rather than implying a complete answer (task 034, Part C). If no feed is
    relevant — or every relevant feed is available-but-empty — NO section renders
    (``[]``): the no-noise rule (task 012), never a dump of the full official picture.
    """
    pairs = _relevant_records(need, situation)[:_MAX_OFFICIAL_RECORDS]
    down_feeds = _relevant_down_feeds(need, situation)

    if not pairs and not down_feeds:
        return []

    blocks: list[Block] = [HeaderBlock(text=PlainTextObject(text=OFFICIAL_SECTION_HEADER))]
    # Whole-path degraded: every relevant feed is down. Lead with the loud, plain alert
    # before the per-feed "unavailable" cards so the gap is unmissable (task 034 C).
    if not pairs and down_feeds:
        blocks.append(SectionBlock(text=MarkdownTextObject(text=OFFICIAL_UNAVAILABLE_ALERT)))
    for feed, record in pairs:
        blocks.extend(_record_card(feed, record))
    for feed in down_feeds:
        blocks.extend(_unavailable_card(feed))
    return blocks
