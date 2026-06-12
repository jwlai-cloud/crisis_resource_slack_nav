"""Unit tests for recall.ranking — pure keyword-overlap + recency scoring.

Table-driven: each row pins one input shape (overlap level, age) to an expected
score band or ordering, so the scoring blend stays explainable and regressions
surface as a row flip. Builders come in via the ``make_need`` / ``make_match``
fixtures and ``now`` (the fixed reference instant) from conftest.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from entities import Need
from recall.models import RecallMatch
from recall.ranking import (
    keyword_overlap,
    need_keywords,
    rank_matches,
    recency_score,
    score_match,
)


def test_need_keywords_drops_stopwords_and_short_tokens(
    make_need: Callable[..., Need],
) -> None:
    """Keyword set is need_type + location, minus stopwords and 1-char tokens."""
    need = make_need(need_type="a generator", location="North Exmouth")

    keywords = need_keywords(need)

    assert keywords == {"generator", "north", "exmouth"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spare generator available in Exmouth", 1.0),  # both keywords hit
        ("spare generator available in town", 0.5),  # need_type only
        ("water and food in Exmouth", 0.5),  # location only
        ("we have water and food", 0.0),  # no overlap
    ],
)
def test_keyword_overlap_fraction(
    text: str,
    expected: float,
    make_need: Callable[..., Need],
    make_match: Callable[..., RecallMatch],
) -> None:
    """Overlap is the fraction of the need's keywords present in the match text."""
    need = make_need(need_type="generator", location="Exmouth")
    match = make_match(text=text)

    assert keyword_overlap(need, match) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), 1.0),  # posted exactly now
        (timedelta(days=7), 0.0),  # at the window edge
        (timedelta(days=14), 0.0),  # older than the window clamps to 0
        (timedelta(days=-1), 1.0),  # future (clock skew) clamps to 1
        (timedelta(days=3, hours=12), 0.5),  # half the 7-day window
    ],
)
def test_recency_score_decays_linearly(
    age: timedelta,
    expected: float,
    make_match: Callable[..., RecallMatch],
    now: datetime,
) -> None:
    """Recency is 1.0 at now, decaying linearly to 0.0 across a 7-day window."""
    match = make_match(ts=now - age)

    assert recency_score(match, now) == pytest.approx(expected)


def test_score_blends_overlap_above_recency(
    make_need: Callable[..., Need],
    make_match: Callable[..., RecallMatch],
    now: datetime,
) -> None:
    """A perfectly relevant old match beats a recent irrelevant one."""
    need = make_need(need_type="generator", location="Exmouth")
    relevant_old = make_match(text="generator in Exmouth", ts=now - timedelta(days=6))
    irrelevant_new = make_match(text="free coffee in the kitchen", ts=now)

    assert score_match(need, relevant_old, now) > score_match(need, irrelevant_new, now)


def test_rank_orders_best_fit_first(
    need: Need,
    make_match: Callable[..., RecallMatch],
    now: datetime,
) -> None:
    """rank_matches puts the strongest (relevant + recent) match first."""
    strong = make_match(text="spare generator in Exmouth", ts=now - timedelta(hours=1))
    weak_relevant = make_match(text="generator somewhere", ts=now - timedelta(days=6))
    irrelevant = make_match(text="anyone got spare batteries?", ts=now)

    ranked = rank_matches(need, [irrelevant, weak_relevant, strong], now)

    assert ranked[0] is strong
    assert ranked[-1] is irrelevant


def test_rank_is_stable_for_equal_scores(
    make_need: Callable[..., Need],
    make_match: Callable[..., RecallMatch],
    now: datetime,
) -> None:
    """Equal-scoring matches order deterministically (recency desc, then text)."""
    need = make_need(need_type="water", location="Exmouth")
    # Neither mentions the keywords -> equal overlap (0); same ts -> equal recency.
    a = make_match(text="aaa unrelated", ts=now)
    b = make_match(text="bbb unrelated", ts=now)

    ranked = rank_matches(need, [b, a], now)

    assert [m.text for m in ranked] == ["aaa unrelated", "bbb unrelated"]
