"""Unit tests for listeners.actions.crisis_buttons — the confirmation handlers.

The Slack client, the process-local offer index, and the audit trail are all
patched per test so a click can be driven and its side effects asserted without a
live App. The contracts pinned here are the bounded-autonomy guardrails:

* The requester is always the clicker (``body["user"]["id"]``), never carried in
  the payload — the agent can't act on a match on someone's behalf.
* Connect opens a group DM (requester + offerer), posts a sourced intro, marks the
  index offer MATCHED, and swaps in a Mark-resolved button.
* Resolve marks the index offer RESOLVED (so it stops matching) and confirms.
* Not relevant mutes the card and records the signal — no connection, no index
  change.
* Every failure path posts a visible message (degraded guardrail) — never silence.
* Every action appends one audit event.
"""

from collections.abc import Callable

from pytest_mock import MockerFixture

from entities import Offer, Status
from listeners.actions import crisis_buttons
from matching.audit import AuditTrail
from matching.index import OfferIndex
from recall.dismissals import DismissalStore, match_identity
from recall.payload import ConnectPayload


def _patch_singletons(mocker: MockerFixture) -> tuple[OfferIndex, AuditTrail]:
    """Swap the module-level index + audit trail for fresh, isolated instances.

    Also stubs out ``update_board`` (the task-017 coordinator-board hook): these
    tests assert the button state machine, not the Canvas, and the board update is
    a best-effort, isolated side effect with its own tests in
    ``tests/unit/coordinator``. Stubbing it keeps these tests Slack-free and pins
    that a board failure can never be in the button's path here.
    """
    index = OfferIndex()
    trail = AuditTrail()
    mocker.patch.object(crisis_buttons, "offer_index", index)
    mocker.patch.object(crisis_buttons, "audit_trail", trail)
    mocker.patch.object(crisis_buttons, "update_board")
    return index, trail


def _context(mocker: MockerFixture, *, user_token: str | None = "xoxp-user") -> object:
    """A BoltContext-like stub carrying the user token the board hook reads."""
    return mocker.Mock(user_token=user_token)


def _patch_dismissals(mocker: MockerFixture) -> DismissalStore:
    """Swap the module-level dismissal store for a fresh, isolated instance."""
    store = DismissalStore()
    mocker.patch.object(crisis_buttons, "dismissal_store", store)
    return store


def _client(mocker: MockerFixture) -> object:
    """A WebClient mock whose conversations_open returns a usable DM channel."""
    client = mocker.Mock()
    client.conversations_open.return_value = {"channel": {"id": "D_GROUP"}}
    return client


# ----- crisis_connect -----


def test_connect_opens_group_dm_with_requester_and_offerer(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """Connect opens a conversation including BOTH the clicker (requester) and offerer."""
    _patch_singletons(mocker)
    client = _client(mocker)
    body = make_action_body(
        clicker="U_REQUESTER",
        payload=ConnectPayload(offerer_id="U_OFFERER", snippet="2kW generator"),
    )

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    users = client.conversations_open.call_args.kwargs["users"]
    assert "U_REQUESTER" in users  # the clicker, derived from body["user"]["id"]
    assert "U_OFFERER" in users  # the offerer, from the payload


def test_connect_acks_immediately(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """The handler ack()s before doing any work."""
    _patch_singletons(mocker)
    ack = mocker.Mock()

    crisis_buttons.handle_crisis_connect(
        ack=ack,
        body=make_action_body(),
        client=_client(mocker),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    ack.assert_called_once()


def test_connect_posts_sourced_intro(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """The intro names both parties and cites the offer — sourced, no safety claim."""
    _patch_singletons(mocker)
    client = _client(mocker)
    body = make_action_body(
        clicker="U_REQUESTER",
        payload=ConnectPayload(offerer_id="U_OFFERER", snippet="2kW generator"),
    )

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    intro = client.chat_postMessage.call_args.kwargs["text"]
    assert "<@U_REQUESTER>" in intro
    assert "<@U_OFFERER>" in intro
    assert "2kW generator" in intro
    assert "verify" in intro.lower()  # never asserts safety; tells them to verify


def test_connect_marks_index_offer_matched(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
    make_offer: Callable[..., Offer],
) -> None:
    """Connect on an index hit transitions the offer to MATCHED."""
    index, _ = _patch_singletons(mocker)
    offer = make_offer()
    index.add(offer)
    body = make_action_body(
        payload=ConnectPayload(offerer_id="U_OFFERER", offer_id=str(offer.id), snippet="x")
    )

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=body,
        client=_client(mocker),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    assert index.lookup(offer.id).status is Status.MATCHED


def test_connect_swaps_in_mark_resolved_button(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """After a connect, the card's action row becomes a single Mark-resolved button."""
    _patch_singletons(mocker)
    client = _client(mocker)

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    updated_blocks = client.chat_update.call_args.kwargs["blocks"]
    action_rows = [b for b in updated_blocks if b["type"] == "actions"]
    assert len(action_rows) == 1
    assert [e["action_id"] for e in action_rows[0]["elements"]] == ["crisis_resolve"]


def test_connect_falls_back_to_offerer_dm_when_group_dm_fails(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """If the group DM can't open, fall back to a DM with the offerer — never silent."""
    _patch_singletons(mocker)
    client = mocker.Mock()
    # First conversations_open (group) raises; second (offerer-only) succeeds.
    client.conversations_open.side_effect = [
        Exception("missing_scope: mpim:write"),
        {"channel": {"id": "D_OFFERER"}},
    ]

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    assert client.conversations_open.call_count == 2
    # The fallback opened a DM with just the offerer and posted the intro there.
    assert client.conversations_open.call_args.kwargs["users"] == "U_OFFERER"
    assert client.chat_postMessage.call_args.kwargs["channel"] == "D_OFFERER"


def test_connect_posts_visible_message_when_both_dm_attempts_fail(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """If even the offerer DM fails, the clicker gets an explicit message (degraded)."""
    _patch_singletons(mocker)
    client = mocker.Mock()
    client.conversations_open.side_effect = Exception("hard down")

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(clicker="U_REQUESTER"),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    client.chat_postEphemeral.assert_called_once()
    text = client.chat_postEphemeral.call_args.kwargs["text"].lower()
    assert "couldn't open" in text
    assert "nothing was sent" in text
    client.chat_update.assert_not_called()  # no card flip on a failed connect


def test_connect_records_audit_event(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A connect appends one audit event attributing the action to the clicker."""
    _, trail = _patch_singletons(mocker)

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(clicker="U_REQUESTER"),
        client=_client(mocker),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    events = trail.list_events()
    assert len(events) == 1
    assert events[0].actor_id == "U_REQUESTER"
    assert events[0].action == "connect"


# ----- crisis_resolve -----


def test_resolve_marks_index_offer_resolved(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
    make_offer: Callable[..., Offer],
) -> None:
    """Resolve transitions the index offer to RESOLVED (so it stops matching)."""
    index, _ = _patch_singletons(mocker)
    offer = make_offer()
    index.add(offer)
    body = make_action_body(
        action_id="crisis_resolve",
        payload=ConnectPayload(offerer_id="U_OFFERER", offer_id=str(offer.id), snippet="x"),
    )

    crisis_buttons.handle_crisis_resolve(
        ack=mocker.Mock(),
        body=body,
        client=mocker.Mock(),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    assert index.lookup(offer.id).status is Status.RESOLVED


def test_resolve_mutes_card_and_posts_threaded_confirmation(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """Resolve flips the card to a Resolved state and posts a threaded ack."""
    _patch_singletons(mocker)
    client = mocker.Mock()
    body = make_action_body(action_id="crisis_resolve", clicker="U_REQUESTER")

    crisis_buttons.handle_crisis_resolve(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    updated_blocks = client.chat_update.call_args.kwargs["blocks"]
    muted = [b for b in updated_blocks if b["type"] == "context"]
    assert any("Resolved" in e["text"] for b in muted for e in b["elements"])
    confirm = client.chat_postMessage.call_args.kwargs
    assert confirm["thread_ts"] == "1742550600.000300"  # threaded under the card
    assert "<@U_REQUESTER>" in confirm["text"]


def test_resolve_records_audit_event(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A resolve appends one audit event."""
    _, trail = _patch_singletons(mocker)

    crisis_buttons.handle_crisis_resolve(
        ack=mocker.Mock(),
        body=make_action_body(action_id="crisis_resolve", clicker="U_REQUESTER"),
        client=mocker.Mock(),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    events = trail.list_events()
    assert len(events) == 1
    assert events[0].action == "resolve"


# ----- crisis_not_relevant -----


def test_not_relevant_mutes_card_to_dismissed(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """Not relevant collapses the button row to a muted Dismissed note — never silent."""
    _patch_singletons(mocker)
    client = mocker.Mock()
    body = make_action_body(action_id="crisis_not_relevant")

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    updated_blocks = client.chat_update.call_args.kwargs["blocks"]
    muted = [b for b in updated_blocks if b["type"] == "context"]
    assert any("Dismissed" in e["text"] for b in muted for e in b["elements"])


def test_not_relevant_makes_no_connection_and_no_index_change(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
    make_offer: Callable[..., Offer],
) -> None:
    """Dismissing opens no conversation and leaves the offer OPEN (no auto-action)."""
    index, _ = _patch_singletons(mocker)
    offer = make_offer()
    index.add(offer)
    client = mocker.Mock()
    body = make_action_body(
        action_id="crisis_not_relevant",
        payload=ConnectPayload(offerer_id="U_OFFERER", offer_id=str(offer.id), snippet="x"),
    )

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    client.conversations_open.assert_not_called()
    assert index.lookup(offer.id).status is Status.OPEN


def test_not_relevant_records_audit_event(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A dismissal appends one audit event with the not_relevant action."""
    _, trail = _patch_singletons(mocker)
    _patch_dismissals(mocker)

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(),
        body=make_action_body(action_id="crisis_not_relevant"),
        client=mocker.Mock(),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    assert [e.action for e in trail.list_events()] == ["not_relevant"]


def test_not_relevant_records_dismissal_for_the_clicker(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """Dismissing writes the (clicker, match identity) pair into the dismissal store (015)."""
    _patch_singletons(mocker)
    store = _patch_dismissals(mocker)
    payload = ConnectPayload(
        offerer_id="U_OFFERER", offer_id="uuid-123", permalink="https://x/p1", snippet="x"
    )
    body = make_action_body(action_id="crisis_not_relevant", clicker="U_REQUESTER", payload=payload)

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(),
        body=body,
        client=mocker.Mock(),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    # Identity follows offer_id -> permalink -> text; this payload has an offer id.
    identity = match_identity(offer_id="uuid-123", permalink="https://x/p1", text="x")
    assert store.is_dismissed("U_REQUESTER", identity) is True


def test_not_relevant_dismissal_is_keyed_to_the_clicker_only(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """The dismissal binds to the clicker — a different user is not marked dismissed (015)."""
    _patch_singletons(mocker)
    store = _patch_dismissals(mocker)
    payload = ConnectPayload(offerer_id="U_OFFERER", permalink="https://x/p1", snippet="x")
    body = make_action_body(action_id="crisis_not_relevant", clicker="U_A", payload=payload)

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(),
        body=body,
        client=mocker.Mock(),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    identity = match_identity(permalink="https://x/p1")
    assert store.is_dismissed("U_A", identity) is True
    assert store.is_dismissed("U_B", identity) is False


# ----- malformed payload (degraded) -----


def test_malformed_payload_posts_visible_message_and_does_nothing(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A button with a non-JSON value posts an explicit failure and changes nothing."""
    _, trail = _patch_singletons(mocker)
    client = mocker.Mock()
    body = make_action_body(value="not json {")

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    client.chat_postEphemeral.assert_called_once()
    assert "didn't do anything" in client.chat_postEphemeral.call_args.kwargs["text"].lower()
    client.conversations_open.assert_not_called()
    assert trail.list_events() == []  # nothing audited — nothing happened


def test_rts_only_match_connect_does_not_touch_index(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """An RTS-only match (no offer id) connects fine and makes no index transition."""
    index, _ = _patch_singletons(mocker)
    spy = mocker.spy(index, "mark_matched")
    body = make_action_body(
        payload=ConnectPayload(offerer_id="U_SAM", permalink="https://x/p1", snippet="lend a gen")
    )

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=body,
        client=_client(mocker),
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    spy.assert_not_called()  # no offer id -> no index op


def test_connect_double_click_is_idempotent(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
    make_offer: Callable[..., Offer],
) -> None:
    """A second Connect click on an already-matched offer sends no new DM."""
    index, _ = _patch_singletons(mocker)
    offer = make_offer()
    index.add(offer)
    body = make_action_body(
        payload=ConnectPayload(offerer_id="U_OFFERER", offer_id=str(offer.id), snippet="x")
    )
    client = _client(mocker)

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )
    dm_posts_after_first = client.chat_postMessage.call_count

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(), body=body, client=client, context=_context(mocker), logger=mocker.Mock()
    )

    assert client.chat_postMessage.call_count == dm_posts_after_first


# ----- coordinator-board hook (task 017) -----


def test_connect_refreshes_board_with_resolved_user_token(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A successful connect refreshes the coordinator board with the user token."""
    _patch_singletons(mocker)  # patches update_board to a Mock
    client = _client(mocker)

    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(),
        client=client,
        context=_context(mocker, user_token="xoxp-coordinator"),
        logger=mocker.Mock(),
    )

    crisis_buttons.update_board.assert_called_once_with(client, "xoxp-coordinator")


def test_resolve_refreshes_board(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A resolve refreshes the coordinator board."""
    _patch_singletons(mocker)
    client = mocker.Mock()

    crisis_buttons.handle_crisis_resolve(
        ack=mocker.Mock(),
        body=make_action_body(action_id="crisis_resolve"),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    crisis_buttons.update_board.assert_called_once()


def test_not_relevant_refreshes_board(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """A dismissal refreshes the coordinator board (the activity log records it)."""
    _patch_singletons(mocker)
    _patch_dismissals(mocker)
    client = mocker.Mock()

    crisis_buttons.handle_crisis_not_relevant(
        ack=mocker.Mock(),
        body=make_action_body(action_id="crisis_not_relevant"),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    crisis_buttons.update_board.assert_called_once()


def test_board_hook_is_isolated_so_a_failure_never_breaks_connect(
    mocker: MockerFixture,
    make_action_body: Callable[..., dict],
) -> None:
    """update_board is the board boundary — it never raises, so connect always completes.

    Here the real (non-stubbed) update_board is exercised with a client whose
    canvas calls fail; the connect's DM + card flip must still stand. This pins
    that the board hook is additive and isolated (task-017 constraint).
    """
    index = OfferIndex()
    trail = AuditTrail()
    mocker.patch.object(crisis_buttons, "offer_index", index)
    mocker.patch.object(crisis_buttons, "audit_trail", trail)
    # update_board NOT stubbed — exercise the real best-effort path with a failing
    # canvas, against a fresh board so no prior test's stored id leaks in.
    from coordinator.canvas import CoordinatorBoard

    mocker.patch("coordinator.canvas.coordinator_board", CoordinatorBoard())
    client = _client(mocker)
    client.canvases_create.side_effect = RuntimeError("canvas down")

    # Must not raise; the connect's intro is still posted.
    crisis_buttons.handle_crisis_connect(
        ack=mocker.Mock(),
        body=make_action_body(),
        client=client,
        context=_context(mocker),
        logger=mocker.Mock(),
    )

    client.chat_postMessage.assert_called()  # the intro went out despite the board failure
