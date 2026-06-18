"""Unit tests for scripts.open_board — the on-demand board entry point.

No live API: the WebClient and the board singleton are mocked. These pin the
exit-code contract — a missing user token fails fast (exit 1, no canvas call), a
failed open exits 1, success exits 0 — and the default-vs-fresh routing: the default
REUSES the board (``publish``), while ``--fresh`` routes to ``recreate``. Both reuse
the one titled tab and never delete (task 027); ``recreate`` is a clean-re-render
alias, so repeated ``make board`` never piles up canvases.

``sys.argv`` is stubbed per test so argparse doesn't read pytest's own argv.
"""

from pytest_mock import MockerFixture

from scripts import open_board


def _argv(mocker: MockerFixture, *args: str) -> None:
    """Stub sys.argv so argparse sees only the flags the test intends."""
    mocker.patch("sys.argv", ["open_board", *args])


def test_missing_user_token_exits_nonzero_without_calling_canvas(
    mocker: MockerFixture,
) -> None:
    """With no SLACK_USER_TOKEN the script fails fast and never touches the API."""
    _argv(mocker)
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value=None)
    publish = mocker.patch("scripts.open_board.coordinator_board.publish")
    recreate = mocker.patch("scripts.open_board.coordinator_board.recreate")

    rc = open_board.main()

    assert rc == 1
    publish.assert_not_called()
    recreate.assert_not_called()


def test_default_reuses_board_via_publish(mocker: MockerFixture) -> None:
    """Default (no --fresh): the script REUSES the board via publish; exit 0."""
    _argv(mocker)
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-coordinator")
    client = mocker.patch("scripts.open_board.WebClient").return_value
    client.auth_test.return_value = {"team_id": "T_TEAM", "url": "https://acme.slack.com/"}
    publish = mocker.patch("scripts.open_board.coordinator_board.publish", return_value="F_X")
    recreate = mocker.patch("scripts.open_board.coordinator_board.recreate")

    rc = open_board.main()

    assert rc == 0
    publish.assert_called_once_with(client, "xoxp-coordinator", "T_TEAM", "https://acme.slack.com/")
    recreate.assert_not_called()


def test_fresh_flag_recreates(mocker: MockerFixture) -> None:
    """--fresh routes to recreate (reuse + clean re-render, never delete); exit 0."""
    _argv(mocker, "--fresh")
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-coordinator")
    client = mocker.patch("scripts.open_board.WebClient").return_value
    client.auth_test.return_value = {"team_id": "T_TEAM", "url": "https://acme.slack.com/"}
    recreate = mocker.patch("scripts.open_board.coordinator_board.recreate", return_value="F_X")
    publish = mocker.patch("scripts.open_board.coordinator_board.publish")

    rc = open_board.main()

    assert rc == 0
    recreate.assert_called_once_with(
        client, "xoxp-coordinator", "T_TEAM", "https://acme.slack.com/"
    )
    publish.assert_not_called()


def test_failed_open_exits_nonzero(mocker: MockerFixture) -> None:
    """A best-effort open that returns None (API down) surfaces as exit 1."""
    _argv(mocker)
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-user")
    client = mocker.patch("scripts.open_board.WebClient").return_value
    client.auth_test.return_value = {"team_id": "T_TEAM", "url": "https://acme.slack.com/"}
    mocker.patch("scripts.open_board.coordinator_board.publish", return_value=None)

    rc = open_board.main()

    assert rc == 1


def test_team_id_failure_degrades_to_none_without_aborting(mocker: MockerFixture) -> None:
    """An auth.test failure still opens the board — publish gets team_id=None."""
    _argv(mocker)
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-coordinator")
    client = mocker.patch("scripts.open_board.WebClient").return_value
    client.auth_test.side_effect = RuntimeError("auth down")
    publish = mocker.patch("scripts.open_board.coordinator_board.publish", return_value="F_X")

    rc = open_board.main()

    assert rc == 0
    publish.assert_called_once_with(client, "xoxp-coordinator", None, None)
