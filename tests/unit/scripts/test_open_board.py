"""Unit tests for scripts.open_board — the on-demand board entry point.

No live API: the WebClient and the board singleton's recreate are mocked. These
pin the exit-code contract — a missing user token fails fast (exit 1, no canvas
call), a failed create exits 1, and a successful create exits 0 — so the demo
operator gets a clear signal.
"""

from pytest_mock import MockerFixture

from scripts import open_board


def test_missing_user_token_exits_nonzero_without_calling_canvas(
    mocker: MockerFixture,
) -> None:
    """With no SLACK_USER_TOKEN the script fails fast and never touches the API."""
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value=None)
    recreate = mocker.patch("scripts.open_board.coordinator_board.recreate")

    rc = open_board.main()

    assert rc == 1
    recreate.assert_not_called()


def test_successful_create_exits_zero(mocker: MockerFixture) -> None:
    """A created canvas returns exit 0."""
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-user")
    mocker.patch("scripts.open_board.WebClient")
    mocker.patch("scripts.open_board.coordinator_board.recreate", return_value="F_BOARD")

    rc = open_board.main()

    assert rc == 0


def test_failed_create_exits_nonzero(mocker: MockerFixture) -> None:
    """A best-effort create that returns None (API down) surfaces as exit 1."""
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-user")
    mocker.patch("scripts.open_board.WebClient")
    mocker.patch("scripts.open_board.coordinator_board.recreate", return_value=None)

    rc = open_board.main()

    assert rc == 1


def test_recreate_called_with_resolved_token(mocker: MockerFixture) -> None:
    """The script passes the resolved user token through to recreate."""
    mocker.patch("scripts.open_board.load_dotenv")
    mocker.patch("scripts.open_board.resolve_user_token", return_value="xoxp-coordinator")
    client = mocker.patch("scripts.open_board.WebClient").return_value
    recreate = mocker.patch("scripts.open_board.coordinator_board.recreate", return_value="F_X")

    open_board.main()

    recreate.assert_called_once_with(client, "xoxp-coordinator")
