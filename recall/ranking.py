"""Rank recall matches against a Need — the *rank* step of the agent loop.

CPU-bound and pure: no I/O, no clock side effects (the "now" used for recency is
passed in, so the function is deterministic and table-testable). The score is a
simple, explainable blend of two signals the design doc calls out (§"ranked by
relevance, proximity, recency"):

* **Keyword overlap** — how many of the Need's keywords (its ``need_type`` and
  ``location`` words) appear in the match text. This is the relevance/proximity
  signal: a match mentioning the same resource *and* the same place scores above
  one mentioning only the resource.
* **Recency** — newer posts rank higher, decaying smoothly over a window. During
  a fast-moving disaster a generator offered an hour ago beats one from last week.

Scores are in ``[0, 1]``; overlap is weighted above recency because a recent but
irrelevant message helps no one. Ties break on recency (newer first) then text so
the order is stable for snapshot tests.
"""

import re
from datetime import datetime, timedelta

from entities import Need
from recall.models import RecallMatch

# Weights: relevance dominates, recency is the tie-shaper. They sum to 1 so the
# combined score stays in [0, 1].
_OVERLAP_WEIGHT = 0.7
_RECENCY_WEIGHT = 0.3

# Recency decays linearly to zero across this window. A week matches the demo's
# "crisis runs for days" horizon without making month-old posts score as recent.
_RECENCY_WINDOW = timedelta(days=7)

# Words too short or too common to carry signal — dropped from the keyword set so
# "a", "of", "the" don't manufacture overlap.
_STOPWORDS = frozenset(
    {"a", "an", "and", "or", "the", "of", "for", "to", "in", "on", "at", "is", "are", "need"}
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens with stopwords and 1-char tokens removed."""
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS}


def need_keywords(need: Need) -> set[str]:
    """The keyword set a recall match is scored against: need_type + location."""
    return _tokens(f"{need.need_type} {need.location}")


def keyword_overlap(need: Need, match: RecallMatch) -> float:
    """Fraction of the Need's keywords present in the match text, in ``[0, 1]``."""
    keywords = need_keywords(need)
    if not keywords:
        return 0.0
    hits = keywords & _tokens(match.text)
    return len(hits) / len(keywords)


def recency_score(match: RecallMatch, now: datetime) -> float:
    """Linear recency in ``[0, 1]``: 1.0 at ``now``, 0.0 at/older than the window.

    ``now`` is passed in (not read from the clock) so ranking stays pure and
    deterministic for tests. A match newer than ``now`` (clock skew) clamps to 1.0.
    """
    age = now - match.ts
    if age <= timedelta(0):
        return 1.0
    if age >= _RECENCY_WINDOW:
        return 0.0
    return 1.0 - (age / _RECENCY_WINDOW)


def score_match(need: Need, match: RecallMatch, now: datetime) -> float:
    """Combined relevance+recency score in ``[0, 1]`` for one match."""
    return _OVERLAP_WEIGHT * keyword_overlap(need, match) + _RECENCY_WEIGHT * recency_score(
        match, now
    )


def rank_matches(need: Need, matches: list[RecallMatch], now: datetime) -> list[RecallMatch]:
    """Return ``matches`` ordered best-fit first for ``need``.

    Sort key: combined score desc, then recency desc, then text — so equal-scoring
    matches order deterministically and snapshot tests stay stable.
    """
    return sorted(
        matches,
        key=lambda m: (-score_match(need, m, now), -m.ts.timestamp(), m.text),
    )
