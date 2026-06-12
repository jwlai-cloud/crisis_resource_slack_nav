"""Compose the offer-acknowledgement reply as Block Kit — informational only.

When a volunteer posts an offer the agent confirms it was logged and indexed. The
acknowledgement is deliberately *informational*: it carries the offer's source
(who offered, when) so the same sourcing guardrail that governs recall replies
holds here too, but it has **no action buttons** — acknowledging an offer is not
an actionable match, and the bounded-autonomy confirmation step (Connect / Mark
resolved, W3) belongs to the Need→Offer match flow, not to logging an offer.

Pure and deterministic (UTC timestamp formatting), so the block structure is
unit-asserted without a live Slack call.
"""

from datetime import datetime

from slack_sdk.models.blocks import (
    Block,
    ContextBlock,
    MarkdownTextObject,
    SectionBlock,
)

from entities import Offer
from recall.blocks import WORKSPACE_BAR_EMOJI

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"

# The ack opens with the same colored-square rank-label cue as the recall cards
# (task 008 visual parity), mirroring the mock's offer card: green = workspace.
# An indexed offer is "workspace memory" — searchable, but not yet a match.
INDEXED_RANK_LABEL = f"{WORKSPACE_BAR_EMOJI} *INDEXED* · WORKSPACE MEMORY"

_CONFIRMATION = (
    ":white_check_mark: Logged your offer — I'll surface it when someone nearby "
    "needs it. Nothing happens automatically; a person always confirms a match."
)


def _format_ts(ts: datetime) -> str:
    """Render an aware-UTC timestamp for on-screen display (deterministic)."""
    return ts.strftime(_TIMESTAMP_FORMAT)


def _source_line(offer: Offer) -> str:
    """The sourcing context line for an offer: who / what / where / when.

    The offerer renders as a real Slack mention when it looks like a user id;
    an unknown location is omitted rather than shown as "in unknown" — the
    no-placeholder rule applies to our own blocks too.
    """
    if offer.offerer and offer.offerer.startswith(("U", "W")) and offer.offerer.isalnum():
        offerer = f"<@{offer.offerer}>"
    else:
        offerer = f"*{offer.offerer or 'Unknown offerer'}*"
    location = (offer.location or "").strip()
    where = f" in {location}" if location and location.lower() != "unknown" else ""
    return (
        f"Offer from {offerer}: {offer.resource_type}{where} "
        f"· {offer.availability} · logged {_format_ts(offer.source_ts)}"
    )


def build_offer_ack_blocks(offer: Offer) -> list[Block]:
    """Compose the informational acknowledgement for a freshly indexed offer.

    Three blocks: the workspace rank-label cue (matching the recall cards / mock),
    a confirmation section (no actions), and a sourcing context line carrying the
    offerer and the timestamp — the offer is sourced and timestamped on screen,
    never silently swallowed.
    """
    return [
        ContextBlock(elements=[MarkdownTextObject(text=INDEXED_RANK_LABEL)]),
        SectionBlock(text=MarkdownTextObject(text=_CONFIRMATION)),
        ContextBlock(elements=[MarkdownTextObject(text=_source_line(offer))]),
    ]
