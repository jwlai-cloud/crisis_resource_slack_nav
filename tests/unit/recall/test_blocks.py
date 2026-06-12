"""Unit tests for recall.blocks — Block Kit composition.

Blocks are asserted as structured dicts (``Block.to_dict()``): we check block
types and that the guardrail content is present on *every* match — source
(author + channel), timestamp, permalink, and the verify note — plus the
explicit degraded (RecallError) and empty (no matches) reply shapes. Match
builders come from the ``make_match`` fixture in conftest.

Task 008 (match-card visual parity) added two code-composed elements asserted
here: a parse-summary ``section`` with ``fields`` (need_type / location /
urgency / household), composed from the parsed Need, and a per-card rank-label
context line (``🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH``). The 010 action
rows must survive the restyle untouched, so the button assertions stay.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from entities import Need, Urgency, deterministic_id
from matching.conversion import INDEX_SOURCE_CHANNEL
from recall.blocks import (
    ACTION_CONNECT,
    ACTION_NOT_RELEVANT,
    VERIFY_NOTE,
    WORKSPACE_BAR_EMOJI,
    build_recall_blocks,
)
from recall.models import RecallError, RecallMatch
from recall.payload import ConnectPayload


def _dicts(result, need: Need | None = None) -> list[dict]:
    return [b.to_dict() for b in build_recall_blocks(result, need=need)]


def _text_of(block: dict) -> str:
    """Flatten a block's visible text (section text or joined context elements)."""
    if "text" in block:
        return block["text"]["text"]
    return " ".join(e["text"] for e in block.get("elements", []))


def _sourcing_text(result, need: Need | None = None) -> str:
    """The text of the (single) sourcing context block — the who/where/when line."""
    sourcing = [
        b
        for b in _dicts(result, need=need)
        if b["type"] == "context" and "Posted by" in _text_of(b)
    ]
    assert len(sourcing) == 1
    return _text_of(sourcing[0])


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

    # header, rank-label context, section (snippet), context (sourcing),
    # actions (confirmation buttons)
    types = [b["type"] for b in blocks]
    assert types == ["header", "context", "section", "context", "actions"]
    assert _text_of(blocks[2]) == "spare generator in Exmouth"
    context_text = _text_of(blocks[3])
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

    # Every sourcing context block carries source + timestamp + verify. (Rank-label
    # context blocks also exist now; we target the sourcing ones by their content.)
    sourcing_blocks = [b for b in blocks if b["type"] == "context" and "Posted by" in _text_of(b)]
    assert len(sourcing_blocks) == len(matches)
    for ctx in sourcing_blocks:
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

    blocks = _dicts(matches)
    types = [b["type"] for b in blocks]

    assert "divider" in types
    # header + (rank-context + section + sourcing-context + actions) + divider + (...)
    assert types.count("section") == 2
    # Two context blocks per card now: the rank label and the sourcing line.
    assert types.count("context") == 4
    assert types.count("actions") == 2
    sourcing_blocks = [b for b in blocks if b["type"] == "context" and "Posted by" in _text_of(b)]
    assert len(sourcing_blocks) == 2


def test_match_without_permalink_still_sourced(
    make_match: Callable[..., RecallMatch],
) -> None:
    """A hit with no permalink still renders author/channel/timestamp + verify."""
    match = make_match(permalink="")

    context_text = _sourcing_text([match])

    assert "View message" not in context_text  # no link rendered
    assert "Posted by" in context_text
    assert VERIFY_NOTE in context_text


def test_match_carries_tappable_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Every match renders a tappable `Contact: <@author_id>` Slack mention."""
    match = make_match()  # author_id defaults to "U_OFFERER" in the fixture

    context_text = _sourcing_text([match])

    assert "Contact: <@U_OFFERER>" in context_text


def test_real_channel_is_hash_prefixed(
    make_match: Callable[..., RecallMatch],
) -> None:
    """A real Slack channel still renders with a leading `#` (e.g. `in #general`)."""
    match = make_match(channel="general")

    context_text = _sourcing_text([match])

    assert "in #general" in context_text


def test_index_provenance_label_is_not_hash_prefixed(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The index provenance label renders WITHOUT a `#` (016 amendment, cosmetic).

    An index-only hit carries the "workspace memory" provenance label, not a Slack
    channel. Prefixing it with `#` ("in #workspace memory") would dress a
    non-channel up as one; it must read "in workspace memory".
    """
    match = make_match(channel=INDEX_SOURCE_CHANNEL)

    context_text = _sourcing_text([match])

    assert f"in {INDEX_SOURCE_CHANNEL}" in context_text
    assert f"#{INDEX_SOURCE_CHANNEL}" not in context_text


def test_every_match_has_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The contact mention holds for EVERY item, alongside source + timestamp + verify."""
    matches = [make_match(text="m1"), make_match(text="m2"), make_match(text="m3")]

    sourcing_blocks = [
        b for b in _dicts(matches) if b["type"] == "context" and "Posted by" in _text_of(b)
    ]

    assert len(sourcing_blocks) == len(matches)
    for ctx in sourcing_blocks:
        assert "Contact: <@U_OFFERER>" in _text_of(ctx)


def test_match_without_author_id_omits_contact_mention(
    make_match: Callable[..., RecallMatch],
) -> None:
    """A hit with no author_id omits the contact line — never an empty `<@>` mention."""
    match = make_match()
    match.author_id = ""

    context_text = _sourcing_text([match])

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


# --- Task 008: parse-summary fields ---------------------------------------


def _need(**overrides: object) -> Need:
    fields: dict[str, object] = {
        "id": deterministic_id("U_REQ", datetime(2026, 3, 21, 11, 30, tzinfo=UTC)),
        "requester": "U_REQ",
        "need_type": "generator",
        "location": "North Exmouth",
        "urgency": Urgency.HIGH,
        "household_size": 4,
        "source_ts": datetime(2026, 3, 21, 11, 30, tzinfo=UTC),
    }
    fields.update(overrides)
    return Need(**fields)


def _fields_block(result, need: Need | None) -> dict | None:
    """The leading section block that carries the parse-summary ``fields``, if any."""
    for block in _dicts(result, need=need):
        if block["type"] == "section" and "fields" in block:
            return block
    return None


def test_parse_summary_opens_structured_region_with_fields(
    make_match: Callable[..., RecallMatch],
) -> None:
    """When a Need is recognised, the reply opens with a section carrying fields."""
    blocks = _dicts([make_match()], need=_need())

    # The very first block is the parse-summary section (before the recall header).
    assert blocks[0]["type"] == "section"
    assert "fields" in blocks[0]
    field_texts = [f["text"] for f in blocks[0]["fields"]]
    joined = "\n".join(field_texts)
    assert "need_type" in joined
    assert "generator" in joined
    assert "location" in joined
    assert "North Exmouth" in joined
    assert "urgency" in joined
    assert "high" in joined
    assert "household" in joined
    assert "4" in joined


def test_parse_summary_fields_composed_by_code_not_llm(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The field values come verbatim from the Need object (code-composed)."""
    need = _need(need_type="water", location="Town", urgency=Urgency.CRITICAL, household_size=2)

    block = _fields_block([make_match()], need)

    assert block is not None
    joined = "\n".join(f["text"] for f in block["fields"])
    assert "water" in joined
    assert "Town" in joined
    assert "critical" in joined
    assert "2" in joined


def test_parse_summary_omits_unknown_fields_no_placeholders(
    make_match: Callable[..., RecallMatch],
) -> None:
    """An empty/unknown field is omitted entirely — never a '?' or empty placeholder."""
    need = _need(location="", need_type="generator")

    block = _fields_block([make_match()], need)

    assert block is not None
    joined = "\n".join(f["text"] for f in block["fields"])
    assert "location" not in joined  # omitted, not shown blank
    assert "?" not in joined
    assert "need_type" in joined  # the known fields still render


def test_parse_summary_caps_fields_under_slack_limit(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Slack allows max 10 fields per section; our four-field summary stays well under."""
    block = _fields_block([make_match()], _need())

    assert block is not None
    assert len(block["fields"]) <= 10


def test_no_need_omits_parse_summary(make_match: Callable[..., RecallMatch]) -> None:
    """Called without a Need (back-compat), no parse-summary section is emitted."""
    blocks = _dicts([make_match()], need=None)

    assert blocks[0]["type"] == "header"  # straight to the recall header, no fields block
    assert _fields_block([make_match()], None) is None


def test_parse_summary_present_on_degraded_and_empty(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The parse summary still leads the reply on degraded and empty recall results."""
    for result in (RecallError(reason="ratelimited"), []):
        block = _fields_block(result, _need())
        assert block is not None
        assert "need_type" in "\n".join(f["text"] for f in block["fields"])


# --- Task 008: per-card rank label ----------------------------------------


def _rank_lines(result, need: Need | None = None) -> list[str]:
    """The rank-label context lines (the `… MATCH n · WORKSPACE · …` headers)."""
    return [
        _text_of(b)
        for b in _dicts(result, need=need)
        if b["type"] == "context" and "MATCH" in _text_of(b)
    ]


def test_each_match_has_a_workspace_rank_label(
    make_match: Callable[..., RecallMatch],
) -> None:
    """Every workspace card opens with `🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH`."""
    matches = [make_match(text="m1"), make_match(text="m2"), make_match(text="m3")]

    lines = _rank_lines(matches)

    assert lines == [
        f"{WORKSPACE_BAR_EMOJI} *MATCH 1* · WORKSPACE · REAL-TIME SEARCH",
        f"{WORKSPACE_BAR_EMOJI} *MATCH 2* · WORKSPACE · REAL-TIME SEARCH",
        f"{WORKSPACE_BAR_EMOJI} *MATCH 3* · WORKSPACE · REAL-TIME SEARCH",
    ]


def test_rank_label_uses_colored_square_as_left_bar_cue(
    make_match: Callable[..., RecallMatch],
) -> None:
    """The colored-square emoji stands in for the mock's colored left bar (green = workspace)."""
    line = _rank_lines([make_match()])[0]

    assert line.startswith(WORKSPACE_BAR_EMOJI)
    assert WORKSPACE_BAR_EMOJI == "🟩"  # green, matching the mock's workspace card bar


def test_rank_label_numbering_caps_with_rendered_matches(
    make_match: Callable[..., RecallMatch],
) -> None:
    """With more than the top-N cap, only the rendered cards get numbered labels."""
    matches = [make_match(text=f"m{i}") for i in range(7)]

    lines = _rank_lines(matches)

    assert len(lines) == 5  # the top-5 cap
    assert lines[0].startswith(f"{WORKSPACE_BAR_EMOJI} *MATCH 1*")
    assert lines[-1].startswith(f"{WORKSPACE_BAR_EMOJI} *MATCH 5*")


def test_degraded_and_empty_have_no_rank_labels() -> None:
    """No cards -> no rank labels (degraded / empty)."""
    assert _rank_lines(RecallError(reason="x")) == []
    assert _rank_lines([]) == []
