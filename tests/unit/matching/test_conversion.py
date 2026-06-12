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
    """Offerer and source_ts (trust-critical) survive the conversion intact.

    ``author_id`` carries the raw offerer id (it drives the contact mention and
    the button payload); ``author`` carries the same id rendered as a Slack
    mention so the "Posted by" line shows ``<@id>`` rather than a leaked raw id.
    """
    offer = make_offer(offerer="U_JORDAN")

    match = match_from_offer(offer)

    assert isinstance(match, RecallMatch)
    assert match.author == "<@U_JORDAN>"  # mention-rendered, not a leaked raw id
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


def test_index_source_channel_is_workspace_memory_not_a_fake_channel() -> None:
    """The provenance label reads as memory, never a fabricated ``#indexed offers``.

    Live 016: the index card leaked ``in #indexed offers`` — a channel that does
    not exist. The label must name the live in-memory recall honestly without
    dressing it up as a real Slack channel.
    """
    assert INDEX_SOURCE_CHANNEL == "workspace memory"
    assert "indexed offers" not in INDEX_SOURCE_CHANNEL


def test_match_from_offer_author_id_drives_a_real_mention(
    make_offer: Callable[..., Offer],
) -> None:
    """``author_id`` carries the offerer's Slack id so the card renders a ``<@id>``.

    The block compose step renders ``Contact: <@author_id>`` from ``author_id``,
    so an index card must carry it the same way an RTS card does — otherwise the
    index card cannot render a tappable mention (live 016: it leaked a raw id in
    the source line instead).
    """
    offer = make_offer(offerer="U0BA67L9HRS")

    match = match_from_offer(offer)

    assert match.author_id == "U0BA67L9HRS"  # drives <@U0BA67L9HRS> in the card


def test_match_from_offer_carries_offer_id(
    make_offer: Callable[..., Offer],
) -> None:
    """The index offer id rides through as a string so handlers can resolve it."""
    offer = make_offer()

    match = match_from_offer(offer)

    assert match.offer_id == str(offer.id)
