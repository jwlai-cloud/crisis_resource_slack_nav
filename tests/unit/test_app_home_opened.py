import logging
from unittest.mock import Mock

from slack_bolt import BoltContext
from slack_sdk import WebClient

from coordinator.situation import SituationFeed, SituationSnapshot
from listeners.events.app_home_opened import handle_app_home_opened

test_logger = logging.getLogger(__name__)

HANDLER_MODULE = "listeners.events.app_home_opened"


def _snapshot() -> SituationSnapshot:
    down = SituationFeed(feed="road_closures", available=False, detail="outage")
    empty = SituationFeed(feed="evac_centres", available=True, records=())
    advice = SituationFeed(feed="official_advice", available=True, records=())
    return SituationSnapshot(road_closures=down, evac_centres=empty, official_advice=advice)


class TestAppHomeOpened:
    def setup_method(self):
        self.fake_client = Mock(WebClient)
        self.fake_context = Mock(BoltContext)
        self.fake_context.user_id = "U123"
        self.fake_context.team_id = "T999"

    def test_publishes_home_view(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value=None)

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        self.fake_client.views_publish.assert_called_once()
        kwargs = self.fake_client.views_publish.call_args.kwargs
        assert kwargs["user_id"] == "U123"
        assert kwargs["view"]["type"] == "home"

    def test_passes_read_situation_into_the_builder(self, mocker):
        snapshot = _snapshot()
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=snapshot)
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value=None)
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        assert build.call_args.kwargs["situation"] is snapshot

    def test_builds_a_board_url_when_a_canvas_id_exists(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value="C9")
        self.fake_client.auth_test.return_value = {"url": "https://acme.slack.com/"}
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        board_url = build.call_args.kwargs["board_url"]
        assert board_url is not None
        assert "C9" in board_url
        assert "T999" in board_url

    def test_no_board_url_when_no_canvas_id(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value=None)
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        assert build.call_args.kwargs["board_url"] is None

    def test_situation_read_failure_degrades_to_none(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", side_effect=Exception("feed boom"))
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value=None)
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        # Act — must not crash; situation degrades to None.
        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        self.fake_client.views_publish.assert_called_once()
        assert build.call_args.kwargs["situation"] is None

    def test_canvas_read_failure_degrades_to_no_board_link(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", side_effect=Exception("io boom"))
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        self.fake_client.views_publish.assert_called_once()
        assert build.call_args.kwargs["board_url"] is None

    def test_team_url_resolution_failure_still_links_with_team_id(self, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value="C9")
        self.fake_client.auth_test.side_effect = Exception("auth boom")
        build = mocker.patch(
            f"{HANDLER_MODULE}.build_app_home_view",
            return_value={"type": "home", "blocks": []},
        )

        # Act — auth.test failing must not crash; falls back to slack.com form.
        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        board_url = build.call_args.kwargs["board_url"]
        assert board_url is not None
        assert "C9" in board_url

    def test_views_publish_exception_is_swallowed(self, caplog, mocker):
        mocker.patch(f"{HANDLER_MODULE}.read_situation", return_value=_snapshot())
        mocker.patch(f"{HANDLER_MODULE}.load_canvas_id", return_value=None)
        self.fake_client.views_publish.side_effect = Exception("test exception")

        handle_app_home_opened(
            client=self.fake_client,
            context=self.fake_context,
            logger=test_logger,
        )

        self.fake_client.views_publish.assert_called_once()
        assert "test exception" in caplog.text
