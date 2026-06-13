"""Unit tests for coordinator.canvas — the find-or-create + update publisher.

No live API: the ``WebClient`` is a mock so ``canvases_create`` / ``canvases_edit``
calls are asserted by argument. These tests pin the lifecycle (create once, then
edit), the full-replace edit shape, the user-token Authorization-header contract,
recreate, the no-token skip, and the best-effort guarantee that an API failure
logs and never raises.
"""

from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from coordinator.board import BOARD_TITLE
from coordinator.canvas import CoordinatorBoard, update_board
from entities import Offer

USER_TOKEN = "xoxp-user-token"


@pytest.fixture
def fresh_board() -> CoordinatorBoard:
    """A board with no stored canvas id, isolated from the module singleton."""
    return CoordinatorBoard()


def _client(mocker: MockerFixture, *, canvas_id: str = "F_BOARD"):
    """A mocked WebClient whose canvases_create returns a canvas id."""
    client = mocker.Mock()
    client.canvases_create.return_value = {"ok": True, "canvas_id": canvas_id}
    return client


def test_first_publish_creates_canvas_with_title_and_markdown(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The first publish calls canvases_create with the board title + markdown content."""
    client = _client(mocker, canvas_id="F_NEW")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_NEW"
    client.canvases_create.assert_called_once()
    kwargs = client.canvases_create.call_args.kwargs
    assert kwargs["title"] == BOARD_TITLE
    assert kwargs["document_content"]["type"] == "markdown"
    assert BOARD_TITLE in kwargs["document_content"]["markdown"]
    client.canvases_edit.assert_not_called()


def test_create_authenticates_as_user_via_authorization_header(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The canvas write carries the user token as a per-call Authorization header."""
    client = _client(mocker, canvas_id="F_NEW")

    fresh_board.publish(client, USER_TOKEN)

    headers = client.canvases_create.call_args.kwargs["headers"]
    assert headers == {"Authorization": f"Bearer {USER_TOKEN}"}


def test_canvas_id_stored_after_create(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The created canvas id is held on the board for later updates."""
    client = _client(mocker, canvas_id="F_HELD")

    fresh_board.publish(client, USER_TOKEN)

    assert fresh_board.canvas_id == "F_HELD"


def test_second_publish_edits_existing_canvas_with_full_replace(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """Once created, a publish edits via a single full-document replace op."""
    client = _client(mocker, canvas_id="F_BOARD")
    fresh_board.publish(client, USER_TOKEN)  # create

    fresh_board.publish(client, USER_TOKEN)  # update

    client.canvases_create.assert_called_once()  # not created again
    client.canvases_edit.assert_called_once()
    kwargs = client.canvases_edit.call_args.kwargs
    assert kwargs["canvas_id"] == "F_BOARD"
    assert kwargs["headers"] == {"Authorization": f"Bearer {USER_TOKEN}"}
    changes = kwargs["changes"]
    assert len(changes) == 1
    assert changes[0]["operation"] == "replace"
    assert "section_id" not in changes[0]  # no section id = replace whole document
    assert changes[0]["document_content"]["type"] == "markdown"


def test_recreate_drops_id_and_creates_fresh_canvas(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """recreate forces a brand-new canvas even when one already exists."""
    client = _client(mocker, canvas_id="F_FIRST")
    fresh_board.publish(client, USER_TOKEN)
    client.canvases_create.return_value = {"ok": True, "canvas_id": "F_SECOND"}

    new_id = fresh_board.recreate(client, USER_TOKEN)

    assert new_id == "F_SECOND"
    assert fresh_board.canvas_id == "F_SECOND"
    assert client.canvases_create.call_count == 2
    client.canvases_edit.assert_not_called()


def test_publish_without_user_token_is_skipped(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """With no user token the publish is skipped — never falls back to the bot token."""
    client = _client(mocker)

    result = fresh_board.publish(client, None)

    assert result is None
    assert fresh_board.canvas_id is None
    client.canvases_create.assert_not_called()
    client.canvases_edit.assert_not_called()


def test_publish_swallows_create_failure_and_returns_none(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A canvases_create failure is logged and swallowed — never raised."""
    client = mocker.Mock()
    client.canvases_create.side_effect = RuntimeError("canvas_creation_failed")

    result = fresh_board.publish(client, USER_TOKEN)

    assert result is None
    assert fresh_board.canvas_id is None  # no id stored on failure


def test_publish_swallows_edit_failure_and_returns_none(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A canvases_edit failure on update is logged and swallowed — never raised."""
    client = _client(mocker, canvas_id="F_BOARD")
    fresh_board.publish(client, USER_TOKEN)  # create succeeds
    client.canvases_edit.side_effect = RuntimeError("edit_failed")

    result = fresh_board.publish(client, USER_TOKEN)

    assert result is None


def test_publish_swallows_missing_canvas_id_in_response(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A create response with no canvas_id degrades quietly (KeyError caught)."""
    client = mocker.Mock()
    client.canvases_create.return_value = {"ok": True}

    result = fresh_board.publish(client, USER_TOKEN)

    assert result is None
    assert fresh_board.canvas_id is None


def test_publish_renders_current_index_and_audit_state(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
) -> None:
    """publish composes from the live offer index + audit trail singletons."""
    offer = make_offer(offerer="U_LIVE", resource_type="defibrillator")
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    markdown = client.canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "defibrillator" in markdown
    assert "<@U_LIVE>" in markdown


def test_update_board_helper_delegates_to_singleton_publish(
    mocker: MockerFixture,
) -> None:
    """The handler-facing helper refreshes the board via the singleton's publish."""
    client = mocker.Mock()
    publish = mocker.patch("coordinator.canvas.coordinator_board.publish", return_value="F_BOARD")

    update_board(client, USER_TOKEN)

    publish.assert_called_once_with(client, USER_TOKEN)


def test_update_board_helper_swallows_publish_failure(
    mocker: MockerFixture,
) -> None:
    """update_board never raises even if the underlying publish path errors out.

    publish is best-effort and returns None on failure; update_board ignores the
    result and adds no raising path, so a board failure can never break a handler.
    """
    client = mocker.Mock()
    mocker.patch("coordinator.canvas.coordinator_board.publish", return_value=None)

    # Must not raise.
    assert update_board(client, USER_TOKEN) is None
