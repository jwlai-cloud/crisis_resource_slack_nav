"""Unit tests for recall.dismissals — per-user dismissal memory (task 015).

Pure, in-process: no Slack, no network. We pin the identity scheme (offer id ->
permalink -> text hash), the round-trip (dismiss then read it back), the per-user
isolation guarantee (user A's dismissal never hides a match from user B), and the
filter contract used by the recall path.
"""

from datetime import UTC, datetime

from recall.dismissals import (
    DismissalStore,
    identity_of,
    match_identity,
)
from recall.models import RecallMatch

NOW = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)


def _match(
    *,
    text: str = "spare generator in Exmouth",
    permalink: str = "https://x/p1",
    offer_id: str = "",
) -> RecallMatch:
    return RecallMatch(
        text=text,
        author="Jordan",
        author_id="U_OFFERER",
        channel="offers",
        channel_id="C1",
        ts=NOW,
        permalink=permalink,
        offer_id=offer_id,
    )


# ----- identity scheme -----


def test_identity_prefers_offer_id() -> None:
    """An index-backed match identifies by its offer id above all else."""
    identity = match_identity(offer_id="abc", permalink="https://x/p1", text="anything")

    assert identity == "offer:abc"


def test_identity_falls_back_to_permalink() -> None:
    """With no offer id, the permalink is the identity."""
    identity = match_identity(permalink="https://x/p1", text="anything")

    assert identity == "link:https://x/p1"


def test_identity_falls_back_to_text_hash() -> None:
    """With neither id nor permalink, a stable hash of the normalised text is used."""
    identity = match_identity(text="Offering: water")

    assert identity.startswith("text:")
    assert len(identity) > len("text:")  # an actual digest, not an empty hash


def test_text_identity_is_whitespace_and_case_insensitive() -> None:
    """Cosmetically-different copies of the same text hash to the same identity."""
    a = match_identity(text="Offering:  WATER  now")
    b = match_identity(text="offering: water now")

    assert a == b


def test_different_handles_never_collide() -> None:
    """offer-id, permalink, and text identities live in separate prefixed namespaces."""
    by_offer = match_identity(offer_id="https://x/p1")
    by_link = match_identity(permalink="https://x/p1")

    assert by_offer != by_link


def test_identity_of_match_uses_offer_id_when_present() -> None:
    """identity_of reads offer_id off a RecallMatch first."""
    match = _match(offer_id="uuid-123", permalink="https://x/p1")

    assert identity_of(match) == "offer:uuid-123"


# ----- round-trip -----


def test_dismiss_then_is_dismissed_round_trips() -> None:
    """A recorded dismissal reads back as dismissed for that user + identity."""
    store = DismissalStore()

    store.dismiss("U_A", "offer:abc")

    assert store.is_dismissed("U_A", "offer:abc") is True


def test_unrecorded_pair_is_not_dismissed() -> None:
    """A pair that was never recorded is not dismissed."""
    store = DismissalStore()

    assert store.is_dismissed("U_A", "offer:never") is False


def test_dismiss_is_idempotent() -> None:
    """Dismissing the same match twice stays a single membership (it is a set)."""
    store = DismissalStore()

    store.dismiss("U_A", "offer:abc")
    store.dismiss("U_A", "offer:abc")

    assert store.is_dismissed("U_A", "offer:abc") is True


# ----- per-user isolation (the headline guarantee) -----


def test_user_a_dismissal_does_not_hide_match_from_user_b() -> None:
    """A dismissal is personal: user B still sees what user A dismissed."""
    store = DismissalStore()
    match = _match(offer_id="uuid-shared")
    store.dismiss("U_A", identity_of(match))

    a_view = store.filter_dismissed("U_A", [match])
    b_view = store.filter_dismissed("U_B", [match])

    assert a_view == []  # A dismissed it -> hidden from A
    assert b_view == [match]  # B never dismissed it -> still visible to B


def test_filter_drops_only_dismissed_keeps_the_rest_in_order() -> None:
    """filter_dismissed removes dismissed matches and preserves the order of the rest."""
    store = DismissalStore()
    keep_first = _match(text="generator one", permalink="https://x/keep1")
    drop = _match(text="generator two", permalink="https://x/drop")
    keep_last = _match(text="generator three", permalink="https://x/keep2")
    store.dismiss("U_A", identity_of(drop))

    out = store.filter_dismissed("U_A", [keep_first, drop, keep_last])

    assert out == [keep_first, keep_last]


def test_filter_with_no_user_returns_all_matches() -> None:
    """An anonymous turn (no user id) filters nothing — we never guess whose dismissal applies."""
    store = DismissalStore()
    match = _match(offer_id="uuid-x")
    store.dismiss("U_A", identity_of(match))

    out = store.filter_dismissed("", [match])

    assert out == [match]


def test_filter_with_no_dismissals_returns_all_matches() -> None:
    """With nothing dismissed, every match passes through untouched."""
    store = DismissalStore()
    matches = [_match(permalink="https://x/a"), _match(permalink="https://x/b")]

    assert store.filter_dismissed("U_A", matches) == matches
