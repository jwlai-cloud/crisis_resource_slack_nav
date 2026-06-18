"""A thin, process-local index of parsed Offers — the *plan* step's fast path.

When a volunteer posts an offer it is parsed (``agent.parsing``) into an
:class:`~entities.Offer` and added here, keyed by its deterministic id. A later
Need is matched against this index *before* the Real-Time Search round-trip, so
an offer posted seconds ago surfaces instantly without waiting on RTS indexing.

**Restart semantics (deliberate, documented).** This index is a plain in-process
``dict``; it dies with the process and survives nothing — no file, no database,
no cross-process sharing. That is explicitly fine for the demo (see
``docs/adr/0003-in-memory-matching-index.md``): the workspace itself, queried via
the Real-Time Search API, is the durable store. Every offer indexed here was
*also* posted as a Slack message, so after a restart RTS recall still finds it —
the index is a latency optimisation over the durable workspace, never the system
of record.

Single-process only: the demo runs one socket-mode process, so a module-level
:data:`offer_index` singleton is sufficient. The keyword match reuses
``recall.ranking``'s token logic (imported, never duplicated) so index hits and
RTS hits are scored by exactly the same notion of "overlap".
"""

import logging
import threading
from uuid import UUID

from entities import Need, Offer, Status
from recall.ranking import need_keywords, tokenize

logger = logging.getLogger(__name__)


class OfferIndex:
    """A process-local ``dict`` of :class:`~entities.Offer` rows keyed by id.

    Not durable by design (see the module docstring and ADR-0003). Operations are
    intentionally minimal: add an offer, look one up, transition its status through
    the lifecycle, and find the offers whose text overlaps a Need's keywords.

    **Thread-safe (task 010).** The status transitions are a read-modify-write
    (get -> ``model_copy`` -> set) which is *not* atomic under the GIL, and the
    action-button handlers (Connect / Mark resolved) now mutate the index from
    Bolt's thread pool. A :class:`threading.Lock` guards every access to the
    backing dict so concurrent transitions never lose a write. ADR-0003's
    "threaded dispatch" revisit trigger fired; the lock is the minimal response —
    supersession (an external store) is not needed for a single-process demo.
    """

    def __init__(self) -> None:
        self._offers: dict[UUID, Offer] = {}
        self._lock = threading.Lock()

    def add(self, offer: Offer) -> None:
        """Index ``offer`` under its id.

        Idempotent: re-adding an offer with the same id (e.g. a listener retry on
        the same Slack message — ids are deterministic, see ``entities.models``)
        overwrites the existing row rather than accumulating a duplicate.
        """
        with self._lock:
            self._offers[offer.id] = offer
        logger.info("Indexed offer %s: %s in %s", offer.id, offer.resource_type, offer.location)

    def lookup(self, offer_id: UUID) -> Offer | None:
        """Return the indexed offer for ``offer_id``, or ``None`` if absent."""
        with self._lock:
            return self._offers.get(offer_id)

    def all_offers(self) -> list[Offer]:
        """Return every indexed offer (insertion order)."""
        with self._lock:
            return list(self._offers.values())

    def mark_matched(self, offer_id: UUID) -> Offer | None:
        """Transition an offer to ``MATCHED``; return it, or ``None`` if absent.

        Status is carried on the typed :class:`~entities.Offer`; a transition
        replaces the stored row with a copy bearing the new status (Pydantic
        models are treated as immutable values here).
        """
        return self._set_status(offer_id, Status.MATCHED)

    def mark_resolved(self, offer_id: UUID) -> Offer | None:
        """Transition an offer to ``RESOLVED``; return it, or ``None`` if absent."""
        return self._set_status(offer_id, Status.RESOLVED)

    def _set_status(self, offer_id: UUID, status: Status) -> Offer | None:
        # The whole get -> copy -> set is under the lock: it is a read-modify-write
        # and button handlers run it concurrently on Bolt's thread pool.
        with self._lock:
            offer = self._offers.get(offer_id)
            if offer is None:
                logger.info("Status transition skipped: offer %s not in index", offer_id)
                return None
            updated = offer.model_copy(update={"status": status})
            self._offers[offer_id] = updated
        logger.info("Offer %s -> %s", offer_id, status)
        return updated

    def keyword_lookup(self, need: Need) -> list[Offer]:
        """Return indexed offers whose text overlaps ``need``'s keywords.

        Relevance uses the *same* token logic as RTS ranking
        (``recall.ranking``): a Need's keywords are its ``need_type`` + ``location``
        words (stopwords/1-char tokens dropped), and an offer is a candidate when
        any of those keywords appear in its ``resource_type``, ``location``, or
        ``availability`` text. Resolved offers are excluded — a closed offer is no
        longer a live match. The result is unranked; the caller merges it with RTS
        hits and ranks the combined set so both sources share one ordering.
        """
        keywords = need_keywords(need)
        if not keywords:
            return []
        # Snapshot the rows under the lock, then score outside it: scoring is pure
        # CPU work and must not hold the lock (nor iterate a dict another thread
        # may be mutating, which would raise RuntimeError).
        with self._lock:
            offers = list(self._offers.values())
        candidates: list[Offer] = []
        for offer in offers:
            if offer.status is Status.RESOLVED:
                continue
            offer_tokens = tokenize(f"{offer.resource_type} {offer.location} {offer.availability}")
            if keywords & offer_tokens:
                candidates.append(offer)
        return candidates


# Module-level singleton: the demo runs a single socket-mode process, so one
# shared index per process is the whole design (ADR-0003). Listeners import this
# instance directly rather than constructing their own.
offer_index = OfferIndex()
