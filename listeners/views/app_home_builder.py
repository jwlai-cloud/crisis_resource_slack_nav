"""Compose the App Home tab as a branded Crisis Resource Navigator dashboard.

The Home tab is the first thing a resident, volunteer, or judge sees, so it states
the product, how to use it, the current official situation, and a link to the
coordinator board. It is deliberately a **pure composer**: ``state -> blocks``.
All I/O — reading the official feeds and the board canvas id — happens at the
handler boundary (:mod:`listeners.events.app_home_opened`) and is passed in, so a
Home render is total and unit-testable without a live feed or canvas.

Every guardrail the recall cards and the coordinator board honour, the Home tab
honours too (they hold on the Home tab as well):

* **A human always confirms** — the bounded-autonomy guardrail (g1) is stated up
  front as a feature of how to use the agent, not buried.
* **Every situation item is sourced + carries a verify note** — each row names the
  feed it came from and when that lookup ran (g3), and the section carries the
  standing verify-before-relying note.
* **Degraded feeds are named, never silent** — a feed that is down renders an
  explicit, named "feed unavailable" line (g4) rather than vanishing.
* **Never asserts safety** — the section relays what the official feeds say; it
  never states that a road is safe or that it is okay to travel.
"""

from datetime import datetime

from coordinator.situation import FeedRecord, SituationFeed, SituationSnapshot
from mocks.server import EvacCentre, RoadClosure

# The branded header + one-line "what it does" shown at the top of every Home tab.
_HEADER = "Crisis Resource Navigator"
_TAGLINE = (
    "Describe a need or an offer in plain language. I surface matching local "
    "offers and official updates from this workspace — each with its source and "
    "timestamp — and a human confirms every match."
)

# "How to use", with the bounded-autonomy guardrail (g1) stated as a feature.
_HOW_TO_HEADING = "*How to use*"
_HOW_TO_BODY = (
    ":writing_hand: *Post a need or an offer in plain language* — in a channel "
    "I'm in, or by messaging me directly. Examples: _“Family of 4, no "
    "power, need water”_ or _“I can offer a spare room in town.”_\n"
    ":mag: *I find matches* — relevant offers and notices already in this "
    "workspace, plus the current official situation, each stamped with its source "
    "and time.\n"
    ":white_check_mark: *A human always confirms* — I surface and rank options "
    "with a one-tap connect button; I never make a match, a placement, or any "
    "action on my own. You decide; verify details before relying on them."
)

# The Current situation section — relays the official picture, sourced + verify.
_SITUATION_HEADING = "*Current situation*"
_SITUATION_VERIFY_NOTE = (
    "Relayed from official feeds, not advice. Always verify the current situation "
    "with the official source before relying on it."
)
# Shown when an available feed has no current records — an explicit empty state.
_NO_SITUATION_RECORDS = "_No current entries._"

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"


def _format_ts(ts: datetime) -> str:
    """Render an aware-UTC timestamp for on-screen display (deterministic)."""
    return ts.strftime(_TIMESTAMP_FORMAT)


def _feed_stamp(feed: SituationFeed) -> str:
    """The source label every situation row carries: feed name + fetched-at (g3)."""
    if feed.fetched_at is None:
        return f"source: {feed.feed}"
    return f"source: {feed.feed} · fetched {_format_ts(feed.fetched_at)}"


def _row_for(record: FeedRecord, feed: SituationFeed) -> str:
    """Render one feed record as a feed-stamped Home row, dispatched by type.

    Each record relays its own fields verbatim — the road's own status word, the
    centre's occupancy + services (where a water point surfaces), the notice's
    advice line — and carries the feed stamp. It states what the feed says; it
    never asserts of its own that a road is safe or okay to travel (guardrail 2).
    """
    stamp = _feed_stamp(feed)
    if isinstance(record, RoadClosure):
        return f"• *{record.road}* — {record.segment}: {record.status}. {record.reason} _{stamp}_"
    if isinstance(record, EvacCentre):
        services = ", ".join(record.services) if record.services else "—"
        return (
            f"• *{record.name}* ({record.address}) — {record.status}, "
            f"{record.occupancy}/{record.capacity}. Services: {services} _{stamp}_"
        )
    return f"• *{record.title}* ({record.level}) — {record.advice} _{stamp}_"


def _feed_lines(label: str, feed: SituationFeed) -> list[str]:
    """The compact lines for one official feed: a label, then rows or a named-down line.

    A feed that is unavailable renders an explicit, *named* "feed unavailable" line
    rather than being dropped (degraded-states guardrail 4) — a reader sees the
    source is down, never a silently missing line. An available-but-empty feed
    renders an explicit empty-state line.
    """
    if not feed.available:
        detail = feed.detail or "No detail provided."
        return [f"*{label}*: _Feed unavailable: {feed.feed} — {detail}_"]
    if not feed.records:
        return [f"*{label}*: {_NO_SITUATION_RECORDS}"]
    return [f"*{label}*"] + [_row_for(record, feed) for record in feed.records]


def _situation_blocks(situation: SituationSnapshot) -> list[dict]:
    """The Current situation section: each feed sourced (g3) or named-down (g4).

    Renders the heading, a compact road / evac / advice snapshot, and a context
    verify note. Every present row is feed-stamped; every down feed is named
    explicitly. The whole section is omitted by the caller when no snapshot is
    available, so this is only ever called with a real snapshot.
    """
    lines: list[str] = []
    lines.extend(_feed_lines("Road closures", situation.road_closures))
    lines.extend(_feed_lines("Evacuation centres", situation.evac_centres))
    lines.extend(_feed_lines("Official advice", situation.official_advice))
    return [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": _SITUATION_HEADING}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{_SITUATION_VERIFY_NOTE}_"}],
        },
    ]


def _board_blocks(board_url: str) -> list[dict]:
    """The "Open the cases board" link block, rendered only when a url is known."""
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":clipboard: *<{board_url}|Open the cases board>* — every "
                    "community case grouped by status, plus the log of confirmed "
                    "human actions."
                ),
            },
        },
    ]


def build_app_home_view(*, situation: SituationSnapshot | None, board_url: str | None) -> dict:
    """Compose the branded App Home view — pure ``state -> blocks``.

    Args:
        situation: the current official picture (road closures / water points /
            evac centres), read at the handler boundary
            (:func:`coordinator.situation.read_situation`) and passed in. When
            supplied it renders a compact, sourced Current-situation section with a
            verify note and any down feed named (guardrails 3/4). When ``None``
            (a degraded or failed read) the section is omitted cleanly.
        board_url: a deep link to the coordinator board canvas, built at the
            handler boundary from the persisted canvas id. When present an "Open
            the cases board" link renders; when ``None`` it is omitted cleanly.
    """
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": _HEADER}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _TAGLINE}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": _HOW_TO_HEADING}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _HOW_TO_BODY}},
    ]

    if situation is not None:
        blocks.extend(_situation_blocks(situation))

    if board_url is not None:
        blocks.extend(_board_blocks(board_url))

    return {"type": "home", "blocks": blocks}
