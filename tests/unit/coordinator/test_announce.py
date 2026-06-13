"""Unit tests for coordinator.announce — the one-shot board-link post.

When a board canvas is *created* (not on every edit), its link is posted once to
the ``COORDINATOR_CHANNEL`` so a coordinator can find and open it. Mirrors the
``CRISIS_CHANNEL`` env pattern: empty/unset = off. Best-effort: a post failure is
logged and swallowed, never raised. No live API — the WebClient is mocked.
"""

import pytest
from pytest_mock import MockerFixture

from coordinator import announce


@pytest.fixture(autouse=True)
def _clear_env(mocker: MockerFixture) -> None:
    """Each test sets COORDINATOR_CHANNEL explicitly; start from unset."""
    mocker.patch.dict("os.environ", {}, clear=False)
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: ""})


def test_coordinator_channel_id_off_when_unset(mocker: MockerFixture) -> None:
    """Unset COORDINATOR_CHANNEL reads as off (None)."""
    mocker.patch.dict("os.environ", {}, clear=False)
    import os

    os.environ.pop(announce.COORDINATOR_CHANNEL_ENV, None)

    assert announce.coordinator_channel_id() is None


def test_coordinator_channel_id_trims_and_reads_value(mocker: MockerFixture) -> None:
    """A configured channel id is returned, whitespace-trimmed."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: "  C_COORD \n"})

    assert announce.coordinator_channel_id() == "C_COORD"


def test_announce_skipped_when_channel_off(mocker: MockerFixture) -> None:
    """With COORDINATOR_CHANNEL empty, no message is posted."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: ""})
    client = mocker.Mock()

    announce.announce_board(client, canvas_id="F_BOARD", team_id="T1")

    client.chat_postMessage.assert_not_called()


def test_announce_posts_once_to_configured_channel(mocker: MockerFixture) -> None:
    """A configured channel gets exactly one chat_postMessage with the canvas link."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()

    announce.announce_board(client, canvas_id="F_BOARD", team_id="T_TEAM")

    client.chat_postMessage.assert_called_once()
    kwargs = client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C_COORD"
    assert "F_BOARD" in kwargs["text"]
    assert "T_TEAM" in kwargs["text"]  # link is constructed from team + canvas id


def test_announce_posts_without_team_id(mocker: MockerFixture) -> None:
    """No team id still posts a discoverable message naming the canvas id."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()

    announce.announce_board(client, canvas_id="F_BOARD", team_id=None)

    client.chat_postMessage.assert_called_once()
    kwargs = client.chat_postMessage.call_args.kwargs
    assert kwargs["channel"] == "C_COORD"
    assert "F_BOARD" in kwargs["text"]


def test_announce_swallows_post_failure(mocker: MockerFixture) -> None:
    """A chat_postMessage failure is logged and swallowed — never raised."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.chat_postMessage.side_effect = RuntimeError("channel_not_found")

    # Must not raise.
    announce.announce_board(client, canvas_id="F_BOARD", team_id="T1")


def test_canvas_link_constructs_docs_url_with_team() -> None:
    """The link form is the standalone-canvas docs URL when a team id is known."""
    link = announce.canvas_link(canvas_id="F_BOARD", team_id="T_TEAM")

    assert link == "https://slack.com/docs/T_TEAM/F_BOARD"


def test_canvas_link_none_without_team() -> None:
    """Without a team id we cannot build the docs URL — return None, post bare id instead."""
    assert announce.canvas_link(canvas_id="F_BOARD", team_id=None) is None


def test_announce_forwards_user_token(mocker: MockerFixture) -> None:
    """A given user_token is passed to chat_postMessage as the per-call override."""
    mocker.patch.dict("os.environ", {announce.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()

    announce.announce_board(client, canvas_id="F_BOARD", team_id="T_TEAM", user_token="xoxp-u")

    assert client.chat_postMessage.call_args.kwargs["token"] == "xoxp-u"
