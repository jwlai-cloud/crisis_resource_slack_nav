"""Unit tests for recall.blocks — Block Kit composition.

Blocks are asserted as structured dicts (``Block.to_dict()``): we check block
types and that the guardrail content is present on *every* match — source
(author + channel), timestamp, permalink, and the verify note — plus the
explicit degraded (RecallError) and empty (no matches) reply shapes. Match
builders come from the ``make_match`` fixture in conftest.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from recall.blocks import (
    ACTION_CONNECT,
    ACTION_NOT_RELEVANT,
    VERIFY_NOTE,
    build_recall_blocks,
)
from recall.models import RecallError, RecallMatch
from recall.payload import ConnectPayload


def _dicts(result) -> list[dict]:
    return [b.to_dict() for b in build_recall_blocks(result)]


def _text_of(block: dict) -> str:
    """Flatten a block's visible text (section text or joined context elements)."""
    if "text" in block:
        return block["text"]["text"]
    return " ".join(e["text"] for e in block.get("elements", []))


def test_error_result_renders_single_unavailable_block() -> None:
    """A RecallError composes one explicit 'couldn't search' block — never silent."""
    blocks = _dicts(RecallError(reason="ratelimited"))

    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    text = _text_of(blocks[0]).lower()
    assert "couldn't search the workspace" in text


def test_empty_result_renders_explicit_no_matches_block() -> None:
    """Zero matches composes an explicit 'no prior offers' block, not silence."""
    blocks = _dicts([])

    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert "no prior offers" in _text_of(blocks[0]).lower()


def test_single_match_carries_source_timestamp_and_verify(
    make_match: Callable[..., RecallMatch],
) -> None:
    """One match: snippet block + a context block with who/where/when/link/verify."""
    match = make_match(
        text="spare generator in Exmouth",
        author="Jordan",
        channel="offers",
        ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
        permalink="https://x/p1",
    )

    blocks = _dicts([match])

    # header, section (snippet), context (sourcing), actions (confirmation buttons)
    types = [b["type"] for b in blocks]
    assert types == ["header", "section", "context", "actions"]
    assert _text_of(blocks[1]) == "spare generator in Exmouth"
    context_text = _text_of(blocks[2])
    assert "Jordan" in context_text  # author
    assert "#offers" in context_text  # channel
    assert "2026-03-21 09:30 UTC" in context_text  # timestamp
    assert "https://x/p1" in context_text  # permalink
    assert VERIFY_NOTE in context_text  # verify-before-relying note


def test_every_match_has_source_timestamp_and_verify(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The sourcing guardrail holds for EVERY item, not just the first."""
    matches = [
        make_match(text="m1", author="Jordan", channel="offers", permalink="https://x/p1"),
        make_match(text="m2", author="Sam", channel="general", permalink="https://x/p2"),
        make_match(text="m3", author="Lee", channel="aid", permalink="https://x/p3"),
    ]

    blocks = _dicts(matches)

    # Every context block carries source + timestamp + verify.
    context_blocks = [b for b in blocks if b["type"] == "context"]
    assert len(context_blocks) == len(matches)
    for ctx in context_blocks:
        text = _text_of(ctx)
        assert "Posted by" in text  # who
        assert "UTC" in text  # when
        assert "View message" in text  # permalink link label
        assert VERIFY_NOTE in text  # verify note


def test_multiple_matches_are_divider_separated(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Match groups are separated by dividers so the list is scannable."""
    matches = [make_match(text="m1"), make_match(text="m2")]

    types = [b["type"] for b in _dicts(matches)]

    assert "divider" in types
    # header + (section+context+actions) + divider + (section+context+actions)
    assert types.count("section") == 2
    assert types.count("context") == 2
    assert types.count("actions") == 2


def test_match_without_permalink_still_sourced(
    make_match: Callable[..., RecallMatch],
) -> None:
    """A hit with no permalink still renders author/channel/timestamp + verify."""
    match = make_match(permalink="")

    context_text = _text_of(_dicts([match])[2])

    assert "View message" not in context_text  # no link rendered
    assert "Posted by" in context_text
    assert VERIFY_NOTE in context_text


def test_match_carries_tappable_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Every match renders a tappable `Contact: <@author_id>` Slack mention."""
    match = make_match()  # author_id defaults to "U_OFFERER" in the fixture

    context_text = _text_of(_dicts([match])[2])

    assert "Contact: <@U_OFFERER>" in context_text


def test_every_match_has_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The contact mention holds for EVERY item, alongside source + timestamp + verify."""
    matches = [make_match(text="m1"), make_match(text="m2"), make_match(text="m3")]

    context_blocks = [b for b in _dicts(matches) if b["type"] == "context"]

    assert len(context_blocks) == len(matches)
    for ctx in context_blocks:
        assert "Contact: <@U_OFFERER>" in _text_of(ctx)


def test_match_without_author_id_omits_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """A hit with no author_id omits the contact line — never an empty `<@>` mention."""
    match = make_match()
    match.author_id = ""

    context_text = _text_of(_dicts([match])[2])

    assert "Contact:" not in context_text  # no broken/empty mention
    assert "Posted by" in context_text  # still sourced


def _action_blocks(result) -> list[dict]:
    return [b for b in _dicts(result) if b["type"] == "actions"]


def test_match_card_carries_connect_and_not_relevant_buttons(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Every workspace match gains a Connect (primary) + Not relevant confirmation row."""
    actions = _action_blocks([make_match()])

    assert len(actions) == 1
    elements = actions[0]["elements"]
    action_ids = [e["action_id"] for e in elements]
    assert action_ids == [ACTION_CONNECT, ACTION_NOT_RELEVANT]
    # Connect is the primary call to action.
    connect = next(e for e in elements if e["action_id"] == ACTION_CONNECT)
    assert connect["style"] == "primary"
    assert connect["text"]["text"] == "Connect me"


def test_every_match_card_carries_action_buttons(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The confirmation row holds for EVERY rendered match, not just the first."""
    matches = [make_match(text="m1"), make_match(text="m2"), make_match(text="m3")]

    actions = _action_blocks(matches)

    assert len(actions) == len(matches)
    for block in actions:
        assert [e["action_id"] for e in block["elements"]] == [
            ACTION_CONNECT,
            ACTION_NOT_RELEVANT,
        ]
    # Each row has a unique block_id so a handler can rewrite the right card.
    assert len({b["block_id"] for b in actions}) == len(matches)


def test_button_value_carries_index_offer_id_when_present(
    make_match: Callable[..., RecallMatch],
) -> None:
    """An index-hit card encodes its offer id + offerer in the button value."""
    match = make_match()
    match.offer_id = "offer-123"

    connect = _action_blocks([match])[0]["elements"][0]
    payload = ConnectPayload.from_value(connect["value"])

    assert payload.offer_id == "offer-123"
    assert payload.offerer_id == "U_OFFERER"  # the fixture's author_id


def test_button_value_carries_permalink_for_rts_only_match(
    make_match: Callable[..., RecallMatch],
) -> None:
    """An RTS-only card (no offer id) encodes the offerer + permalink for sourcing."""
    match = make_match(permalink="https://x/p1")  # offer_id stays "" (RTS hit)

    connect = _action_blocks([match])[0]["elements"][0]
    payload = ConnectPayload.from_value(connect["value"])

    assert payload.offer_id == ""
    assert payload.permalink == "https://x/p1"
    assert payload.offerer_id == "U_OFFERER"


def test_button_value_omits_requester_identity(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The requester is never in the payload — it is the human who clicks (no auto-action)."""
    connect = _action_blocks([make_match()])[0]["elements"][0]

    assert "requester" not in connect["value"]


def test_degraded_result_has_no_action_buttons() -> None:
    """A degraded (RecallError) reply carries no buttons — nothing to act on."""
    assert _action_blocks(RecallError(reason="ratelimited")) == []


def test_empty_result_has_no_action_buttons() -> None:
    """A zero-match reply carries no buttons — nothing to confirm."""
    assert _action_blocks([]) == []
