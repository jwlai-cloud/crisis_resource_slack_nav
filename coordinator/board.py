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


# Prefixes the button handlers write on an audit target (see
# ``crisis_buttons._offer_target``): an offer by its id, or an offerer by user id.
_OFFER_TARGET_PREFIX = "offer:"
_OFFERER_TARGET_PREFIX = "offerer:"


def _person(user_id: str, names: dict[str, str]) -> str:
    """Render a user id as a display name when known, else the bare id.

    The canvas does NOT resolve ``<@id>`` mention syntax (task 019), so we
    substitute the resolved display name. With no name for the id we fall back to
    the bare id — never a crash, never an empty string.
    """
    return names.get(user_id, user_id)


def _case_row(offer: Offer, names: dict[str, str]) -> str:
    """One sourced + timestamped case row for an offer.

    Names the resource and location, the offerer (by resolved display name, or
    the bare id when unresolved), and the offer's post time — the same
    who/what/when sourcing the recall cards carry. Rendered as a markdown bullet
    so the status section reads as a list.
    """
    when = _format_ts(offer.source_ts)
    offerer = _person(offer.offerer, names)
    return f"- *{offer.resource_type}* in {offer.location} — offered by {offerer} · {when}"


def _status_section(
    status: Status, heading: str, offers: list[Offer], names: dict[str, str]
) -> list[str]:
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
    lines.extend(_case_row(offer, names) for offer in group)
    return lines


def _humanize_target(target: str, offers: list[Offer], names: dict[str, str]) -> str:
    """Render an audit target as something a coordinator can read.

    The handlers record a target verbatim as ``offer:<uuid>`` or
    ``offerer:<id>``. Neither reads well on screen, so:

    * ``offer:<uuid>`` resolves against ``offers`` to "the <resource_type> offer"
      (e.g. "the camp beds offer"); if the offer is not in the list we fall back
      to the bare target string so the line is never dropped or blanked.
    * ``offerer:<id>`` resolves the id to a display name via ``names`` (bare id
      when unresolved).
    * Anything else renders verbatim — the log never silently swallows a target.
    """
    if target.startswith(_OFFER_TARGET_PREFIX):
        offer_id = target[len(_OFFER_TARGET_PREFIX) :]
        for offer in offers:
            if str(offer.id) == offer_id:
                return f"the {offer.resource_type} offer"
        return target
    if target.startswith(_OFFERER_TARGET_PREFIX):
        user_id = target[len(_OFFERER_TARGET_PREFIX) :]
        return _person(user_id, names)
    return target


def _activity_line(event: AuditEvent, offers: list[Offer], names: dict[str, str]) -> str:
    """One activity-log line: actor / action / target / when.

    The actor renders by resolved display name (bare id when unresolved), the
    action as a human verb, and the target humanized — an ``offer:<uuid>`` shows
    the resource ("the camp beds offer"), an ``offerer:<id>`` shows the offerer's
    name — with the time as aware-UTC. Every confirmed action leaves one line.
    """
    verb = _ACTION_LABELS.get(event.action, event.action)
    when = _format_ts(event.ts)
    actor = _person(event.actor_id, names)
    target = _humanize_target(event.target, offers, names)
    return f"- {actor} {verb} {target} · {when}"


def _activity_section(
    events: list[AuditEvent], offers: list[Offer], names: dict[str, str]
) -> list[str]:
    """The activity-log section: an h2 heading then one line per audit event.

    Events render newest-first (the trail stores insertion order; we reverse for
    display). An empty trail renders the heading plus an explicit empty-state
    line. Each line is humanized against ``offers`` (to name the targeted
    resource) and ``names`` (to name the people).
    """
    lines = ["## Activity log"]
    if not events:
        lines.append(_NO_ACTIVITY)
        return lines
    lines.extend(_activity_line(event, offers, names) for event in reversed(events))
    return lines


def compose_board_markdown(
    offers: list[Offer],
    events: list[AuditEvent],
    names: dict[str, str] | None = None,
) -> str:
    """Render the full coordinator board as a Canvas ``markdown`` string.

    Pure ``state -> markdown``: groups ``offers`` by :class:`~entities.Status`
    (open / connected / resolved), then renders the ``events`` as a dated activity
    log. The output is the value for a Canvas ``document_content`` of
    ``{"type": "markdown", "markdown": <this>}``.

    ``names`` maps user id -> display name (resolved by the publisher's impure
    boundary, :func:`coordinator.names.resolve_display_names`, and passed in so
    this stays pure). A canvas renders ``<@id>`` mention syntax literally rather
    than as a name, so case rows and activity lines substitute the resolved name;
    any id missing from ``names`` falls back to the bare id (never a crash). With
    ``names`` omitted (``None``) every person renders as the bare id.

    The board always renders every status heading and the activity heading, even
    when empty (explicit empty states), so a coordinator reading it after a restart
    — when the in-memory index is empty but the Canvas still holds the last board —
    sees a coherent, intentionally-empty board rather than a blank document.
    """
    names = names or {}
    lines: list[str] = [f"# {BOARD_TITLE}", "", VERIFY_NOTE, ""]
    for status, heading in _STATUS_ORDER:
        lines.extend(_status_section(status, heading, offers, names))
        lines.append("")
    lines.extend(_activity_section(events, offers, names))
    return "\n".join(lines).rstrip() + "\n"
