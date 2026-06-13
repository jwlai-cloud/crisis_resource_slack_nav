"""Unit tests for coordinator.bookmark — the persistent channel quick link.

On board create/recreate a single "Community Cases board" channel bookmark is
added (or updated in place) in ``COORDINATOR_CHANNEL`` pointing at the board
canvas, so coordinators have an always-visible top-bar link that never scrolls
away. Mirrors the announce posture exactly:

* ``COORDINATOR_CHANNEL`` empty/unset = off; nothing happens.
* Idempotent: ``bookmarks_list`` first; an existing bookmark with the title is
  ``bookmarks_edit``-ed to the new url, otherwise ``bookmarks_add``-ed — never a
  duplicate on a re-run.
* Best-effort: any API failure is logged and swallowed, never raised, so a
  bookmark problem can never break the board create it is hooked into.

No live API — the ``WebClient`` is mocked.
"""

import pytest
from pytest_mock import MockerFixture

from coordinator import bookmark


@pytest.fixture(autouse=True)
def _clear_env(mocker: MockerFixture) -> None:
    """Each test sets COORDINATOR_CHANNEL explicitly; start from unset."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: ""})


def _list_response(mocker: MockerFixture, bookmarks: list[dict[str, str]]):
    """A mocked bookmarks.list response carrying the given bookmark records."""
    return {"ok": True, "bookmarks": bookmarks}


def test_skipped_when_channel_off(mocker: MockerFixture) -> None:
    """With COORDINATOR_CHANNEL empty, no bookmark API call is made at all."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: ""})
    client = mocker.Mock()

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    client.bookmarks_list.assert_not_called()
    client.bookmarks_add.assert_not_called()
    client.bookmarks_edit.assert_not_called()


def test_skipped_when_link_is_none(mocker: MockerFixture) -> None:
    """No usable link (no team id upstream) -> no bookmark; can't point at nothing."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()

    bookmark.upsert_board_bookmark(client, link=None)

    client.bookmarks_list.assert_not_called()
    client.bookmarks_add.assert_not_called()
    client.bookmarks_edit.assert_not_called()


def test_adds_bookmark_when_absent(mocker: MockerFixture) -> None:
    """No existing board bookmark -> bookmarks_add with the title, link, and type=link."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.return_value = _list_response(mocker, [])

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    client.bookmarks_list.assert_called_once()
    assert client.bookmarks_list.call_args.kwargs["channel_id"] == "C_COORD"
    client.bookmarks_add.assert_called_once()
    add_kwargs = client.bookmarks_add.call_args.kwargs
    assert add_kwargs["channel_id"] == "C_COORD"
    assert add_kwargs["title"] == bookmark.BOOKMARK_TITLE
    assert add_kwargs["type"] == "link"
    assert add_kwargs["link"] == "https://slack.com/docs/T1/F_BOARD"
    client.bookmarks_edit.assert_not_called()


def test_edits_bookmark_when_present(mocker: MockerFixture) -> None:
    """An existing board bookmark with the title -> bookmarks_edit to the new url."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.return_value = _list_response(
        mocker,
        [
            {"id": "Bk_OTHER", "title": "Some other link"},
            {"id": "Bk_BOARD", "title": bookmark.BOOKMARK_TITLE},
        ],
    )

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_NEW")

    client.bookmarks_add.assert_not_called()
    client.bookmarks_edit.assert_called_once()
    edit_kwargs = client.bookmarks_edit.call_args.kwargs
    assert edit_kwargs["bookmark_id"] == "Bk_BOARD"
    assert edit_kwargs["channel_id"] == "C_COORD"
    assert edit_kwargs["link"] == "https://slack.com/docs/T1/F_NEW"


def test_re_run_does_not_duplicate(mocker: MockerFixture) -> None:
    """Two upserts against a channel that now holds the bookmark only ever edit."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    # First call: absent -> add.
    client.bookmarks_list.return_value = _list_response(mocker, [])
    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")
    # Second call: now present -> edit, not a second add.
    client.bookmarks_list.return_value = _list_response(
        mocker, [{"id": "Bk_BOARD", "title": bookmark.BOOKMARK_TITLE}]
    )

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    assert client.bookmarks_add.call_count == 1
    assert client.bookmarks_edit.call_count == 1


def test_forwards_user_token(mocker: MockerFixture) -> None:
    """A given user_token is the per-call token override on every bookmark call."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.return_value = _list_response(mocker, [])

    bookmark.upsert_board_bookmark(
        client, link="https://slack.com/docs/T1/F_BOARD", user_token="xoxp-u"
    )

    assert client.bookmarks_list.call_args.kwargs["token"] == "xoxp-u"
    assert client.bookmarks_add.call_args.kwargs["token"] == "xoxp-u"


def test_no_token_override_when_user_token_absent(mocker: MockerFixture) -> None:
    """Without a user token the client's own (bot) token is used — no token kwarg."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.return_value = _list_response(mocker, [])

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    assert "token" not in client.bookmarks_list.call_args.kwargs
    assert "token" not in client.bookmarks_add.call_args.kwargs


def test_malformed_matching_entry_without_id_falls_through_to_add(mocker: MockerFixture) -> None:
    """A title-matching bookmark with no id is skipped — upsert adds rather than KeyErrors."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    # Title matches but the record is missing its id (malformed list response).
    client.bookmarks_list.return_value = _list_response(
        mocker, [{"title": bookmark.BOOKMARK_TITLE}]
    )

    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    client.bookmarks_edit.assert_not_called()
    client.bookmarks_add.assert_called_once()


def test_swallows_list_failure(mocker: MockerFixture) -> None:
    """A bookmarks_list failure is logged and swallowed — never raised."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.side_effect = RuntimeError("missing_scope")

    # Must not raise.
    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")

    client.bookmarks_add.assert_not_called()
    client.bookmarks_edit.assert_not_called()


def test_swallows_add_failure(mocker: MockerFixture) -> None:
    """A bookmarks_add failure is logged and swallowed — never raised."""
    mocker.patch.dict("os.environ", {bookmark.COORDINATOR_CHANNEL_ENV: "C_COORD"})
    client = mocker.Mock()
    client.bookmarks_list.return_value = _list_response(mocker, [])
    client.bookmarks_add.side_effect = RuntimeError("channel_not_found")

    # Must not raise.
    bookmark.upsert_board_bookmark(client, link="https://slack.com/docs/T1/F_BOARD")
