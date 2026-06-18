"""Per-user dismissal memory for recall matches (task 015).

When a human clicks "Not relevant" on a match card, that is a deliberate signal:
*this requester does not want this match surfaced again*. Without a memory of it,
a fresh need re-queries RTS and resurfaces the very match they just dismissed with
new buttons (live finding 2026-06-12). This module is that memory.

**What it remembers.** A set of ``(user_id, match identity)`` pairs. The identity
is the most stable handle the match offers, in priority order:

1. ``offer_id`` — the in-memory index id, when the match came from the index.
2. ``permalink`` — the workspace message URL, for an RTS-only hit.
3. a normalised-text hash — the last resort when neither id nor permalink exists,
   so a textually identical match is still recognised as the same one.

**Per-user, by design.** The store is keyed on the dismissing user, so user A's
dismissal never hides a match from user B. Dismissal is a personal "not for me"
signal, not a workspace-wide takedown.

**Restart semantics (deliberate, documented).** This is a plain in-process set; it
dies with the process and persists nothing — the *same* posture as the matching
index (``docs/adr/0003-in-memory-matching-index.md``) and the audit trail. The
W4 persistence decision covers all three together. A :class:`threading.Lock`
guards mutation because the action-button handlers run on Bolt's thread pool.
"""

import hashlib
import logging
import threading

from recall.models import RecallMatch

logger = logging.getLogger(__name__)


def match_identity(*, offer_id: str = "", permalink: str = "", text: str = "") -> str:
    """The stable identity of a match, from its most reliable available handle.

    Priority: ``offer_id`` (index id) -> ``permalink`` (workspace URL) -> a hash of
    the normalised text. Whitespace is collapsed and lowercased before hashing so a
    re-posted, cosmetically-different copy of the same message hashes the same. The
    returned string is prefixed (``offer:`` / ``link:`` / ``text:``) so two
    different handles can never collide on the same value.
    """
    if offer_id:
        return f"offer:{offer_id}"
    if permalink:
        return f"link:{permalink}"
    # Truncate the RAW text to the button payload's snippet cap (280) before
    # normalising, so the write side (which hashes the truncated snippet) and the
    # read side (which hashes the full match text) agree for long messages.
    normalised = " ".join(text[:280].split()).lower()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return f"text:{digest}"


def identity_of(match: RecallMatch) -> str:
    """The dismissal identity for a :class:`RecallMatch` (offer id / permalink / text)."""
    return match_identity(offer_id=match.offer_id, permalink=match.permalink, text=match.text)


class DismissalStore:
    """A process-local set of ``(user_id, match identity)`` dismissals.

    Not durable by design (see the module docstring): it mirrors the matching
    index and audit trail. Thread-safe — a lock guards every access because the
    Bolt action handlers record dismissals from the thread pool while the recall
    path reads them.
    """

    def __init__(self) -> None:
        self._dismissed: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def dismiss(self, user_id: str, identity: str) -> None:
        """Record that ``user_id`` dismissed the match with ``identity``.

        Idempotent: dismissing the same match twice is a no-op (it is a set).
        """
        with self._lock:
            self._dismissed.add((user_id, identity))
            count = len(self._dismissed)
        logger.info("Dismissal recorded for %s on %s (%d total)", user_id, identity, count)

    def is_dismissed(self, user_id: str, identity: str) -> bool:
        """Whether ``user_id`` previously dismissed the match with ``identity``."""
        with self._lock:
            return (user_id, identity) in self._dismissed

    def filter_dismissed(self, user_id: str, matches: list[RecallMatch]) -> list[RecallMatch]:
        """Drop matches ``user_id`` has dismissed; keep order and every other match.

        Per-user: only the dismissing user's own dismissals are consulted, so this
        never hides a match from a different requester. With no ``user_id`` (an
        anonymous turn) nothing is filtered — we never guess whose dismissal applies.
        """
        if not user_id:
            return matches
        with self._lock:
            dismissed = {identity for (uid, identity) in self._dismissed if uid == user_id}
        if not dismissed:
            return matches
        return [m for m in matches if identity_of(m) not in dismissed]


# Module-level singleton: one store per socket-mode process, mirroring the
# matching-index and audit-trail singletons. Handlers and the recall path import
# this instance directly rather than constructing their own.
dismissal_store = DismissalStore()
