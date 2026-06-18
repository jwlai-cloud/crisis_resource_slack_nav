from datetime import UTC, datetime

from coordinator.situation import SituationFeed, SituationSnapshot
from listeners.views.app_home_builder import build_app_home_view
from listeners.views.feedback_builder import build_feedback_blocks
from mocks.server import EvacCentre, OfficialAdvice, RoadClosure


def test_build_feedback_blocks():
    blocks = build_feedback_blocks()

    assert len(blocks) > 0
    # The block should contain a feedback action
    block_dict = blocks[0].to_dict()
    action_ids = [e["action_id"] for e in block_dict["elements"]]
    assert "feedback" in action_ids


def _all_text(view: dict) -> str:
    """Flatten every rendered text string in the view for content assertions."""
    parts: list[str] = []
    for block in view["blocks"]:
        if block.get("type") == "header" or block.get("type") == "section":
            parts.append(block["text"]["text"])
        elif block.get("type") == "context":
            parts.extend(e["text"] for e in block["elements"])
    return "\n".join(parts)


def _situation(*, road_available: bool = True) -> SituationSnapshot:
    """A realistic Exmouth situation snapshot for the dashboard tests."""
    fetched = datetime(2026, 3, 14, 6, 30, tzinfo=UTC)
    road = (
        SituationFeed(
            feed="road_closures",
            available=True,
            fetched_at=fetched,
            records=(
                RoadClosure(
                    road="Minilya-Exmouth Road",
                    segment="Learmonth turnoff",
                    status="closed",
                    reason="floodwater over the road",
                    detour="none available",
                    updated_at=fetched,
                ),
            ),
        )
        if road_available
        else SituationFeed(
            feed="road_closures",
            available=False,
            detail="The road_closures feed is unavailable (simulated outage).",
        )
    )
    evac = SituationFeed(
        feed="evac_centres",
        available=True,
        fetched_at=fetched,
        records=(
            EvacCentre(
                name="Exmouth Recreation Centre",
                address="Murat Rd",
                status="open",
                capacity=200,
                occupancy=40,
                services=["water", "power"],
                updated_at=fetched,
            ),
        ),
    )
    advice = SituationFeed(
        feed="official_advice",
        available=True,
        fetched_at=fetched,
        records=(
            OfficialAdvice(
                title="Cyclone Narelle",
                level="Watch and Act",
                area="Exmouth",
                message="Severe tropical cyclone approaching.",
                advice="Prepare to shelter.",
                updated_at=fetched,
            ),
        ),
    )
    return SituationSnapshot(road_closures=road, evac_centres=evac, official_advice=advice)


class TestAppHomeBranding:
    def test_returns_a_home_view(self):
        view = build_app_home_view(situation=None, board_url=None)
        assert view["type"] == "home"

    def test_has_a_branded_header_and_what_it_does(self):
        view = build_app_home_view(situation=None, board_url=None)

        header = next(b for b in view["blocks"] if b["type"] == "header")
        assert "Crisis Resource Navigator" in header["text"]["text"]

        text = _all_text(view)
        # One-line "what it does" mentions surfacing needs/offers in this workspace.
        assert "plain language" in text.lower()

    def test_has_a_how_to_use_section(self):
        view = build_app_home_view(situation=None, board_url=None)
        text = _all_text(view)
        assert "How to use" in text
        # Posting a need or an offer in plain language.
        assert "need" in text.lower()
        assert "offer" in text.lower()

    def test_states_human_confirms_as_a_feature(self):
        view = build_app_home_view(situation=None, board_url=None)
        text = _all_text(view).lower()
        # The bounded-autonomy guardrail (g1) stated as a feature.
        assert "confirm" in text
        assert "human" in text

    def test_drops_the_mcp_status_block(self):
        view = build_app_home_view(situation=None, board_url=None)
        text = _all_text(view)
        # The OAuth-mode MCP connection status block is gone (Part B item 5).
        assert "MCP Server" not in text


class TestAppHomeSituation:
    def test_renders_a_present_situation_sourced_with_verify_note(self):
        view = build_app_home_view(situation=_situation(), board_url=None)
        text = _all_text(view)

        # A compact snapshot naming a road closure and an evac centre.
        assert "Minilya-Exmouth Road" in text
        assert "Exmouth Recreation Centre" in text
        # Sourced: the feed name + fetched stamp (guardrail 3).
        assert "road_closures" in text
        assert "fetched" in text.lower()
        # Verify-before-relying framing (guardrail 3).
        assert "verify" in text.lower()

    def test_names_a_degraded_feed_never_silent(self):
        view = build_app_home_view(situation=_situation(road_available=False), board_url=None)
        text = _all_text(view)

        # Degraded feed is named explicitly, not silently dropped (guardrail 4).
        assert "road_closures" in text
        assert "unavailable" in text.lower()

    def test_omits_situation_section_cleanly_when_none(self):
        view = build_app_home_view(situation=None, board_url=None)
        text = _all_text(view)

        # No situation heading and no verify note when there is no snapshot.
        assert "Current situation" not in text


class TestAppHomeBoardLink:
    def test_renders_open_the_cases_board_when_url_present(self):
        view = build_app_home_view(situation=None, board_url="https://acme.slack.com/docs/T1/C9")
        text = _all_text(view)
        assert "https://acme.slack.com/docs/T1/C9" in text
        assert "board" in text.lower()

    def test_omits_board_link_cleanly_when_absent(self):
        view = build_app_home_view(situation=None, board_url=None)
        text = _all_text(view)
        assert "cases board" not in text.lower()

    def test_never_asserts_safety(self):
        view = build_app_home_view(situation=_situation(), board_url=None)
        text = _all_text(view).lower()
        # The dashboard relays + frames; it never tells anyone it is safe to travel.
        assert "safe to travel" not in text
        assert "it is safe" not in text
