"""Unit tests for coordinator.canvas — the channel-canvas find-or-create publisher.

The board is the **channel canvas** of ``CRISIS_CHANNEL`` (task 025, ADR-0005): a
permanent top-bar tab, not a standalone canvas behind a bookmark. No live API: the
``WebClient`` is a mock so ``conversations_canvases_create`` / ``canvases_edit`` /
``conversations_info`` calls are asserted by argument. These tests pin the
find-or-create order (persisted id -> conversations.info discovery -> create on the
channel), the full-replace edit shape, the user-token override contract, recreate,
the no-token skip, the best-effort guarantee that an API failure logs and never
raises, and that the obsolete bookmark upsert is no longer called from the create
path.
"""

from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture
from slack_sdk.errors import SlackApiError

from coordinator.board import BOARD_TITLE
from coordinator.canvas import CoordinatorBoard, update_board
from entities import Offer
from matching.audit import AuditEvent

USER_TOKEN = "xoxp-user-token"
CRISIS_CHANNEL = "C_CRISIS"


@pytest.fixture(autouse=True)
def _set_crisis_channel(mocker: MockerFixture) -> None:
    """The channel canvas attaches to CRISIS_CHANNEL; pin it for every test.

    The publisher reads the channel via ``listeners.channel_gate.designated_channel_id``
    (no duplicated env read), so patch that one helper rather than the env var.
    """
    mocker.patch("coordinator.canvas.designated_channel_id", return_value=CRISIS_CHANNEL)


@pytest.fixture
def fresh_board() -> CoordinatorBoard:
    """A board with no stored canvas id, isolated from the module singleton."""
    return CoordinatorBoard()


def _client(mocker: MockerFixture, *, canvas_id: str = "F_BOARD"):
    """A mocked WebClient whose conversations_canvases_create returns a canvas id.

    By default ``conversations_info`` reports no existing channel canvas (empty
    ``properties``), so the find-or-create falls through to the create path unless a
    test re-stubs it.
    """
    client = mocker.Mock()
    client.conversations_canvases_create.return_value = {"ok": True, "canvas_id": canvas_id}
    client.conversations_info.return_value = {"ok": True, "channel": {"properties": {}}}
    return client


def _slack_api_error(error: str) -> SlackApiError:
    """A SlackApiError carrying ``error`` in its response (what slack_sdk raises)."""
    return SlackApiError(message=error, response={"ok": False, "error": error})


# --- create-on-the-channel (the new mechanism, task 025) --------------------


def test_first_publish_creates_channel_canvas_with_markdown(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The first publish creates the CRISIS_CHANNEL channel canvas with board markdown."""
    client = _client(mocker, canvas_id="F_NEW")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_NEW"
    client.conversations_canvases_create.assert_called_once()
    kwargs = client.conversations_canvases_create.call_args.kwargs
    assert kwargs["channel_id"] == CRISIS_CHANNEL
    assert kwargs["document_content"]["type"] == "markdown"
    assert BOARD_TITLE in kwargs["document_content"]["markdown"]
    # The board is a channel canvas now, never a standalone one.
    client.canvases_create.assert_not_called()
    client.canvases_edit.assert_not_called()


def test_create_authenticates_as_user_via_token_override(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The channel-canvas create carries the user token as a per-call token override."""
    client = _client(mocker, canvas_id="F_NEW")

    fresh_board.publish(client, USER_TOKEN)

    assert client.conversations_canvases_create.call_args.kwargs["token"] == USER_TOKEN


def test_canvas_id_stored_after_create(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The created canvas id is held on the board for later updates."""
    client = _client(mocker, canvas_id="F_HELD")

    fresh_board.publish(client, USER_TOKEN)

    assert fresh_board.canvas_id == "F_HELD"


def test_publish_skipped_when_no_crisis_channel(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """With CRISIS_CHANNEL unset there is no channel to attach the canvas to."""
    mocker.patch("coordinator.canvas.designated_channel_id", return_value=None)
    client = _client(mocker)
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)

    result = fresh_board.publish(client, USER_TOKEN)

    assert result is None
    assert fresh_board.canvas_id is None
    client.conversations_canvases_create.assert_not_called()


# --- edit path unchanged ----------------------------------------------------


def test_second_publish_edits_existing_canvas_with_full_replace(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """Once created, a publish edits via a single full-document replace op (unchanged)."""
    client = _client(mocker, canvas_id="F_BOARD")
    fresh_board.publish(client, USER_TOKEN)  # create

    fresh_board.publish(client, USER_TOKEN)  # update

    client.conversations_canvases_create.assert_called_once()  # not created again
    client.canvases_edit.assert_called_once()
    kwargs = client.canvases_edit.call_args.kwargs
    assert kwargs["canvas_id"] == "F_BOARD"
    assert kwargs["token"] == USER_TOKEN
    changes = kwargs["changes"]
    assert len(changes) == 1
    assert changes[0]["operation"] == "replace"
    assert "section_id" not in changes[0]  # no section id = replace whole document
    assert changes[0]["document_content"]["type"] == "markdown"


# --- recreate ---------------------------------------------------------------


def test_recreate_drops_id_and_creates_fresh_channel_canvas(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """recreate forces a brand-new channel canvas even when one already exists.

    The old canvas is deleted first, so a fresh create on the channel no longer
    collides with ``channel_canvas_already_exists``.
    """
    client = _client(mocker, canvas_id="F_FIRST")
    fresh_board.publish(client, USER_TOKEN)
    client.conversations_canvases_create.return_value = {"ok": True, "canvas_id": "F_SECOND"}

    new_id = fresh_board.recreate(client, USER_TOKEN)

    assert new_id == "F_SECOND"
    assert fresh_board.canvas_id == "F_SECOND"
    assert client.conversations_canvases_create.call_count == 2
    client.canvases_edit.assert_not_called()
    # the prior canvas is deleted, not orphaned
    client.canvases_delete.assert_called_once_with(canvas_id="F_FIRST", token=USER_TOKEN)


# --- no-token + best-effort -------------------------------------------------


def test_publish_without_user_token_is_skipped(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """With no user token the publish is skipped — never falls back to the bot token."""
    client = _client(mocker)

    result = fresh_board.publish(client, None)

    assert result is None
    assert fresh_board.canvas_id is None
    client.conversations_canvases_create.assert_not_called()
    client.canvases_edit.assert_not_called()


def test_publish_swallows_create_failure_and_returns_none(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A channel-canvas create failure is logged and swallowed — never raised."""
    client = mocker.Mock()
    client.conversations_info.return_value = {"ok": True, "channel": {"properties": {}}}
    client.conversations_canvases_create.side_effect = RuntimeError("canvas_creation_failed")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)

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
    client.conversations_info.return_value = {"ok": True, "channel": {"properties": {}}}
    client.conversations_canvases_create.return_value = {"ok": True}
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)

    result = fresh_board.publish(client, USER_TOKEN)

    assert result is None
    assert fresh_board.canvas_id is None


# --- compose path (unchanged: index + audit + names + situation) ------------


def test_publish_renders_current_index_and_audit_state(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
) -> None:
    """publish composes from the live offer index + audit trail singletons."""
    offer = make_offer(offerer="U_LIVE", resource_type="defibrillator")
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    mocker.patch("coordinator.canvas.resolve_display_names", return_value={})
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "defibrillator" in markdown
    # No names resolved -> bare id rendered (degraded but coherent).
    assert "U_LIVE" in markdown


def test_publish_resolves_names_and_threads_them_into_the_board(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
) -> None:
    """publish fetches display names for every actor/offerer id and renders them."""
    offer = make_offer(offerer="U_LIVE", resource_type="defibrillator")
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    resolve = mocker.patch(
        "coordinator.canvas.resolve_display_names", return_value={"U_LIVE": "Liv Rivera"}
    )
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    # The publish path (impure boundary) does the lookup with the user token.
    resolve.assert_called_once()
    call = resolve.call_args
    assert call.args[0] is client
    assert call.args[1] == USER_TOKEN
    assert "U_LIVE" in call.args[2]  # the id set to resolve
    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "Liv Rivera" in markdown


def test_publish_collects_actor_and_offerer_ids_for_resolution(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
    make_event: Callable[..., AuditEvent],
) -> None:
    """The id set spans offerers, audit actors, and offerer:<id> targets."""
    offer = make_offer(offerer="U_OFFERER")
    actor_event = make_event(actor_id="U_ACTOR", action="connect", target="offer:x")
    offerer_target_event = make_event(
        actor_id="U_ACTOR2", action="connect", target="offerer:U_TARGET"
    )
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch(
        "coordinator.canvas.audit_trail.list_events",
        return_value=[actor_event, offerer_target_event],
    )
    resolve = mocker.patch("coordinator.canvas.resolve_display_names", return_value={})
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    id_set = resolve.call_args.args[2]
    assert {"U_OFFERER", "U_ACTOR", "U_ACTOR2", "U_TARGET"} <= id_set


def test_publish_swallows_name_resolution_failure(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
) -> None:
    """A name-lookup failure never breaks the board update — best-effort guardrail.

    ``resolve_display_names`` is itself best-effort, but the publish path must not
    crash even if it raised unexpectedly: the board still renders with bare ids.
    """
    offer = make_offer(offerer="U_LIVE", resource_type="defibrillator")
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    mocker.patch("coordinator.canvas.resolve_display_names", side_effect=RuntimeError("names_boom"))
    client = _client(mocker, canvas_id="F_BOARD")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_BOARD"
    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "defibrillator" in markdown
    assert "U_LIVE" in markdown


# --- Situation section wiring (task 020, unchanged) -------------------------


def _situation_snapshot(*, road_available: bool = True):
    """A SituationSnapshot for the publish-path tests (built from real types)."""
    from datetime import UTC, datetime

    from coordinator.situation import SituationFeed, SituationSnapshot
    from mocks.server import RoadClosure

    fetched_at = datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
    if road_available:
        road = SituationFeed(
            feed="road_closures",
            available=True,
            fetched_at=fetched_at,
            records=(
                RoadClosure(
                    road="Minilya-Exmouth Road",
                    segment="Yannarie River crossing",
                    status="CLOSED",
                    reason="Floodwater over road.",
                    detour="No detour available.",
                    updated_at=fetched_at,
                ),
            ),
        )
    else:
        road = SituationFeed(feed="road_closures", available=False, detail="down")
    return SituationSnapshot(
        road_closures=road,
        evac_centres=SituationFeed(feed="evac_centres", available=False, detail="down"),
        official_advice=SituationFeed(feed="official_advice", available=False, detail="down"),
    )


def test_publish_reads_situation_and_threads_it_into_the_board(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """publish reads the official situation and renders it into the board markdown."""
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    mocker.patch("coordinator.canvas.resolve_display_names", return_value={})
    read = mocker.patch("coordinator.canvas.read_situation", return_value=_situation_snapshot())
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    read.assert_called_once()
    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "## Situation" in markdown
    assert "Minilya-Exmouth Road" in markdown


def test_publish_renders_degraded_feed_line_when_a_source_is_down(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A down feed surfaces as an explicit unavailable line on the published board."""
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    mocker.patch("coordinator.canvas.resolve_display_names", return_value={})
    mocker.patch(
        "coordinator.canvas.read_situation",
        return_value=_situation_snapshot(road_available=False),
    )
    client = _client(mocker, canvas_id="F_BOARD")

    fresh_board.publish(client, USER_TOKEN)

    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "road_closures" in markdown
    assert "unavailable" in markdown.lower()


def test_publish_swallows_situation_read_failure_and_omits_the_section(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
    make_offer: Callable[..., Offer],
) -> None:
    """A situation-read failure degrades to no Situation section — board still updates."""
    offer = make_offer(offerer="U_LIVE", resource_type="defibrillator")
    mocker.patch("coordinator.canvas.offer_index.all_offers", return_value=[offer])
    mocker.patch("coordinator.canvas.audit_trail.list_events", return_value=[])
    mocker.patch("coordinator.canvas.resolve_display_names", return_value={})
    mocker.patch("coordinator.canvas.read_situation", side_effect=RuntimeError("feeds_boom"))
    client = _client(mocker, canvas_id="F_BOARD")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_BOARD"
    markdown = client.conversations_canvases_create.call_args.kwargs["document_content"]["markdown"]
    assert "defibrillator" in markdown  # the board still composed
    assert "## Situation" not in markdown  # but degraded to no situation section


def test_update_board_helper_delegates_to_singleton_publish(
    mocker: MockerFixture,
) -> None:
    """The handler-facing helper refreshes the board via the singleton's publish."""
    client = mocker.Mock()
    publish = mocker.patch("coordinator.canvas.coordinator_board.publish", return_value="F_BOARD")

    update_board(client, USER_TOKEN)

    # update_board threads team_id (None when omitted) through to publish; the team
    # id and url are still accepted for caller signature stability (unused by the
    # channel-canvas create, which needs only the channel id).
    publish.assert_called_once_with(client, USER_TOKEN, None, None)


def test_update_board_helper_forwards_team_id(
    mocker: MockerFixture,
) -> None:
    """A team id from the Bolt context is still threaded through (signature stable)."""
    client = mocker.Mock()
    publish = mocker.patch("coordinator.canvas.coordinator_board.publish", return_value="F_BOARD")

    update_board(client, USER_TOKEN, "T_TEAM")

    publish.assert_called_once_with(client, USER_TOKEN, "T_TEAM", None)


def test_update_board_helper_swallows_publish_failure(
    mocker: MockerFixture,
) -> None:
    """update_board never raises even if the underlying publish path errors out."""
    client = mocker.Mock()
    mocker.patch("coordinator.canvas.coordinator_board.publish", return_value=None)

    # Must not raise.
    assert update_board(client, USER_TOKEN) is None


# --- Find-or-create: persisted-id reattach (the cross-process bridge) -------


def test_create_persists_canvas_id_to_shared_store(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The script process creates + persists, so the server can reattach."""
    client = _client(mocker, canvas_id="F_PERSISTED")
    save = mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)

    fresh_board.publish(client, USER_TOKEN)

    save.assert_called_once_with("F_PERSISTED")


def test_first_publish_loads_persisted_id_and_edits_not_creates(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A second process reads the persisted id and EDITS — no duplicate, no discovery."""
    client = _client(mocker, canvas_id="F_SHOULD_NOT_CREATE")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value="F_FROM_SCRIPT")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_FROM_SCRIPT"
    client.conversations_canvases_create.assert_not_called()
    # The persisted id short-circuits before the conversations.info discovery.
    client.conversations_info.assert_not_called()
    client.canvases_edit.assert_called_once()
    assert client.canvases_edit.call_args.kwargs["canvas_id"] == "F_FROM_SCRIPT"


def test_persisted_id_loaded_only_once_not_on_every_publish(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The store is read only when the in-process id is unknown, not on every edit."""
    client = _client(mocker, canvas_id="F_BOARD")
    load = mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value="F_SHARED")

    fresh_board.publish(client, USER_TOKEN)  # loads -> edits
    fresh_board.publish(client, USER_TOKEN)  # id now in process -> edits, no reload

    assert load.call_count == 1
    assert client.canvases_edit.call_count == 2


# --- Find-or-create: conversations.info discovery of an existing channel canvas ---


def test_discovers_existing_channel_canvas_via_conversations_info(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """No persisted id, but the channel already has a canvas -> reattach + edit it."""
    client = _client(mocker, canvas_id="F_SHOULD_NOT_CREATE")
    client.conversations_info.return_value = {
        "ok": True,
        "channel": {"properties": {"canvas": {"file_id": "F_EXISTING", "is_empty": False}}},
    }
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    save = mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_EXISTING"
    client.conversations_info.assert_called_once_with(channel=CRISIS_CHANNEL, token=USER_TOKEN)
    client.conversations_canvases_create.assert_not_called()
    client.canvases_edit.assert_called_once()
    assert client.canvases_edit.call_args.kwargs["canvas_id"] == "F_EXISTING"
    # The discovered id is persisted so the cross-process bridge reattaches to it.
    save.assert_called_once_with("F_EXISTING")


def test_no_existing_channel_canvas_falls_through_to_create(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """An empty properties.canvas (no channel canvas yet) -> create one."""
    client = _client(mocker, canvas_id="F_FRESH")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_FRESH"
    client.conversations_info.assert_called_once()
    client.conversations_canvases_create.assert_called_once()


def test_conversations_info_failure_falls_through_to_create(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A conversations.info failure degrades to create — discovery is best-effort."""
    client = _client(mocker, canvas_id="F_FRESH")
    client.conversations_info.side_effect = RuntimeError("info_down")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_FRESH"
    client.conversations_canvases_create.assert_called_once()


def test_create_race_recovers_via_discovery(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A channel_canvas_already_exists on create recovers by discovering the canvas.

    discovery first reports no canvas (so we attempt create), then create loses the
    race and reports the channel canvas already exists; we re-discover it rather
    than crashing the board.
    """
    client = _client(mocker, canvas_id="F_RACE")
    client.conversations_info.side_effect = [
        {"ok": True, "channel": {"properties": {}}},  # first look: none yet
        {  # after the race: the canvas the other process created
            "ok": True,
            "channel": {"properties": {"canvas": {"file_id": "F_WON_RACE"}}},
        },
    ]
    client.conversations_canvases_create.side_effect = _slack_api_error(
        "channel_canvas_already_exists"
    )
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    save = mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_WON_RACE"
    client.canvases_edit.assert_called_once()
    assert client.canvases_edit.call_args.kwargs["canvas_id"] == "F_WON_RACE"
    save.assert_called_once_with("F_WON_RACE")


def test_recreate_still_creates_even_with_persisted_id(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """recreate forces a fresh channel canvas regardless of a persisted id (clean demo)."""
    client = _client(mocker, canvas_id="F_FRESH")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value="F_OLD")
    save = mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")

    new_id = fresh_board.recreate(client, USER_TOKEN)

    assert new_id == "F_FRESH"
    client.conversations_canvases_create.assert_called_once()
    client.canvases_edit.assert_not_called()
    save.assert_called_once_with("F_FRESH")
    # the persisted prior canvas is deleted before minting fresh
    client.canvases_delete.assert_called_once_with(canvas_id="F_OLD", token=USER_TOKEN)


# --- Announce-on-create discoverability (kept minimal, task 025) ------------


def test_create_announces_board_link_once(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """Creating a canvas announces its link once to the coordinator channel."""
    client = _client(mocker, canvas_id="F_NEW")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    announce = mocker.patch("coordinator.canvas.announce_board")

    fresh_board.publish(client, USER_TOKEN, team_id="T_TEAM")

    announce.assert_called_once_with(
        client, canvas_id="F_NEW", team_id="T_TEAM", team_url=None, user_token=USER_TOKEN
    )


def test_edit_does_not_announce(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """A board edit (not a create) never re-announces — idempotent discoverability."""
    client = _client(mocker, canvas_id="F_BOARD")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    announce = mocker.patch("coordinator.canvas.announce_board")
    fresh_board.publish(client, USER_TOKEN)  # create -> announces

    announce.reset_mock()
    fresh_board.publish(client, USER_TOKEN)  # edit -> must not announce

    announce.assert_not_called()


def test_reattached_id_does_not_announce(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """Reattaching to a persisted canvas (edit path) does not announce — only create does."""
    client = _client(mocker, canvas_id="F_X")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value="F_FROM_SCRIPT")
    announce = mocker.patch("coordinator.canvas.announce_board")

    fresh_board.publish(client, USER_TOKEN)

    announce.assert_not_called()


def test_discovered_canvas_does_not_announce(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """Reattaching to a discovered channel canvas (edit path) does not announce."""
    client = _client(mocker, canvas_id="F_X")
    client.conversations_info.return_value = {
        "ok": True,
        "channel": {"properties": {"canvas": {"file_id": "F_EXISTING"}}},
    }
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    announce = mocker.patch("coordinator.canvas.announce_board")

    fresh_board.publish(client, USER_TOKEN)

    announce.assert_not_called()


def test_announce_failure_does_not_break_publish(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """An announce error never breaks the create — best-effort, returns the id."""
    client = _client(mocker, canvas_id="F_NEW")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    mocker.patch("coordinator.canvas.announce_board", side_effect=RuntimeError("boom"))

    canvas_id = fresh_board.publish(client, USER_TOKEN)

    assert canvas_id == "F_NEW"


# --- The bookmark is obsolete: no longer touched from the create path (task 025) ---


def test_create_does_not_upsert_bookmark(
    fresh_board: CoordinatorBoard,
    mocker: MockerFixture,
) -> None:
    """The channel-canvas tab supersedes the bookmark — create never upserts one."""
    client = _client(mocker, canvas_id="F_NEW")
    mocker.patch("coordinator.canvas.canvas_store.load_canvas_id", return_value=None)
    mocker.patch("coordinator.canvas.canvas_store.save_canvas_id")
    upsert = mocker.patch("coordinator.bookmark.upsert_board_bookmark")

    fresh_board.publish(client, USER_TOKEN, team_id="T_TEAM")

    upsert.assert_not_called()
    client.bookmarks_add.assert_not_called()
    client.bookmarks_edit.assert_not_called()
