"""Unit tests for the need-echo filter (task 014).

Live finding (2026-06-12): a requester's own earlier need message surfaced as
MATCH 1 — a near-perfect keyword match, but it is a *need*, not an offer. The
filter drops RTS matches whose token set is a near-duplicate (Jaccard >= 0.85) of
the current request text. It is a pure function over ``tokenize()`` sets — no LLM,
no network.

Honest scope (pinned by the "near-miss kept" test): this kills *echoes* of the
current request, not arbitrary foreign needs.
"""

from datetime import UTC, datetime

from recall.client import _drop_need_echoes
from recall.models import RecallMatch

NOW = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)


def _m(text: str) -> RecallMatch:
    return RecallMatch(
        text=text,
        author="user",
        author_id="U1",
        channel="general",
        channel_id="C1",
        ts=NOW,
        permalink="https://x/p1",
    )


def test_exact_echo_of_request_is_dropped() -> None:
    """A match identical to the current request is an echo and is dropped."""
    request = "Family of 4 need water and a generator"
    matches = [_m("Family of 4 need water and a generator")]

    assert _drop_need_echoes(matches, request) == []


def test_near_duplicate_above_threshold_is_dropped() -> None:
    """A match sharing >= 85% of its token set with the request is dropped."""
    request = "family of four needs water and a generator in exmouth town"
    # Same content tokens, only stopword-level cosmetic differences -> Jaccard ~1.0.
    matches = [_m("family of four needs water and the generator in exmouth town")]

    assert _drop_need_echoes(matches, request) == []


def test_near_miss_below_threshold_is_kept() -> None:
    """A genuine offer that merely shares the resource words is kept (honest scope)."""
    request = "family of four needs water and a generator in exmouth town urgently"
    offer = _m("I have a spare generator to lend, collect from north exmouth")

    out = _drop_need_echoes([offer], request)

    assert out == [offer]


def test_empty_request_text_keeps_everything() -> None:
    """With no request tokens to compare against, nothing is treated as an echo."""
    offer = _m("Offering: bottled water")

    assert _drop_need_echoes([offer], "") == [offer]


def test_only_the_echo_is_dropped_others_survive() -> None:
    """The echo is removed; unrelated and partially-overlapping offers stay."""
    request = "need a generator and water in exmouth"
    echo = _m("need a generator and water in exmouth")
    offer = _m("I can lend a generator this afternoon")

    out = _drop_need_echoes([echo, offer], request)

    assert out == [offer]


def test_threshold_boundary_at_0_85_drops() -> None:
    """A token set at exactly the 0.85 Jaccard boundary counts as an echo (>=)."""
    # Request tokens: {one, two, three, four, five, six} (6 tokens).
    request = "one two three four five six"
    # Match shares 6 of 7 union tokens with the request -> 6/7 ≈ 0.857 >= 0.85.
    matches = [_m("one two three four five six seven")]

    assert _drop_need_echoes(matches, request) == []


def test_just_below_boundary_is_kept() -> None:
    """A token set just under the 0.85 boundary is not an echo and is kept."""
    # Request: 4 tokens; match shares 4 of 6 union -> 4/6 ≈ 0.667 < 0.85.
    request = "alpha bravo charlie delta"
    match = _m("alpha bravo charlie delta echo foxtrot")

    assert _drop_need_echoes([match], request) == [match]
