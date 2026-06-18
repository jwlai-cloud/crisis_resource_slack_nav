"""Unit tests for recall.official_blocks — the official-card composition (task 028).

``build_official_blocks(need, situation)`` is a pure ``(Need, SituationSnapshot) ->
list[Block]`` render: it applies a deterministic need_type -> feed relevance map,
selects up to a few records from the relevant feed(s), and composes emoji-cue
"Official information" cards mirroring the workspace cards in :mod:`recall.blocks`
(but blue/red and *button-free*). Blocks are asserted as structured dicts
(``Block.to_dict()``).

Every guardrail the workspace cards honour, these honour too:

* **Every official item is sourced + timestamped** — a context line carrying the
  feed name + an *absolute* UTC ``fetched <…>`` stamp, plus the standing verify note.
* **Never assert safety** — the card relays the feed's own status word verbatim
  (e.g. a road "CLOSED"); no "safe"/"okay to travel" phrasing is ever composed.
* **Degraded feeds stay loud** — a feed relevant to the need but ``available=False``
  renders an explicit "unavailable — <detail>" card, never dropped.
* **No action buttons** — you do not "Connect" to a road closure.

If no feed is relevant to the need, NO official section renders (``[]``) — the
no-noise rule (task 012), never a dump of the full picture.
"""

from datetime import UTC, datetime

from coordinator.situation import SituationFeed, SituationSnapshot
from entities import Need, Urgency, deterministic_id
from mocks.server import EvacCentre, OfficialAdvice, RoadClosure
from recall.official_blocks import (
    OFFICIAL_ADVISORY_BAR_EMOJI,
    OFFICIAL_INFO_BAR_EMOJI,
    OFFICIAL_SECTION_HEADER,
    OFFICIAL_UNAVAILABLE_ALERT,
    VERIFY_NOTE,
    build_official_blocks,
    build_official_unavailable_blocks,
    is_official_fully_unavailable,
)

FETCHED_AT = datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
UPDATED_AT = datetime(2026, 3, 15, 5, 30, tzinfo=UTC)
ABSOLUTE_STAMP = "2026-03-15 06:30 UTC"


# --- builders ----------------------------------------------------------------


def _need(*, need_type: str, is_information: bool = False, location: str = "Exmouth") -> Need:
    """A Need keyed on ``need_type`` (the field the relevance map reads)."""
    ts = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)
    return Need(
        id=deterministic_id("U_REQ", ts),
        requester="U_REQ",
        need_type=need_type,
        location=location,
        urgency=Urgency.HIGH,
        household_size=3,
        is_information=is_information,
        source_ts=ts,
    )


def _road_record(*, status: str = "CLOSED") -> RoadClosure:
    return RoadClosure(
        road="Minilya-Exmouth Road",
        segment="Yannarie River crossing",
        status=status,
        reason="Floodwater over road.",
        detour="No detour available.",
        updated_at=UPDATED_AT,
    )


def _evac_record(*, services: list[str] | None = None) -> EvacCentre:
    return EvacCentre(
        name="Exmouth Recreation Centre",
        address="Murat Road, Exmouth WA 6707",
        status="OPEN",
        capacity=250,
        occupancy=168,
        services=services or ["Emergency water point", "Bedding and shelter"],
        updated_at=UPDATED_AT,
    )


def _advice_record(*, title: str = "Power and water outage — Exmouth") -> OfficialAdvice:
    return OfficialAdvice(
        title=title,
        level="Advice",
        area="Exmouth",
        message="Power and water remain down.",
        advice="Conserve battery and stored water.",
        updated_at=UPDATED_AT,
    )


def _feed(name: str, records: tuple[object, ...]) -> SituationFeed:
    return SituationFeed(feed=name, available=True, fetched_at=FETCHED_AT, records=records)


def _down_feed(name: str, detail: str) -> SituationFeed:
    return SituationFeed(feed=name, available=False, detail=detail)


def _empty_feed(name: str) -> SituationFeed:
    return SituationFeed(feed=name, available=True, fetched_at=FETCHED_AT, records=())


def _situation(
    *,
    road: SituationFeed | None = None,
    evac: SituationFeed | None = None,
    advice: SituationFeed | None = None,
) -> SituationSnapshot:
    return SituationSnapshot(
        road_closures=road or _empty_feed("road_closures"),
        evac_centres=evac or _empty_feed("evac_centres"),
        official_advice=advice or _empty_feed("official_advice"),
    )


# --- helpers -----------------------------------------------------------------


def _dicts(need: Need, situation: SituationSnapshot) -> list[dict]:
    return [b.to_dict() for b in build_official_blocks(need, situation)]


def _text_of(block: dict) -> str:
    if "text" in block:
        return block["text"]["text"]
    return " ".join(e["text"] for e in block.get("elements", []))


def _all_text(need: Need, situation: SituationSnapshot) -> str:
    return "\n".join(_text_of(b) for b in _dicts(need, situation))


# --- AC2: relevance map ------------------------------------------------------


def test_water_need_surfaces_evac_water_point() -> None:
    """A water/supply need surfaces the evac centre carrying a water point (blue card)."""
    situation = _situation(
        road=_feed("road_closures", (_road_record(),)),
        evac=_feed("evac_centres", (_evac_record(),)),
    )

    text = _all_text(_need(need_type="drinking water"), situation)

    assert OFFICIAL_SECTION_HEADER in text
    assert "Exmouth Recreation Centre" in text  # the relevant centre
    assert "Minilya-Exmouth Road" not in text  # the road list is NOT dumped


def test_travel_need_surfaces_road_closure() -> None:
    """A travel/road need surfaces the road closure (red advisory card)."""
    situation = _situation(
        road=_feed("road_closures", (_road_record(),)),
        evac=_feed("evac_centres", (_evac_record(),)),
    )

    text = _all_text(_need(need_type="can I drive to town"), situation)

    assert "Minilya-Exmouth Road" in text
    assert "CLOSED" in text  # the feed's own status word, verbatim
    assert "Exmouth Recreation Centre" not in text  # evac list not dumped


def test_shelter_need_surfaces_evac_centre() -> None:
    """A shelter/somewhere-to-stay need surfaces the evacuation centre (blue card)."""
    situation = _situation(evac=_feed("evac_centres", (_evac_record(),)))

    text = _all_text(_need(need_type="somewhere to shelter"), situation)

    assert OFFICIAL_SECTION_HEADER in text
    assert "Exmouth Recreation Centre" in text


def test_official_warning_need_surfaces_advice() -> None:
    """An official-warning status question surfaces the advice notice (blue card)."""
    situation = _situation(advice=_feed("official_advice", (_advice_record(),)))

    text = _all_text(_need(need_type="official warning status", is_information=True), situation)

    assert OFFICIAL_SECTION_HEADER in text
    assert "Power and water outage" in text


def test_unrelated_need_renders_no_official_section() -> None:
    """A need with no relevant feed -> NO official section (the no-dump rule)."""
    situation = _situation(
        road=_feed("road_closures", (_road_record(),)),
        evac=_feed("evac_centres", (_evac_record(),)),
        advice=_feed("official_advice", (_advice_record(),)),
    )

    blocks = build_official_blocks(_need(need_type="baby formula"), situation)

    assert blocks == []  # nothing relevant -> no section, no dump


def test_safety_question_surfaces_relevant_closure() -> None:
    """A safety question ("is the road safe") surfaces the relevant closure verbatim."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))

    text = _all_text(_need(need_type="road safety", is_information=True), situation)

    assert "Minilya-Exmouth Road" in text
    assert "CLOSED" in text


def test_caps_records_to_about_three() -> None:
    """At most ~3 official records render even when the relevant feed has more."""
    many = tuple(_road_record(status=f"STATUS-{i}") for i in range(6))  # six closures in the feed
    situation = _situation(road=_feed("road_closures", many))

    cards = [b for b in _dicts(_need(need_type="road travel"), situation) if b["type"] == "section"]

    assert len(cards) <= 3  # capped, not all six


# --- AC1: card shape (header, emoji cue, source + UTC, verify, no buttons) ----


def test_water_card_is_blue_with_feed_utc_and_verify_no_button() -> None:
    """The water card: blue cue, feed + absolute-UTC stamp, verify note, NO action row."""
    situation = _situation(evac=_feed("evac_centres", (_evac_record(),)))

    blocks = _dicts(_need(need_type="drinking water"), situation)
    types = [b["type"] for b in blocks]

    assert "actions" not in types  # no Connect/Not-relevant — info only (guardrail 1)
    text = "\n".join(_text_of(b) for b in blocks)
    assert OFFICIAL_INFO_BAR_EMOJI in text  # blue cue for info
    assert "evac_centres" in text  # feed name sourced
    assert ABSOLUTE_STAMP in text  # absolute UTC, not relative
    assert "fetched" in text
    assert VERIFY_NOTE in text


def test_road_card_is_red_advisory_cue() -> None:
    """The road-closure card uses the red advisory cue (closure/warning)."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))

    text = _all_text(_need(need_type="road travel"), situation)

    assert OFFICIAL_ADVISORY_BAR_EMOJI in text  # red cue for closures/warnings


def test_section_opens_with_official_information_header() -> None:
    """The official cards sit under an 'Official information' header block."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))

    blocks = _dicts(_need(need_type="road travel"), situation)

    assert blocks[0]["type"] == "header"
    assert OFFICIAL_SECTION_HEADER in _text_of(blocks[0])


def test_no_official_card_carries_action_buttons() -> None:
    """Across every feed type, official cards never carry an actions block (guardrail 1)."""
    situation = _situation(
        road=_feed("road_closures", (_road_record(),)),
        evac=_feed("evac_centres", (_evac_record(),)),
        advice=_feed("official_advice", (_advice_record(),)),
    )

    for need_type in ("road travel", "drinking water", "official warning"):
        blocks = _dicts(_need(need_type=need_type), situation)
        assert all(b["type"] != "actions" for b in blocks)


# --- AC4: never assert safety -----------------------------------------------


def test_card_never_asserts_safety() -> None:
    """No official card composes a safety assertion; it relays status + verify only."""
    situation = _situation(road=_feed("road_closures", (_road_record(status="CLOSED"),)))

    text = _all_text(_need(need_type="is the road safe"), situation).lower()

    assert "safe to travel" not in text
    assert "okay to travel" not in text
    assert "it is safe" not in text
    assert "closed" in text  # the feed's own status, surfaced verbatim
    assert VERIFY_NOTE.lower() in text  # verify note present (guardrail 2)


# --- AC3: degraded-relevant feed renders an explicit unavailable card --------


def test_relevant_but_unavailable_feed_renders_explicit_card() -> None:
    """A feed relevant to the need but available=False -> explicit unavailable card."""
    situation = _situation(
        road=_down_feed("road_closures", "Simulated outage."),
    )

    text = _all_text(_need(need_type="road travel"), situation).lower()

    assert "road_closures" in text  # named
    assert "unavailable" in text  # stated, not dropped
    assert "simulated outage" in text  # the detail carried through


def test_unavailable_feed_irrelevant_to_need_is_not_shown() -> None:
    """A down feed that is NOT relevant to the need is not surfaced (no noise)."""
    situation = _situation(
        road=_down_feed("road_closures", "down"),
        evac=_feed("evac_centres", (_evac_record(),)),
    )

    # A water need is relevant to evac (water point), NOT to road closures.
    text = _all_text(_need(need_type="drinking water"), situation).lower()

    assert "road_closures" not in text  # the down road feed is irrelevant -> not shown
    assert "exmouth recreation centre" in text  # the relevant water card still renders


def test_relevant_feed_available_but_empty_renders_no_card() -> None:
    """A relevant feed that read OK but has no records contributes no card (no empty noise)."""
    situation = _situation(road=_empty_feed("road_closures"))

    blocks = build_official_blocks(_need(need_type="road travel"), situation)

    assert blocks == []  # available + empty + nothing else relevant -> no section


# --- multi-feed need (water touches both evac water point and advice) --------


def test_water_need_can_surface_advice_water_notice_too() -> None:
    """A water need may surface a relevant water/supply advice notice alongside the centre."""
    advice = _advice_record(title="Emergency water point now open — Rec Centre")
    situation = _situation(
        evac=_feed("evac_centres", (_evac_record(),)),
        advice=_feed("official_advice", (advice,)),
    )

    text = _all_text(_need(need_type="drinking water"), situation)

    assert "Exmouth Recreation Centre" in text  # evac water point
    assert "Emergency water point now open" in text  # the water advice notice


# --- Part C: degraded-official whole-path alert (task 034) -------------------
#
# The per-feed "unavailable" card (above) handles ONE down feed. Part C strengthens
# the WHOLE-path case: when EVERY relevant official feed is down — or the situation
# read failed entirely (no snapshot) — the reply must carry an explicit, plain
# user-facing alert ("couldn't reach the official directories — can't give current
# conditions, verify directly"), not silence or an implied-complete answer. Never
# asserts safety; never invents.


def test_alert_text_refuses_safety_and_points_to_verify() -> None:
    """The standing alert says official sources are unreachable + verify; asserts no safety."""
    alert = OFFICIAL_UNAVAILABLE_ALERT.lower()

    assert "official" in alert
    assert "verify" in alert
    # Never asserts safety, never says travel is fine.
    assert "safe to travel" not in alert
    assert "okay to travel" not in alert


def test_is_fully_unavailable_when_all_relevant_feeds_down() -> None:
    """A safety question with every relevant feed down -> official info fully unavailable."""
    situation = _situation(road=_down_feed("road_closures", "Simulated outage."))

    need = _need(need_type="road safety", is_information=True)

    assert is_official_fully_unavailable(need, situation) is True


def test_is_not_fully_unavailable_when_a_relevant_feed_has_records() -> None:
    """If any relevant feed is available with records, official info is NOT fully down."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))

    need = _need(need_type="road safety", is_information=True)

    assert is_official_fully_unavailable(need, situation) is False


def test_is_not_fully_unavailable_when_no_feed_is_relevant() -> None:
    """A need with no relevant feed is not a degraded-official case (it has no official answer)."""
    situation = _situation(road=_down_feed("road_closures", "down"))

    need = _need(need_type="baby formula")  # maps to no official feed

    assert is_official_fully_unavailable(need, situation) is False


def test_all_relevant_feeds_down_renders_explicit_alert_block() -> None:
    """All relevant feeds down -> the official section carries the explicit alert + the down card."""
    situation = _situation(road=_down_feed("road_closures", "Simulated outage."))
    need = _need(need_type="road safety", is_information=True)

    text = _all_text(need, situation)

    assert OFFICIAL_UNAVAILABLE_ALERT in text  # the loud whole-path alert
    assert "road_closures" in text.lower()  # the down feed still named (per-feed card)
    assert "unavailable" in text.lower()


def test_available_feeds_do_not_trigger_the_alert() -> None:
    """A working official section carries NO whole-path alert (only renders when degraded)."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))
    need = _need(need_type="road safety", is_information=True)

    text = _all_text(need, situation)

    assert OFFICIAL_UNAVAILABLE_ALERT not in text
    assert "Minilya-Exmouth Road" in text  # the live card renders normally


def test_build_official_unavailable_blocks_is_loud_and_button_free() -> None:
    """The situation-read-failed builder renders an explicit, button-free alert card."""
    blocks = build_official_unavailable_blocks(_need(need_type="road safety", is_information=True))

    assert blocks, "a wholesale read failure must not render silence"
    types = [b.to_dict()["type"] for b in blocks]
    assert "actions" not in types  # informational only (guardrail 1)
    text = "\n".join(_text_of(b.to_dict()) for b in blocks)
    assert OFFICIAL_UNAVAILABLE_ALERT in text
    assert VERIFY_NOTE in text


def test_build_official_unavailable_blocks_never_asserts_safety() -> None:
    """The wholesale-failure alert never asserts safety and never invents data."""
    text = "\n".join(
        _text_of(b.to_dict())
        for b in build_official_unavailable_blocks(_need(need_type="road safety"))
    ).lower()

    assert "safe to travel" not in text
    assert "okay to travel" not in text
    assert "it is safe" not in text


# --- determinism -------------------------------------------------------------


def test_render_is_deterministic() -> None:
    """The same (need, situation) renders byte-identical blocks (pure function)."""
    situation = _situation(road=_feed("road_closures", (_road_record(),)))
    need = _need(need_type="road travel")

    first = [b.to_dict() for b in build_official_blocks(need, situation)]
    second = [b.to_dict() for b in build_official_blocks(need, situation)]

    assert first == second
