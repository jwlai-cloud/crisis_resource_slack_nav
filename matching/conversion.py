"""Adapt an indexed :class:`~entities.Offer` to the recall :class:`RecallMatch`.

The Need flow consults the in-memory index *and* RTS, then merges both into one
ranked list. To keep a single ranking + compose path (``recall.ranking`` /
``recall.blocks``), index hits are converted to the same :class:`RecallMatch`
shape RTS hits use, so the merged list is uniformly typed and every rendered item
carries source + timestamp + the verify note.

An indexed offer has no Slack permalink or channel (it came off a parsed message,
not an RTS hit), so those map to empty / a provenance label rather than being
fabricated — sourcing stays honest: the offerer and the post time are real, the
"where" is named as the index's live memory rather than dressed up as a channel
link or, worse, a channel that does not exist.
"""

from entities import Offer
from recall.models import RecallMatch

# Shown as the "channel" on an index hit's source line. It names the match's
# provenance — the live in-memory recall (an offer posted this session), not a
# workspace search — without dressing it up as a real Slack channel. Live 016: the
# old "indexed offers" label rendered as "in #indexed offers", a channel that does
# not exist; "workspace memory" reads as memory, not a fabricated channel link.
INDEX_SOURCE_CHANNEL = "workspace memory"


def match_from_offer(offer: Offer) -> RecallMatch:
    """Convert an indexed :class:`~entities.Offer` into a :class:`RecallMatch`.

    The match text recomposes the offer's structured fields into the one-line
    snippet the compose step renders; ``ts`` is the offer's ``source_ts`` (a real,
    trust-critical source field). The parsed offerer *is* the Slack user id, so it
    rides on ``author_id`` (which drives the card's tappable ``Contact: <@id>``
    mention and the action-button payload) and ``author`` is the same id rendered
    as a Slack mention — so the "Posted by" line shows ``<@id>`` like an RTS card
    instead of leaking a raw user id (live 016). ``channel`` is the provenance
    label and ``permalink`` is empty — an index hit links to no single workspace
    message; when a near-duplicate RTS twin exists the merge step adopts that
    twin's channel/permalink for display. ``offer_id`` carries the index id (as a
    string) so the action-button handlers can ``mark_resolved`` the exact offer
    when the human confirms a match.
    """
    text = f"{offer.resource_type} — {offer.availability} ({offer.location})"
    return RecallMatch(
        text=text,
        author=f"<@{offer.offerer}>",
        author_id=offer.offerer,
        channel=INDEX_SOURCE_CHANNEL,
        channel_id="",
        ts=offer.source_ts,
        permalink="",
        offer_id=str(offer.id),
    )
