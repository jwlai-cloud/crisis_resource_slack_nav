"""Unit tests for matching.conversion — Offer -> RecallMatch adaptation.

An index hit must convert into the same RecallMatch shape RTS hits use so the
merged list ranks and renders uniformly, with the offer's real source (offerer +
timestamp) preserved and no permalink fabricated.
"""

from collections.abc import Callable

from entities import Offer
from matching.conversion import INDEX_SOURCE_CHANNEL, match_from_offer
from recall.models import RecallMatch


def test_match_from_offer_preserves_source_fields(
    make_offer: Callable[..., Offer],
) -> None:
    """Offerer and source_ts (trust-critical) survive the conversion intact."""
    offer = make_offer(offerer="U_JORDAN")

    match = match_from_offer(offer)

    assert isinstance(match, RecallMatch)
    assert match.author == "U_JORDAN"
    assert match.author_id == "U_JORDAN"
    assert match.ts == offer.source_ts


def test_match_from_offer_recomposes_text(
    make_offer: Callable[..., Offer],
) -> None:
    """The match snippet recomposes the offer's structured fields."""
    offer = make_offer(
        resource_type="2kW generator",
        location="Exmouth",
        availability="collect any time today",
    )

    match = match_from_offer(offer)

    assert "2kW generator" in match.text
    assert "Exmouth" in match.text
    assert "collect any time today" in match.text


def test_match_from_offer_uses_synthetic_provenance_and_no_permalink(
    make_offer: Callable[..., Offer],
) -> None:
    """An index hit names its provenance and fabricates no workspace permalink."""
    match = match_from_offer(make_offer())

    assert match.channel == INDEX_SOURCE_CHANNEL
    assert match.permalink == ""


def test_match_from_offer_carries_offer_id(
    make_offer: Callable[..., Offer],
) -> None:
    """The index offer id rides through as a string so handlers can resolve it."""
    offer = make_offer()

    match = match_from_offer(offer)

    assert match.offer_id == str(offer.id)
