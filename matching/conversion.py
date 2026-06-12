"""Adapt an indexed :class:`~entities.Offer` to the recall :class:`RecallMatch`.

The Need flow consults the in-memory index *and* RTS, then merges both into one
ranked list. To keep a single ranking + compose path (``recall.ranking`` /
``recall.blocks``), index hits are converted to the same :class:`RecallMatch`
shape RTS hits use, so the merged list is uniformly typed and every rendered item
carries source + timestamp + the verify note.

An indexed offer has no Slack permalink or channel (it came off a parsed message,
not an RTS hit), so those map to empty / a synthetic source label rather than
being fabricated — sourcing stays honest: the offerer and the post time are real,
the "where" is named as the index rather than dressed up as a channel link.
"""

from entities import Offer
from recall.models import RecallMatch

# Shown as the "channel" on an index hit's source line. It tells the reader the
# match came from the live in-memory index (an offer posted this session), not
# from a workspace search — distinct provenance, surfaced not hidden.
INDEX_SOURCE_CHANNEL = "indexed offers"


def match_from_offer(offer: Offer) -> RecallMatch:
    """Convert an indexed :class:`~entities.Offer` into a :class:`RecallMatch`.

    The match text recomposes the offer's structured fields into the one-line
    snippet the compose step renders; ``author`` is the offerer and ``ts`` is the
    offer's ``source_ts`` (both real, trust-critical source fields). ``author_id``
    carries the offerer handle too (the parsed offerer *is* the Slack user id),
    ``channel`` is a synthetic provenance label, and ``permalink`` is empty — an
    index hit links to no single workspace message. ``offer_id`` carries the
    index id (as a string) so the action-button handlers can ``mark_resolved`` the
    exact offer when the human confirms a match.
    """
    text = f"{offer.resource_type} — {offer.availability} ({offer.location})"
    return RecallMatch(
        text=text,
        author=offer.offerer,
        author_id=offer.offerer,
        channel=INDEX_SOURCE_CHANNEL,
        channel_id="",
        ts=offer.source_ts,
        permalink="",
        offer_id=str(offer.id),
    )
