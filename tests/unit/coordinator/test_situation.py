"""Unit tests for coordinator.situation — the official-feed read boundary.

The reader calls the three mock feed functions (``get_road_closures`` /
``get_evac_centres`` / ``get_official_advice``) and normalizes each into a
:class:`SituationFeed` the pure board composer can render. These tests mock the
feed functions (no real file / MCP dependency) and pin:

* **happy path** — three FeedResults normalize to three available, stamped feeds
  carrying their records (sourcing guardrail);
* **degraded** — a feed that returned a FeedError becomes an explicit unavailable
  marker with its detail, never a dropped feed (guardrail 4);
* **all down** — every feed unavailable still yields a coherent snapshot;
* **best-effort** — an *unexpected* exception from a feed function degrades that one
  feed to unavailable rather than raising.
"""

from datetime import UTC, datetime

from pytest_mock import MockerFixture

from coordinator.situation import SituationSnapshot, read_situation
from mocks.server import (
    EvacCentre,
    FeedError,
    FeedResult,
    OfficialAdvice,
    RoadClosure,
)

FETCHED_AT = datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
UPDATED_AT = datetime(2026, 3, 15, 5, 30, tzinfo=UTC)


def _road_result() -> FeedResult:
    """A road_closures FeedResult with one Narelle closure record."""
    return FeedResult(
        feed="road_closures",
        fetched_at=FETCHED_AT,
        records=[
            RoadClosure(
                road="Minilya-Exmouth Road",
                segment="Yannarie River crossing",
                status="CLOSED",
                reason="Floodwater over road.",
                detour="No detour available.",
                updated_at=UPDATED_AT,
            )
        ],
    )


def _evac_result() -> FeedResult:
    """An evac_centres FeedResult with one centre that has a water point."""
    return FeedResult(
        feed="evac_centres",
        fetched_at=FETCHED_AT,
        records=[
            EvacCentre(
                name="Exmouth Recreation Centre",
                address="Murat Road, Exmouth WA 6707",
                status="OPEN",
                capacity=250,
                occupancy=168,
                services=["Emergency water point", "Bedding and shelter"],
                updated_at=UPDATED_AT,
            )
        ],
    )


def _advice_result() -> FeedResult:
    """An official_advice FeedResult with one water-point notice."""
    return FeedResult(
        feed="official_advice",
        fetched_at=FETCHED_AT,
        records=[
            OfficialAdvice(
                title="Emergency water point now open",
                level="Advice",
                area="Exmouth",
                message="An emergency drinking-water point is operating at the Rec Centre.",
                advice="Collect drinking water from the Recreation Centre water point.",
                updated_at=UPDATED_AT,
            )
        ],
    )


def _patch_feeds(
    mocker: MockerFixture,
    *,
    road: object,
    evac: object,
    advice: object,
) -> None:
    """Patch the three feed functions where the reader imported them."""
    mocker.patch("coordinator.situation.get_road_closures", return_value=road)
    mocker.patch("coordinator.situation.get_evac_centres", return_value=evac)
    mocker.patch("coordinator.situation.get_official_advice", return_value=advice)


def test_happy_path_three_results_normalize_to_available_feeds(mocker: MockerFixture) -> None:
    """Three FeedResults become three available, stamped feeds carrying their records."""
    _patch_feeds(mocker, road=_road_result(), evac=_evac_result(), advice=_advice_result())

    snapshot = read_situation()

    assert isinstance(snapshot, SituationSnapshot)
    for feed in (snapshot.road_closures, snapshot.evac_centres, snapshot.official_advice):
        assert feed.available is True
        # fetched-at is the trust stamp carried through from the feed (guardrail 3).
        assert feed.fetched_at == FETCHED_AT
        assert feed.records
    assert snapshot.road_closures.feed == "road_closures"
    assert snapshot.evac_centres.feed == "evac_centres"
    assert snapshot.official_advice.feed == "official_advice"


def test_records_are_carried_through_unchanged(mocker: MockerFixture) -> None:
    """The reader passes the typed records straight through for the composer to render."""
    _patch_feeds(mocker, road=_road_result(), evac=_evac_result(), advice=_advice_result())

    snapshot = read_situation()

    road = snapshot.road_closures.records[0]
    assert isinstance(road, RoadClosure)
    assert road.road == "Minilya-Exmouth Road"
    evac = snapshot.evac_centres.records[0]
    assert isinstance(evac, EvacCentre)
    assert any("water" in service.lower() for service in evac.services)


def test_degraded_feed_becomes_explicit_unavailable_marker(mocker: MockerFixture) -> None:
    """A feed that returned a FeedError is marked unavailable with its detail, not dropped."""
    error = FeedError(
        feed="road_closures",
        error="feed_down",
        detail="The road_closures feed is unavailable (simulated outage).",
    )
    _patch_feeds(mocker, road=error, evac=_evac_result(), advice=_advice_result())

    snapshot = read_situation()

    down = snapshot.road_closures
    assert down.feed == "road_closures"
    assert down.available is False
    assert down.fetched_at is None
    assert down.records == ()
    assert "unavailable" in down.detail.lower()
    # The other two still load — per-feed isolation.
    assert snapshot.evac_centres.available is True
    assert snapshot.official_advice.available is True


def test_all_feeds_down_still_yields_coherent_snapshot(mocker: MockerFixture) -> None:
    """Every feed down is still a full snapshot — three named, unavailable feeds."""
    _patch_feeds(
        mocker,
        road=FeedError(feed="road_closures", error="feed_down", detail="down"),
        evac=FeedError(feed="evac_centres", error="feed_down", detail="down"),
        advice=FeedError(feed="official_advice", error="feed_unavailable", detail="gone"),
    )

    snapshot = read_situation()

    for feed in (snapshot.road_closures, snapshot.evac_centres, snapshot.official_advice):
        assert feed.available is False
        assert feed.records == ()


def test_unexpected_exception_degrades_that_feed_to_unavailable(mocker: MockerFixture) -> None:
    """An unexpected raise from a feed function degrades that feed — never propagates."""
    mocker.patch("coordinator.situation.get_road_closures", side_effect=RuntimeError("boom"))
    mocker.patch("coordinator.situation.get_evac_centres", return_value=_evac_result())
    mocker.patch("coordinator.situation.get_official_advice", return_value=_advice_result())

    snapshot = read_situation()

    assert snapshot.road_closures.available is False
    assert snapshot.road_closures.feed == "road_closures"
    assert snapshot.road_closures.detail
    # The healthy feeds are unaffected.
    assert snapshot.evac_centres.available is True
    assert snapshot.official_advice.available is True


def test_read_situation_never_raises_when_all_feeds_explode(mocker: MockerFixture) -> None:
    """Even with every feed raising, the reader returns a coherent all-down snapshot."""
    mocker.patch("coordinator.situation.get_road_closures", side_effect=RuntimeError("a"))
    mocker.patch("coordinator.situation.get_evac_centres", side_effect=RuntimeError("b"))
    mocker.patch("coordinator.situation.get_official_advice", side_effect=RuntimeError("c"))

    snapshot = read_situation()

    assert isinstance(snapshot, SituationSnapshot)
    assert not snapshot.road_closures.available
    assert not snapshot.evac_centres.available
    assert not snapshot.official_advice.available
