"""Unit tests for listeners.backfill — the startup offer-index backfill (task 026).

The sweep reads ``conversations.history`` and parses each message; both the
``WebClient`` and ``parse_message`` are mocked (pytest-mock) so no real Slack and no
real LLM are touched. We verify:

* only parsed **Offers** are indexed — Needs, chatter, bot posts, subtypes, and
  message-less events are skipped (mirrors ``handle_message`` guards);
* per-message parse failures and a history-fetch failure are caught and never raise
  (best-effort), returning a count;
* idempotence over a real ``OfferIndex`` (same history swept twice -> stable size);
* both gates of ``maybe_backfill_on_start`` (flag off, channel unset) -> no-op, and
  the open-gate path runs the sweep then publishes the board.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pytest_mock import MockerFixture

from entities import Need, Offer, Urgency, deterministic_id
from listeners import backfill
from matching.index import OfferIndex

OFFER_TS = datetime(2026, 3, 21, 9, 30, tzinfo=UTC)
NEED_TS = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)
CHANNEL = "C_CRISIS"
OPERATOR = "U_OPERATOR"
BOT_USER_ID = "U_AGENT"
B_APP = "B_APP"


def _offer(*, offerer: str = "U_OFFERER", source_ts: datetime = OFFER_TS) -> Offer:
    return Offer(
        id=deterministic_id(offerer, source_ts),
        offerer=offerer,
        resource_type="generator",
        location="Exmouth",
        availability="collect any time today",
        source_ts=source_ts,
    )


def _need() -> Need:
    return Need(
        id=deterministic_id("U_REQ", NEED_TS),
        requester="U_REQ",
        need_type="generator",
        location="Exmouth",
        urgency=Urgency.HIGH,
        household_size=4,
        source_ts=NEED_TS,
    )


def _msg(
    *,
    text: str = "I have a generator",
    user: str = "U_OFFERER",
    ts: str = "1700000000.000100",
    **extra: object,
) -> dict:
    """A minimal eligible conversations.history message; ``extra`` overrides/adds fields."""
    message: dict = {"text": text, "user": user, "ts": ts}
    message.update(extra)
    return message


def _history_client(mocker: MockerFixture, messages: list[dict]) -> object:
    """A mock WebClient whose conversations_history returns ``messages``."""
    client = mocker.Mock()
    client.conversations_history.return_value = {"messages": messages}
    return client


@pytest.fixture
def fresh_index(mocker: MockerFixture) -> OfferIndex:
    """Patch the module-level offer_index with a fresh, isolated instance."""
    index = OfferIndex()
    mocker.patch.object(backfill, "offer_index", index)
    return index


def _parser(results: dict[str, object]) -> Callable[[str, str, datetime], object]:
    """A parse_message stand-in keyed by message text; raises if a text isn't mapped."""

    def _parse(text: str, author: str, ts: datetime) -> object:
        if text not in results:
            raise AssertionError(f"unexpected parse text: {text!r}")
        outcome = results[text]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _parse


# --- AC1: only Offers indexed; needs/chatter/bot/subtype/empty skipped ---


def test_only_offers_are_indexed(mocker: MockerFixture, fresh_index: OfferIndex) -> None:
    """6 offers + 2 needs + 3 chatter + bot/subtype/empty -> exactly the 6 offers index."""
    offers = [_offer(offerer=f"U_OFF_{i}", source_ts=OFFER_TS) for i in range(6)]
    offer_msgs = [
        _msg(text=f"offer-{i}", user=f"U_OFF_{i}", ts=f"170000000{i}.000100") for i in range(6)
    ]
    need_msgs = [_msg(text=f"need-{i}", user=f"U_REQ_{i}") for i in range(2)]
    chatter_msgs = [_msg(text=f"chatter-{i}", user=f"U_CHAT_{i}") for i in range(3)]
    bot_msg = _msg(text="offer-from-bot", bot_id="B123")
    subtype_msg = _msg(text="edited offer", subtype="message_changed")
    no_text_msg = _msg(text="")
    no_user_msg = _msg(user="")
    messages = [
        *offer_msgs,
        *need_msgs,
        *chatter_msgs,
        bot_msg,
        subtype_msg,
        no_text_msg,
        no_user_msg,
    ]

    text_to_result: dict[str, object] = {f"offer-{i}": offers[i] for i in range(6)}
    text_to_result.update({f"need-{i}": _need() for i in range(2)})
    text_to_result.update({f"chatter-{i}": "not a crisis message" for i in range(3)})
    mocker.patch.object(backfill, "parse_message", side_effect=_parser(text_to_result))

    client = _history_client(mocker, messages)
    count = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token="xoxp-x")

    assert count == 6
    assert len(fresh_index.all_offers()) == 6
    indexed_ids = {offer.id for offer in fresh_index.all_offers()}
    assert indexed_ids == {offer.id for offer in offers}


def test_history_is_fetched_for_the_given_channel(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """conversations.history is called for the passed channel with the page limit."""
    mocker.patch.object(backfill, "parse_message", side_effect=_parser({}))
    client = _history_client(mocker, [])

    backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None, limit=42)

    client.conversations_history.assert_called_once_with(channel=CHANNEL, limit=42)


# --- 032 AC1/AC2/AC3: skip guard aligned with task 031 (skip own posts, not any bot) ---


def test_seeded_offer_with_bot_id_is_indexed(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """An operator/integration offer (real user + a bot_id) is indexed, not dropped.

    Mirrors the seed-demo payload shape: messages posted through the app's WebClient
    carry a real ``user`` AND a ``bot_id``. The old blanket ``bot_id`` skip dropped
    them; with ``bot_user_id`` set we skip only the agent's own posts, so this offer
    now reaches the index (AC1).
    """
    offer = _offer(offerer=OPERATOR)
    messages = [_msg(text="Offering: a generator", user=OPERATOR, bot_id=B_APP)]
    mocker.patch.object(
        backfill, "parse_message", side_effect=_parser({"Offering: a generator": offer})
    )
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(
        client, channel_id=CHANNEL, user_token=None, bot_user_id=BOT_USER_ID
    )

    assert count == 1
    assert fresh_index.lookup(offer.id) == offer


def test_agents_own_post_is_skipped_by_user_identity(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """The agent's own past post (user == bot_user_id) is skipped, never parsed (AC2)."""
    parse_spy = mocker.patch.object(backfill, "parse_message", side_effect=_parser({}))
    messages = [_msg(text="On it — I'll surface matches.", user=BOT_USER_ID, bot_id=B_APP)]
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(
        client, channel_id=CHANNEL, user_token=None, bot_user_id=BOT_USER_ID
    )

    assert count == 0
    assert fresh_index.all_offers() == []
    parse_spy.assert_not_called()


def test_bot_user_id_none_falls_back_to_bot_id_skip(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """When bot_user_id is unknown, the defensive bot_id skip applies (AC3).

    A bot post (carries a bot_id, real user) is dropped without parsing, exactly as
    the live handler does when it cannot identify itself by user id.
    """
    parse_spy = mocker.patch.object(backfill, "parse_message", side_effect=_parser({}))
    messages = [_msg(text="Offering: a generator", user=OPERATOR, bot_id=B_APP)]
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(
        client, channel_id=CHANNEL, user_token=None, bot_user_id=None
    )

    assert count == 0
    assert fresh_index.all_offers() == []
    parse_spy.assert_not_called()


def test_bot_user_id_none_still_indexes_a_plain_user_offer(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """bot_user_id None drops only bot_id posts; a plain user offer still indexes (AC3)."""
    offer = _offer(offerer=OPERATOR)
    messages = [_msg(text="Offering: a generator", user=OPERATOR)]
    mocker.patch.object(
        backfill, "parse_message", side_effect=_parser({"Offering: a generator": offer})
    )
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(
        client, channel_id=CHANNEL, user_token=None, bot_user_id=None
    )

    assert count == 1
    assert fresh_index.lookup(offer.id) == offer


def test_other_bot_offer_is_indexed_when_bot_user_id_known(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """With bot_user_id set, a DIFFERENT bot's offer (user != bot_user_id) is parsed.

    Aligns with 031's trade-off: only the agent's OWN posts are skipped by identity;
    other bot/integration posts are parsed (parse_message classifies them).
    """
    offer = _offer(offerer="U_OTHER_BOT")
    messages = [_msg(text="Offering: a generator", user="U_OTHER_BOT", bot_id="B_OTHER")]
    mocker.patch.object(
        backfill, "parse_message", side_effect=_parser({"Offering: a generator": offer})
    )
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(
        client, channel_id=CHANNEL, user_token=None, bot_user_id=BOT_USER_ID
    )

    assert count == 1
    assert fresh_index.lookup(offer.id) == offer


# --- AC2: best-effort — parse-raise skips one; history-fetch raise -> 0 ---


def test_per_message_parse_failure_skips_only_that_message(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """A parse that raises drops only its own message; the rest still index."""
    good = _offer(offerer="U_GOOD")
    messages = [
        _msg(text="boom", user="U_BAD"),
        _msg(text="good-offer", user="U_GOOD"),
    ]
    mocker.patch.object(
        backfill,
        "parse_message",
        side_effect=_parser({"boom": RuntimeError("parse exploded"), "good-offer": good}),
    )
    client = _history_client(mocker, messages)

    count = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None)

    assert count == 1
    assert fresh_index.lookup(good.id) == good


def test_history_fetch_failure_returns_zero_and_never_raises(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """A conversations.history exception is swallowed: returns 0, index untouched."""
    client = mocker.Mock()
    client.conversations_history.side_effect = RuntimeError("history down")
    parse_spy = mocker.patch.object(backfill, "parse_message")

    count = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None)

    assert count == 0
    assert fresh_index.all_offers() == []
    parse_spy.assert_not_called()


def test_missing_messages_key_returns_zero(mocker: MockerFixture, fresh_index: OfferIndex) -> None:
    """A response with no 'messages' key is treated as empty history, not an error."""
    client = mocker.Mock()
    client.conversations_history.return_value = {}
    mocker.patch.object(backfill, "parse_message", side_effect=_parser({}))

    count = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None)

    assert count == 0


# --- AC3: idempotent over a real OfferIndex ---


def test_double_run_yields_stable_index_size(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """Sweeping the same history twice keeps one row per (author, ts) — no duplicates."""
    offers = [_offer(offerer=f"U_OFF_{i}", source_ts=OFFER_TS) for i in range(3)]
    messages = [
        _msg(text=f"offer-{i}", user=f"U_OFF_{i}", ts=f"170000000{i}.000100") for i in range(3)
    ]
    mocker.patch.object(
        backfill, "parse_message", side_effect=_parser({f"offer-{i}": offers[i] for i in range(3)})
    )
    client = _history_client(mocker, messages)

    first = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None)
    size_after_first = len(fresh_index.all_offers())
    second = backfill.backfill_offer_index(client, channel_id=CHANNEL, user_token=None)
    size_after_second = len(fresh_index.all_offers())

    assert first == second == 3
    assert size_after_first == size_after_second == 3


# --- AC4: the BACKFILL_ON_START env read (default off; truthy spellings) ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("  TRUE  ", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("nope", False),
    ],
)
def test_backfill_enabled_reads_env(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    """The opt-in flag is off unless explicitly set to a truthy spelling."""
    monkeypatch.setenv(backfill.BACKFILL_ON_START_ENV, value)

    assert backfill._backfill_enabled() is expected


def test_backfill_disabled_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset BACKFILL_ON_START reads as off (default off)."""
    monkeypatch.delenv(backfill.BACKFILL_ON_START_ENV, raising=False)

    assert backfill._backfill_enabled() is False


# --- AC4: both gates of maybe_backfill_on_start ---


def test_gate_no_op_when_flag_disabled(mocker: MockerFixture) -> None:
    """BACKFILL_ON_START unset/false -> no thread, no history call, no board publish."""
    mocker.patch.object(backfill, "_backfill_enabled", return_value=False)
    designated = mocker.patch.object(backfill, "designated_channel_id", return_value=CHANNEL)
    thread = mocker.patch.object(backfill.threading, "Thread")
    client = mocker.Mock()

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x")

    thread.assert_not_called()
    designated.assert_not_called()
    client.conversations_history.assert_not_called()


def test_gate_no_op_when_channel_unset(mocker: MockerFixture) -> None:
    """Flag on but CRISIS_CHANNEL unset -> no thread spawned (nothing to back-fill)."""
    mocker.patch.object(backfill, "_backfill_enabled", return_value=True)
    mocker.patch.object(backfill, "designated_channel_id", return_value=None)
    thread = mocker.patch.object(backfill.threading, "Thread")
    client = mocker.Mock()

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x")

    thread.assert_not_called()
    client.conversations_history.assert_not_called()


def test_gate_open_spawns_a_daemon_thread(mocker: MockerFixture) -> None:
    """Both gates open -> a daemon Thread is started (non-blocking startup)."""
    mocker.patch.object(backfill, "_backfill_enabled", return_value=True)
    mocker.patch.object(backfill, "designated_channel_id", return_value=CHANNEL)
    thread_cls = mocker.patch.object(backfill.threading, "Thread")
    client = mocker.Mock()

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x", team_id="T1")

    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["daemon"] is True
    thread_cls.return_value.start.assert_called_once()


# --- AC5: the runner sweeps then publishes the board (thread run synchronously) ---


def test_runner_indexes_then_publishes_board(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """The spawned runner calls backfill_offer_index then update_board, in that order.

    The Thread is patched to run its target synchronously so we can assert the
    inner runner's effects without real concurrency.
    """
    mocker.patch.object(backfill, "_backfill_enabled", return_value=True)
    mocker.patch.object(backfill, "designated_channel_id", return_value=CHANNEL)
    calls: list[str] = []
    sweep = mocker.patch.object(
        backfill, "backfill_offer_index", side_effect=lambda *a, **k: calls.append("sweep") or 0
    )
    board = mocker.patch.object(
        backfill, "update_board", side_effect=lambda *a, **k: calls.append("board")
    )

    def _run_synchronously(*, target: Callable[[], None], **_kwargs: object) -> object:
        runner = mocker.Mock()
        runner.start.side_effect = target
        return runner

    mocker.patch.object(backfill.threading, "Thread", side_effect=_run_synchronously)
    client = mocker.Mock()

    client.auth_test.return_value = {"user_id": BOT_USER_ID}

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x", team_id="T1")

    assert calls == ["sweep", "board"]
    sweep.assert_called_once_with(
        client, channel_id=CHANNEL, user_token="xoxp-x", bot_user_id=BOT_USER_ID
    )
    board.assert_called_once_with(client, "xoxp-x", "T1")


# --- 032 AC5: maybe_backfill_on_start resolves bot_user_id best-effort + passes it ---


def _synchronous_thread(mocker: MockerFixture) -> Callable[..., object]:
    """A threading.Thread stand-in whose .start() runs the target synchronously."""

    def _factory(*, target: Callable[[], None], **_kwargs: object) -> object:
        runner = mocker.Mock()
        runner.start.side_effect = target
        return runner

    return _factory


def test_resolves_bot_user_id_and_passes_it_to_sweep(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """The runner resolves bot_user_id via auth_test and forwards it to the sweep (AC5)."""
    mocker.patch.object(backfill, "_backfill_enabled", return_value=True)
    mocker.patch.object(backfill, "designated_channel_id", return_value=CHANNEL)
    sweep = mocker.patch.object(backfill, "backfill_offer_index", return_value=0)
    mocker.patch.object(backfill, "update_board")
    mocker.patch.object(backfill.threading, "Thread", side_effect=_synchronous_thread(mocker))
    client = mocker.Mock()
    client.auth_test.return_value = {"user_id": BOT_USER_ID}

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x", team_id="T1")

    client.auth_test.assert_called_once_with()
    sweep.assert_called_once_with(
        client, channel_id=CHANNEL, user_token="xoxp-x", bot_user_id=BOT_USER_ID
    )


def test_auth_test_failure_does_not_break_the_sweep(
    mocker: MockerFixture, fresh_index: OfferIndex
) -> None:
    """auth_test raising -> bot_user_id resolves to None; the sweep still runs (AC5).

    Resolving bot_user_id is best-effort and must never raise out of the daemon-thread
    sweep, so a failure falls back to None (the defensive bot_id skip path).
    """
    mocker.patch.object(backfill, "_backfill_enabled", return_value=True)
    mocker.patch.object(backfill, "designated_channel_id", return_value=CHANNEL)
    sweep = mocker.patch.object(backfill, "backfill_offer_index", return_value=0)
    board = mocker.patch.object(backfill, "update_board")
    mocker.patch.object(backfill.threading, "Thread", side_effect=_synchronous_thread(mocker))
    client = mocker.Mock()
    client.auth_test.side_effect = RuntimeError("auth_test down")

    backfill.maybe_backfill_on_start(client, user_token="xoxp-x", team_id="T1")

    sweep.assert_called_once_with(client, channel_id=CHANNEL, user_token="xoxp-x", bot_user_id=None)
    board.assert_called_once_with(client, "xoxp-x", "T1")
