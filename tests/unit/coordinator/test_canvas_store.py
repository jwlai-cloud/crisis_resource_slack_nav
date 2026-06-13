"""Unit tests for coordinator.canvas_store — the cross-process canvas-id file.

The id store is the shared handle that lets the ``make board`` script process and
the live agent process operate on the *same* canvas instead of each minting its
own (task 018). It is best-effort: a read of a missing/corrupt file returns
``None`` (so the caller mints a fresh canvas) and any I/O error on write is logged
and swallowed — never raised. No real ``.slack/`` writes here: every test points
the store at ``tmp_path``.
"""

from pathlib import Path

from pytest_mock import MockerFixture

from coordinator import canvas_store


def test_load_returns_none_when_file_missing(tmp_path: Path, mocker: MockerFixture) -> None:
    """A missing id file reads as None — the caller then creates a fresh canvas."""
    mocker.patch.object(canvas_store, "_id_path", return_value=tmp_path / "board_canvas_id")

    assert canvas_store.load_canvas_id() is None


def test_save_then_load_round_trips_the_id(tmp_path: Path, mocker: MockerFixture) -> None:
    """An id written by one process is read back verbatim by another."""
    path = tmp_path / "board_canvas_id"
    mocker.patch.object(canvas_store, "_id_path", return_value=path)

    canvas_store.save_canvas_id("F_PERSISTED")

    assert canvas_store.load_canvas_id() == "F_PERSISTED"


def test_save_creates_parent_directory(tmp_path: Path, mocker: MockerFixture) -> None:
    """The store mkdirs the .slack parent so the first write never fails on a fresh checkout."""
    path = tmp_path / ".slack" / "board_canvas_id"
    mocker.patch.object(canvas_store, "_id_path", return_value=path)

    canvas_store.save_canvas_id("F_NEW")

    assert path.read_text(encoding="utf-8").strip() == "F_NEW"


def test_load_strips_surrounding_whitespace(tmp_path: Path, mocker: MockerFixture) -> None:
    """A trailing newline in the file does not bleed into the returned id."""
    path = tmp_path / "board_canvas_id"
    path.write_text("  F_TRIMMED \n", encoding="utf-8")
    mocker.patch.object(canvas_store, "_id_path", return_value=path)

    assert canvas_store.load_canvas_id() == "F_TRIMMED"


def test_load_returns_none_for_empty_file(tmp_path: Path, mocker: MockerFixture) -> None:
    """A whitespace-only / empty file reads as None (corrupt -> degrade to create)."""
    path = tmp_path / "board_canvas_id"
    path.write_text("   \n", encoding="utf-8")
    mocker.patch.object(canvas_store, "_id_path", return_value=path)

    assert canvas_store.load_canvas_id() is None


def test_load_swallows_read_error_and_returns_none(tmp_path: Path, mocker: MockerFixture) -> None:
    """An OS error reading the file is logged and degrades to None — never raised."""
    path = tmp_path / "board_canvas_id"
    mocker.patch.object(canvas_store, "_id_path", return_value=path)
    mocker.patch.object(Path, "read_text", side_effect=OSError("disk gone"))
    # Make the file appear to exist so read_text is reached.
    mocker.patch.object(Path, "exists", return_value=True)

    assert canvas_store.load_canvas_id() is None


def test_save_swallows_write_error(tmp_path: Path, mocker: MockerFixture) -> None:
    """An OS error writing the file is logged and swallowed — never raised."""
    path = tmp_path / "board_canvas_id"
    mocker.patch.object(canvas_store, "_id_path", return_value=path)
    mocker.patch.object(Path, "write_text", side_effect=OSError("read-only fs"))

    # Must not raise.
    canvas_store.save_canvas_id("F_FAILS")


def test_id_path_points_into_slack_state_dir() -> None:
    """The default location is the gitignored .slack/board_canvas_id app-state file."""
    path = canvas_store._id_path()

    assert path.name == "board_canvas_id"
    assert path.parent.name == ".slack"
