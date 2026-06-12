"""Unit tests for matching.index — the process-local offer index.

Covers add/lookup, idempotent re-add, the lifecycle status transitions
(mark_matched / mark_resolved, including the absent-id no-op), and keyword lookup
against a Need (overlap, the resolved-offer exclusion, and the empty-keyword
guard). Builders come in via ``make_offer`` / ``make_need`` and a fresh ``index``
fixture from conftest.
"""

from collections.abc import Callable
from uuid import uuid4

from entities import Need, Offer, Status
from matching.index import OfferIndex, offer_index


def test_add_then_lookup_returns_offer(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
) -> None:
    """An added offer is retrievable by its id."""
    offer = make_offer()

    index.add(offer)

    assert index.lookup(offer.id) == offer


def test_lookup_missing_returns_none(index: OfferIndex) -> None:
    """Looking up an unknown id returns None, not a KeyError."""
    assert index.lookup(uuid4()) is None


def test_add_is_idempotent_on_same_id(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
) -> None:
    """Re-adding an offer with the same id overwrites, never duplicates."""
    first = make_offer(resource_type="generator")
    # Same offerer + source_ts -> same deterministic id (a listener retry).
    second = make_offer(resource_type="2kW generator")
    assert first.id == second.id

    index.add(first)
    index.add(second)

    assert len(index.all_offers()) == 1
    assert index.lookup(first.id).resource_type == "2kW generator"


def test_mark_matched_transitions_status(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
) -> None:
    """mark_matched moves an open offer to MATCHED and returns the updated row."""
    offer = make_offer()
    index.add(offer)

    updated = index.mark_matched(offer.id)

    assert updated is not None
    assert updated.status is Status.MATCHED
    assert index.lookup(offer.id).status is Status.MATCHED


def test_mark_resolved_transitions_status(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
) -> None:
    """mark_resolved moves an offer to RESOLVED and returns the updated row."""
    offer = make_offer()
    index.add(offer)

    updated = index.mark_resolved(offer.id)

    assert updated is not None
    assert updated.status is Status.RESOLVED
    assert index.lookup(offer.id).status is Status.RESOLVED


def test_mark_matched_missing_id_is_noop(index: OfferIndex) -> None:
    """A status transition on an unknown id returns None and adds nothing."""
    result = index.mark_matched(uuid4())

    assert result is None
    assert index.all_offers() == []


def test_keyword_lookup_returns_overlapping_offer(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """An offer whose text overlaps the need's keywords is a candidate."""
    offer = make_offer(resource_type="generator", location="Exmouth")
    index.add(offer)
    need = make_need(need_type="generator", location="Exmouth")

    assert index.keyword_lookup(need) == [offer]


def test_keyword_lookup_excludes_non_overlapping_offer(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """An offer with no keyword overlap is not a candidate."""
    index.add(make_offer(resource_type="bottled water", location="Learmonth"))
    need = make_need(need_type="generator", location="Exmouth")

    assert index.keyword_lookup(need) == []


def test_keyword_lookup_matches_on_availability_text(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """Keyword overlap considers availability text, not just type/location."""
    offer = make_offer(
        resource_type="spare equipment",
        location="town",
        availability="includes a generator, collect in Exmouth",
    )
    index.add(offer)
    need = make_need(need_type="generator", location="Exmouth")

    assert index.keyword_lookup(need) == [offer]


def test_keyword_lookup_excludes_resolved_offers(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """A resolved offer is no longer a live match and is excluded."""
    offer = make_offer(resource_type="generator", location="Exmouth")
    index.add(offer)
    index.mark_resolved(offer.id)
    need = make_need(need_type="generator", location="Exmouth")

    assert index.keyword_lookup(need) == []


def test_keyword_lookup_includes_matched_offers(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """A matched-but-not-resolved offer is still surfaced (still a live option)."""
    offer = make_offer(resource_type="generator", location="Exmouth")
    index.add(offer)
    index.mark_matched(offer.id)
    need = make_need(need_type="generator", location="Exmouth")

    candidates = index.keyword_lookup(need)
    assert [c.id for c in candidates] == [offer.id]
    assert candidates[0].status is Status.MATCHED


def test_keyword_lookup_empty_keywords_returns_empty(
    index: OfferIndex,
    make_offer: Callable[..., Offer],
    make_need: Callable[..., Need],
) -> None:
    """A need whose keywords are all stopwords yields no candidates (no false hits)."""
    index.add(make_offer(resource_type="generator", location="Exmouth"))
    # "a" + "the" -> both stopwords/short -> empty keyword set.
    need = make_need(need_type="a", location="the")

    assert index.keyword_lookup(need) == []


def test_module_singleton_is_an_offer_index() -> None:
    """The shared singleton listeners import is a real OfferIndex instance."""
    assert isinstance(offer_index, OfferIndex)
