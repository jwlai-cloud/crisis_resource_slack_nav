"""Compose the coordinator board as Canvas markdown — the pure *render* step.

The coordinator board (task 017) is a Slack Canvas a coordinator reads to see, at
a glance, every community case grouped by lifecycle status plus the dated activity
log of every human-confirmed action. This module turns the two in-memory state
sources — the matching index (:func:`~matching.index.OfferIndex.all_offers`) and
the audit trail (:func:`~matching.audit.AuditTrail.list_events`) — into the
Canvas's ``document_content`` markdown string.

It is deliberately **pure and Slack-free**: ``state -> markdown``. The publisher
(:mod:`coordinator.canvas`) owns the API call; this module owns only the text, so
the whole composition is unit-testable without a live Canvas. The Canvas
``canvases.edit`` ``replace`` operation overwrites the entire document, so we
always recompose the full board from current state rather than diffing sections.

Every guardrail the cards honour, the board honours too:

* **Every case row is sourced + timestamped** — offerer, origin, and the offer's
  post time, the same trust-critical fields the recall cards surface.
* **Every audit line carries actor / action / target / when** — read straight
  from the audit trail, which only the human-confirmed buttons write. The board
  shows confirmed human actions only; it never renders an auto-action.
* **Never asserts safety.** The board is a record, not advice — it states what was
  offered and what a human did, and carries the standing verify note. It never
  says a road is safe or a placement is okay.
"""

from datetime import datetime

from entities import Offer, Status
from matching.audit import AuditEvent

# Title of the standalone canvas. Used both as the create-time title and as the
# stable handle a coordinator looks for ("the Community Cases board").
BOARD_TITLE = "Crisis Resource Navigator — Community Cases"

# The verify-before-relying guardrail, shown once at the top of the board (the
# same standing note the recall cards carry per item).
VERIFY_NOTE = (
    "_This board is a record of human-confirmed actions, not advice. "
    "Verify any detail before relying on it._"
)

# Status sections render in lifecycle order, each with its on-screen heading. A
# matched offer is "connected"; resolved is "closed".
_STATUS_ORDER: tuple[tuple[Status, str], ...] = (
    (Status.OPEN, "Open"),
    (Status.MATCHED, "Connected"),
    (Status.RESOLVED, "Resolved"),
)

# Audit action codes (as written by the button handlers) -> human-readable verbs
# for the activity log. An unknown code falls back to itself rather than being
# dropped — the log never silently swallows an event.
_ACTION_LABELS: dict[str, str] = {
    "connect": "connected",
    "resolve": "marked resolved",
    "not_relevant": "dismissed",
}

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"

# Shown when a status group or the activity log has nothing yet — an explicit
# empty state, never a silently missing section.
_NO_CASES = "_No cases yet._"
_NO_ACTIVITY = "_No actions recorded yet._"


def _format_ts(ts: datetime) -> str:
    """Render an aware-UTC timestamp for on-screen display (deterministic)."""
    return ts.strftime(_TIMESTAMP_FORMAT)


def _case_row(offer: Offer) -> str:
    """One sourced + timestamped case row for an offer.

    Names the resource and location, the offerer (as a tappable Slack mention),
    and the offer's post time — the same who/what/when sourcing the recall cards
    carry. Rendered as a markdown bullet so the status section reads as a list.
    """
    when = _format_ts(offer.source_ts)
    return f"- *{offer.resource_type}* in {offer.location} — offered by <@{offer.offerer}> · {when}"


def _status_section(status: Status, heading: str, offers: list[Offer]) -> list[str]:
    """The markdown lines for one status group: an h2 heading then its case rows.

    Offers are sorted newest-first by post time so the freshest case is on top.
    An empty group still renders its heading plus an explicit empty-state line —
    a coordinator sees that the group exists and is empty, never a missing
    section.
    """
    group = sorted(
        (o for o in offers if o.status is status),
        key=lambda o: o.source_ts,
        reverse=True,
    )
    lines = [f"## {heading} ({len(group)})"]
    if not group:
        lines.append(_NO_CASES)
        return lines
    lines.extend(_case_row(offer) for offer in group)
    return lines


def _activity_line(event: AuditEvent) -> str:
    """One activity-log line: actor / action / target / when.

    The actor renders as a tappable mention, the action as a human verb, the
    target verbatim (the ``offer:<id>`` / ``offerer:<id>`` string the handler
    recorded), and the time as aware-UTC. Every confirmed action leaves one line.
    """
    verb = _ACTION_LABELS.get(event.action, event.action)
    when = _format_ts(event.ts)
    return f"- <@{event.actor_id}> {verb} `{event.target}` · {when}"


def _activity_section(events: list[AuditEvent]) -> list[str]:
    """The activity-log section: an h2 heading then one line per audit event.

    Events render newest-first (the trail stores insertion order; we reverse for
    display). An empty trail renders the heading plus an explicit empty-state
    line.
    """
    lines = ["## Activity log"]
    if not events:
        lines.append(_NO_ACTIVITY)
        return lines
    lines.extend(_activity_line(event) for event in reversed(events))
    return lines


def compose_board_markdown(offers: list[Offer], events: list[AuditEvent]) -> str:
    """Render the full coordinator board as a Canvas ``markdown`` string.

    Pure ``state -> markdown``: groups ``offers`` by :class:`~entities.Status`
    (open / connected / resolved), then renders the ``events`` as a dated activity
    log. The output is the value for a Canvas ``document_content`` of
    ``{"type": "markdown", "markdown": <this>}``.

    The board always renders every status heading and the activity heading, even
    when empty (explicit empty states), so a coordinator reading it after a restart
    — when the in-memory index is empty but the Canvas still holds the last board —
    sees a coherent, intentionally-empty board rather than a blank document.
    """
    lines: list[str] = [f"# {BOARD_TITLE}", "", VERIFY_NOTE, ""]
    for status, heading in _STATUS_ORDER:
        lines.extend(_status_section(status, heading, offers))
        lines.append("")
    lines.extend(_activity_section(events))
    return "\n".join(lines).rstrip() + "\n"
