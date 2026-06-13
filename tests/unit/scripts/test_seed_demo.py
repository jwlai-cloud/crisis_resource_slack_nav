"""Unit tests for scripts.seed_demo — the Exmouth scenario seeder.

No live API and no real channel scan: the WebClient and ``load_dotenv`` are
mocked, env is patched, and the channel-history scan is fed canned responses.
These pin three contracts the demo operator depends on:

- the scenario content is credible and complete (the offers/notices/chatter the
  demo script beats need),
- every seeded message carries the idempotency marker, and
- a re-run skips messages already present (by marker) and ``--fresh`` deletes the
  prior seed first — so running twice never duplicates the channel.
"""

from pytest_mock import MockerFixture

from scripts import seed_demo

# ----- scenario content -----


def test_scenario_has_expected_message_counts() -> None:
    """5-6 offers, 1-2 coordinator notices, and a few lines of chatter."""
    offers = [m for m in seed_demo.SCENARIO if m.kind == "offer"]
    notices = [m for m in seed_demo.SCENARIO if m.kind == "notice"]
    chatter = [m for m in seed_demo.SCENARIO if m.kind == "chatter"]

    assert 5 <= len(offers) <= 6
    assert 1 <= len(notices) <= 2
    assert 3 <= len(chatter) <= 4


def test_offers_cover_the_demo_resources() -> None:
    """The offers name the demo-script resources: generator, water, beds, formula, room, first aid."""
    offer_text = " ".join(m.text.lower() for m in seed_demo.SCENARIO if m.kind == "offer")

    assert "generator" in offer_text
    assert "water" in offer_text
    assert "bed" in offer_text
    assert "formula" in offer_text
    assert "room" in offer_text
    assert "first" in offer_text and "aid" in offer_text


def test_offers_spread_across_the_three_localities() -> None:
    """Offers are spread across Exmouth / North Exmouth / Learmonth."""
    offer_text = " ".join(m.text.lower() for m in seed_demo.SCENARIO if m.kind == "offer")

    assert "north exmouth" in offer_text
    assert "learmonth" in offer_text
    # Plain "Exmouth" appears beyond the "North Exmouth" / "Minilya-Exmouth" compounds.
    assert offer_text.count("exmouth") > offer_text.count("north exmouth")


def test_coordinator_notice_reads_like_an_ses_dfes_update() -> None:
    """At least one notice is an SES/DFES-style operational update."""
    notice_text = " ".join(m.text for m in seed_demo.SCENARIO if m.kind == "notice")

    assert "SES" in notice_text or "DFES" in notice_text


def test_offers_are_phrased_as_mutual_aid_posts() -> None:
    """Each offer opens like a real mutual-aid post ("Offering: ...")."""
    offers = [m for m in seed_demo.SCENARIO if m.kind == "offer"]

    assert all(m.text.lower().startswith("offering") for m in offers)


# ----- marker / message building -----


def test_with_marker_appends_the_marker_suffix() -> None:
    """The built message ends with the hidden seed marker."""
    built = seed_demo.with_marker("Offering: a 2kW generator (Exmouth)")

    assert built.endswith(seed_demo.SEED_MARKER)
    assert built.startswith("Offering: a 2kW generator (Exmouth)")


def test_is_seeded_message_detects_the_marker() -> None:
    """A message carrying the marker is recognised as a prior seed; a plain one is not."""
    seeded = seed_demo.with_marker("SES update: road closed")

    assert seed_demo.is_seeded_message(seeded) is True
    assert seed_demo.is_seeded_message("just a normal community message") is False


# ----- idempotency decision -----


def test_pending_messages_returns_all_when_nothing_seeded() -> None:
    """With no prior seed every scenario message is pending."""
    pending = seed_demo.pending_messages(seed_demo.SCENARIO, already_posted=set())

    assert len(pending) == len(seed_demo.SCENARIO)


def test_pending_messages_skips_already_posted() -> None:
    """Messages whose marked text is already in the channel are skipped."""
    first_two = seed_demo.SCENARIO[:2]
    already = {seed_demo.with_marker(m.text) for m in first_two}

    pending = seed_demo.pending_messages(seed_demo.SCENARIO, already_posted=already)

    assert len(pending) == len(seed_demo.SCENARIO) - 2
    assert all(seed_demo.with_marker(m.text) not in already for m in pending)


# ----- orchestration: env guards + posting -----


def test_missing_user_token_exits_nonzero_without_posting(mocker: MockerFixture) -> None:
    """With no SLACK_USER_TOKEN the seeder fails fast and never posts."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value=None)
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": "C_CRISIS"}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value

    rc = seed_demo.main([])

    assert rc == 1
    client.chat_postMessage.assert_not_called()


def test_missing_crisis_channel_exits_nonzero_without_posting(mocker: MockerFixture) -> None:
    """With no CRISIS_CHANNEL the seeder fails fast and never posts."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value="xoxp-user")
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": ""}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value

    rc = seed_demo.main([])

    assert rc == 1
    client.chat_postMessage.assert_not_called()


def test_fresh_run_posts_every_scenario_message_with_marker(mocker: MockerFixture) -> None:
    """A first run on an empty channel posts every message, each marked, via the user token."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value="xoxp-user")
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": "C_CRISIS"}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value
    # Empty channel: history scan returns no prior seed.
    client.conversations_history.return_value = {"messages": [], "has_more": False}
    client.chat_postMessage.return_value = {"ok": True, "ts": "1.0"}

    rc = seed_demo.main([])

    assert rc == 0
    assert client.chat_postMessage.call_count == len(seed_demo.SCENARIO)
    for call in client.chat_postMessage.call_args_list:
        assert call.kwargs["channel"] == "C_CRISIS"
        assert call.kwargs["token"] == "xoxp-user"
        assert seed_demo.is_seeded_message(call.kwargs["text"])


def test_rerun_skips_already_seeded_messages(mocker: MockerFixture) -> None:
    """A second run finds the prior seed in history and posts nothing new."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value="xoxp-user")
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": "C_CRISIS"}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value
    prior = [
        {"ts": f"{i}.0", "text": seed_demo.with_marker(m.text)}
        for i, m in enumerate(seed_demo.SCENARIO)
    ]
    client.conversations_history.return_value = {"messages": prior, "has_more": False}

    rc = seed_demo.main([])

    assert rc == 0
    client.chat_postMessage.assert_not_called()


def test_fresh_flag_deletes_prior_seed_then_reposts(mocker: MockerFixture) -> None:
    """``--fresh`` deletes every prior marked message, then reposts the full scenario."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value="xoxp-user")
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": "C_CRISIS"}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value
    prior = [
        {"ts": "100.1", "text": seed_demo.with_marker(seed_demo.SCENARIO[0].text)},
        {"ts": "100.2", "text": "an unrelated community message"},
        {"ts": "100.3", "text": seed_demo.with_marker(seed_demo.SCENARIO[1].text)},
    ]
    client.conversations_history.return_value = {"messages": prior, "has_more": False}
    client.chat_postMessage.return_value = {"ok": True, "ts": "1.0"}

    rc = seed_demo.main(["--fresh"])

    assert rc == 0
    # Only the two marked messages are deleted; the unrelated one is left alone.
    deleted_ts = {c.kwargs["ts"] for c in client.chat_delete.call_args_list}
    assert deleted_ts == {"100.1", "100.3"}
    # After the reset the full scenario is reposted.
    assert client.chat_postMessage.call_count == len(seed_demo.SCENARIO)


def test_fresh_flag_does_not_delete_unmarked_messages(mocker: MockerFixture) -> None:
    """``--fresh`` never deletes ordinary (unmarked) channel messages."""
    mocker.patch("scripts.seed_demo.load_dotenv")
    mocker.patch("scripts.seed_demo.resolve_user_token", return_value="xoxp-user")
    mocker.patch.dict("os.environ", {"CRISIS_CHANNEL": "C_CRISIS"}, clear=False)
    client = mocker.patch("scripts.seed_demo.WebClient").return_value
    client.conversations_history.return_value = {
        "messages": [{"ts": "1.0", "text": "real human chatter, do not touch"}],
        "has_more": False,
    }
    client.chat_postMessage.return_value = {"ok": True, "ts": "1.0"}

    rc = seed_demo.main(["--fresh"])

    assert rc == 0
    client.chat_delete.assert_not_called()
