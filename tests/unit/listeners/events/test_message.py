"""Unit tests for the channel-gating table in listeners.events.message.handle_message.

Task 006 adds passive listening in ONE designated channel (``CRISIS_CHANNEL``).
These tests pin the routing decision without a live Slack or LLM: ``route_message``
and ``compose_reply`` are patched, so we assert *which* path each message takes by
what gets called, never by talking to Slack or the model.

The gating contract under test (top-level channel messages):

* **Designated channel, offer** -> ``route_message`` runs (indexes + acks via its
  own ``say``) and returns ``None``; ``compose_reply`` is NOT called (the ack is the
  only reply).
* **Designated channel, need** -> ``route_message`` returns a ``NeedRecall`` and
  ``compose_reply`` composes exactly one threaded reply.
* **Designated channel, chatter (NotACrisisMessage)** -> ``route_message`` returns
  ``None``; ``compose_reply`` is NOT called -> complete silence. This is the
  critical guardrail: channel chatter never reaches the LLM reply.
* **Other channel, top-level** -> skipped entirely; ``route_message`` is never even
  called (no parse cost outside the designated channel).
* **Thread reply in the designated channel** -> unchanged (handled only if the bot
  is already engaged in that thread).
* **CRISIS_CHANNEL empty/unset** -> all top-level channel messages skipped (the
  pre-006 behavior).

DMs keep their own unconditional reply path and are covered by the DM-unchanged test.
"""

import pytest
from pytest_mock import MockerFixture

from listeners.events import message

CRISIS_CHANNEL = "C_CRISIS"
EVENT_TS = "1742550600.000200"


@pytest.fixture
def patched_flow(mocker: MockerFixture) -> dict[str, object]:
    """Patch the routing/compose seams and the conversation store; return the spies.

    Keeps every test on the in-process gating decision — no Slack, no LLM, no recall
    I/O. ``route_message`` and ``compose_reply`` are the two seams the gate drives.
    """
    route = mocker.patch.object(message, "route_message")
    compose = mocker.patch.object(message, "compose_reply")
    mocker.patch.object(message, "resolve_user_token", return_value="xoxp-x")
    store = mocker.patch.object(message, "conversation_store")
    store.get_history.return_value = None
    return {"route": route, "compose": compose, "store": store}


def _channel_event(
    *, channel_type: str = "channel", thread_ts: str | None = None, text: str = "some text"
) -> dict:
    """A top-level channel message event (no subtype, not a bot, human author)."""
    event: dict[str, object] = {
        "channel_type": channel_type,
        "text": text,
        "ts": EVENT_TS,
        "user": "U_REQ",
    }
    if thread_ts is not None:
        event["thread_ts"] = thread_ts
    return event


def _context(mocker: MockerFixture, channel_id: str) -> object:
    """A minimal BoltContext stand-in carrying the ids the handler reads."""
    context = mocker.Mock()
    context.channel_id = channel_id
    context.user_id = "U_REQ"
    context.user_token = None
    context.team_id = "T1"
    context.bot_user_id = "B1"
    return context


def _invoke(mocker: MockerFixture, *, channel_id: str, event: dict) -> dict[str, object]:
    """Drive handle_message with mocked Bolt args; return the Slack-facing mocks."""
    client = mocker.Mock()
    logger = mocker.Mock()
    say = mocker.Mock()
    say_stream = mocker.Mock()
    set_status = mocker.Mock()
    message.handle_message(
        client=client,
        context=_context(mocker, channel_id),
        event=event,
        logger=logger,
        say=say,
        say_stream=say_stream,
        set_status=set_status,
    )
    return {"client": client, "logger": logger, "say": say, "set_status": set_status}


def test_designated_channel_offer_acked_no_compose(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Top-level offer in the designated channel: route_message runs, compose does not.

    route_message indexes + acks the offer (its own say) and returns None, so the
    handler must NOT compose a need reply — the ack is the single reply.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["route"].return_value = None  # offer acked + None, or chatter

    _invoke(mocker, channel_id=CRISIS_CHANNEL, event=_channel_event())

    patched_flow["route"].assert_called_once()
    patched_flow["compose"].assert_not_called()


def test_designated_channel_need_gets_one_reply(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Top-level need in the designated channel: composed once, threaded under the post."""
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    recall = mocker.Mock()
    patched_flow["route"].return_value = recall

    _invoke(mocker, channel_id=CRISIS_CHANNEL, event=_channel_event())

    patched_flow["route"].assert_called_once()
    patched_flow["compose"].assert_called_once()
    # The reply threads under the resident's original message and names them.
    compose_kwargs = patched_flow["compose"].call_args.kwargs
    assert compose_kwargs["recall"] is recall
    assert compose_kwargs["mention_requester"] is True
    deps = (
        compose_kwargs["deps"]
        if "deps" in compose_kwargs
        else patched_flow["compose"].call_args.args[1]
    )
    assert deps.thread_ts == EVENT_TS


def test_designated_channel_chatter_is_silent(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chatter (NotACrisisMessage) in the designated channel: parsed but NO reply at all.

    route_message returns None for a non-crisis message; the handler must compose
    nothing and post nothing — the critical "chatter never triggers bot noise" rule.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["route"].return_value = None

    slack = _invoke(mocker, channel_id=CRISIS_CHANNEL, event=_channel_event())

    patched_flow["route"].assert_called_once()
    patched_flow["compose"].assert_not_called()
    slack["say"].assert_not_called()  # no reply, no ack, no reaction from the handler


def test_designated_channel_mention_prefixed_post_deferred_to_app_mention(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mention-prefixed top-level post in the designated channel is NOT passively routed.

    Slack delivers BOTH an app_mention and a message.channels event for one user
    message that @mentions the bot. The app_mention handler owns those; the passive
    path must skip them so the message is not acked / replied / indexed twice. With
    no mention guard this is exactly the dual-routing double-ack defect (Break path 7).
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    # bot_user_id on the context is "B1"; mentioning it must defer to app_mention.
    event = _channel_event(text="<@B1> I can offer water")

    slack = _invoke(mocker, channel_id=CRISIS_CHANNEL, event=event)

    patched_flow["route"].assert_not_called()  # app_mention owns the mention-prefixed post
    patched_flow["compose"].assert_not_called()
    slack["say"].assert_not_called()  # no double ack / double reply from the passive path
    slack["set_status"].assert_not_called()


def test_other_channel_top_level_skipped_no_parse(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A top-level message in a non-designated channel is skipped before any parse.

    No route_message call -> no per-message LLM parse cost outside the one channel.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)

    slack = _invoke(mocker, channel_id="C_OTHER", event=_channel_event())

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()
    slack["say"].assert_not_called()
    slack["set_status"].assert_not_called()


def test_thread_reply_in_designated_channel_unchanged(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A thread reply in the designated channel is NOT passively routed.

    Thread replies stay on the existing "engaged thread only" path: with no prior
    history the handler bails before routing — passive listening is top-level only.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["store"].get_history.return_value = None  # bot not engaged in thread

    _invoke(
        mocker,
        channel_id=CRISIS_CHANNEL,
        event=_channel_event(thread_ts="1742550600.000100"),
    )

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()


def test_crisis_channel_unset_all_channel_messages_skipped(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With CRISIS_CHANNEL unset, every top-level channel message is skipped (pre-006)."""
    monkeypatch.delenv("CRISIS_CHANNEL", raising=False)

    slack = _invoke(mocker, channel_id=CRISIS_CHANNEL, event=_channel_event())

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()
    slack["say"].assert_not_called()


def test_dm_path_unchanged_composes_even_without_recall(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DMs keep their unconditional reply: compose runs even when route returns None.

    This contrasts the channel path (silent on None) with the DM path (always
    replies) — the gate must not leak its silence rule into DMs.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["route"].return_value = None

    _invoke(mocker, channel_id="D_DM", event=_channel_event(channel_type="im"))

    patched_flow["compose"].assert_called_once()
    compose_kwargs = patched_flow["compose"].call_args.kwargs
    assert compose_kwargs["mention_requester"] is False  # DM omits the mention


def test_agents_own_message_in_designated_channel_ignored(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent's OWN messages (user == bot_user_id) never route — no self-loop (task 031).

    The agent's acks/replies post as the bot and carry its own user id. The handler
    must skip them so an indexed offer's ack is never re-parsed/re-indexed/re-acked.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    # The agent's own post: authored by the bot's user id, with a bot_id set.
    event = _channel_event(text="Logged your offer")
    event["user"] = "B1"  # context.bot_user_id is "B1"
    event["bot_id"] = "B1"

    _invoke(mocker, channel_id=CRISIS_CHANNEL, event=event)

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()


def test_operator_api_post_in_designated_channel_routed(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator/integration API post (real user + a bot_id) is routed, not skipped (task 031).

    A seeded/operator offer posted via the app's WebClient arrives with a real
    ``user`` (the operator) AND a ``bot_id`` (the posting app). The old blanket
    ``bot_id`` skip dropped it before parsing; now only the agent's OWN posts
    (``user == bot_user_id``) are skipped, so this is parsed/indexed/acked.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["route"].return_value = None  # offer acked by route_message
    event = _channel_event(text="Offering: a 2kW petrol generator")
    event["user"] = "U_OPERATOR"  # a real operator, NOT the bot's user id ("B1")
    event["bot_id"] = "B_APP"  # posted via the app's WebClient

    _invoke(mocker, channel_id=CRISIS_CHANNEL, event=event)

    # Not skipped by the self-guard: the offer reaches route_message to be parsed +
    # indexed + acked (route returns None, so no need reply is composed).
    patched_flow["route"].assert_called_once()
    patched_flow["compose"].assert_not_called()
    # The offer text reaches route_message (passed positionally as the first arg).
    assert patched_flow["route"].call_args.args[0] == "Offering: a 2kW petrol generator"


def test_bot_user_id_none_falls_back_to_bot_id_skip(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive fallback (task 031): bot_user_id unknown -> skip any bot_id message.

    In socket mode ``context.bot_user_id`` is always set; if it is somehow ``None``
    we cannot identify our own posts by user id, so we fall back to the old
    ``bot_id`` skip rather than risk treating our own posts as user input.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    context = _context(mocker, CRISIS_CHANNEL)
    context.bot_user_id = None
    event = _channel_event(text="Offering: a generator")
    event["user"] = "U_OPERATOR"
    event["bot_id"] = "B_APP"

    client = mocker.Mock()
    logger = mocker.Mock()
    say = mocker.Mock()
    say_stream = mocker.Mock()
    set_status = mocker.Mock()
    message.handle_message(
        client=client,
        context=context,
        event=event,
        logger=logger,
        say=say,
        say_stream=say_stream,
        set_status=set_status,
    )

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()


def test_designated_channel_route_failure_stays_silent(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash during passive routing logs but posts NOTHING into the channel.

    The DM path posts a ':warning:' reply on failure (the user is waiting on an
    answer); the passive-channel path must not — an error reply on every failed parse
    would be exactly the bot noise the guardrail forbids. Failures are logged only.
    """
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    patched_flow["route"].side_effect = RuntimeError("boom")

    slack = _invoke(mocker, channel_id=CRISIS_CHANNEL, event=_channel_event())

    patched_flow["compose"].assert_not_called()
    slack["say"].assert_not_called()  # no warning posted into the channel
    slack["logger"].exception.assert_called_once()


def test_message_changed_subtype_in_designated_channel_ignored(
    mocker: MockerFixture, patched_flow: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A message_changed (edit) subtype in the channel never routes — existing guard."""
    monkeypatch.setenv("CRISIS_CHANNEL", CRISIS_CHANNEL)
    event = _channel_event()
    event["subtype"] = "message_changed"

    _invoke(mocker, channel_id=CRISIS_CHANNEL, event=event)

    patched_flow["route"].assert_not_called()
    patched_flow["compose"].assert_not_called()
