"""In-memory matching index for parsed Offers — the fast path before RTS.

A volunteer's offer is parsed into an :class:`~entities.Offer` and added to a
thin, process-local index (:class:`OfferIndex`); a later Need is matched against
that index *first*, then against the Real-Time Search API, and both result sets
are merged into one ranked, sourced reply.

The index is in-memory by design (no persistence, single-process) — see
``docs/adr/0003-in-memory-matching-index.md``. The workspace via RTS remains the
durable store; the index is a latency optimisation, never the system of record.
"""

from matching.blocks import build_offer_ack_blocks
from matching.conversion import INDEX_SOURCE_CHANNEL, match_from_offer
from matching.index import OfferIndex, offer_index

__all__ = [
    "INDEX_SOURCE_CHANNEL",
    "OfferIndex",
    "build_offer_ack_blocks",
    "match_from_offer",
    "offer_index",
]
