"""Regression anchors for the Crisis Resource Navigator system prompt.

The system prompt is version-controlled product code: the four safety guardrails
from CLAUDE.md live inside it. These tests pin a stable, distinctive phrase for
each guardrail (and for the parse->plan->rank->compose loop) so that any future
edit which drops a guardrail fails CI instead of silently shipping.
"""

import pytest

from agent.agent import SYSTEM_PROMPT

# Each entry: (guardrail label, distinctive phrase that MUST stay in the prompt).
GUARDRAIL_ANCHORS = [
    # A human decides; the agent only surfaces and ranks, never auto-acts.
    ("human decides", "surface and rank options — a human decides"),
    ("human decides", "confirmation step"),
    # Never assert safety; always include the verify framing.
    ("never assert safety", "Never assert safety."),
    ("never assert safety", "verify before relying on this"),
    # Every item is sourced and timestamped.
    ("sourced + timestamped", "Every item you surface carries a source and a timestamp."),
    ("sourced + timestamped", "feed / fetched-at"),
    # Degraded states are explicit; no silent skips, no fabrication.
    ("degraded states explicit", "Degraded states are explicit."),
    ("degraded states explicit", "Never silently skip a source"),
    # No placeholder / invented attributions: if a value is unknown, omit the claim.
    ("no placeholders", "Never emit placeholder text"),
    ("no placeholders", "[timestamp]"),
    ("no placeholders", "If a value is unknown, omit the claim"),
]


@pytest.mark.parametrize(
    ("label", "phrase"),
    GUARDRAIL_ANCHORS,
    ids=[f"{label}: {phrase[:30]}" for label, phrase in GUARDRAIL_ANCHORS],
)
def test_guardrail_phrase_present(label: str, phrase: str) -> None:
    """Each safety guardrail keeps its distinctive anchor phrase in the prompt."""
    assert phrase in SYSTEM_PROMPT, f"Guardrail '{label}' anchor missing: {phrase!r}"


FOUR_GUARDRAILS = {
    "human decides",
    "never assert safety",
    "sourced + timestamped",
    "degraded states explicit",
}


def test_all_four_guardrails_have_anchors() -> None:
    """Sanity check: each of the four core guardrails has at least one anchor here."""
    labels = {label for label, _ in GUARDRAIL_ANCHORS}

    assert labels >= FOUR_GUARDRAILS


def test_no_placeholder_rule_is_anchored() -> None:
    """The no-placeholder / no-invented-attribution rule is pinned in the prompt.

    Born from live UX feedback (task 005): blind to the real recall results, the
    model invented sources like "posted [timestamp]" with a literal placeholder.
    The prompt must forbid emitting placeholder text and require omitting any
    claim whose value is unknown. The structured recall blocks are the
    authoritative source display, so the prose must not restate full source lines.
    """
    assert "Never emit placeholder text" in SYSTEM_PROMPT
    assert "[timestamp]" in SYSTEM_PROMPT
    assert "If a value is unknown, omit the claim" in SYSTEM_PROMPT
    # The prose composes around the structured matches, not re-printing sources.
    assert "do not restate the full source line" in SYSTEM_PROMPT


def test_prompt_enforces_parse_plan_rank_compose_loop() -> None:
    """The prompt names the loop and its four structured parse fields."""
    assert "parse → plan → rank → compose" in SYSTEM_PROMPT
    for field in ("need_type", "location", "urgency", "household_size"):
        assert field in SYSTEM_PROMPT, f"Structured parse field missing: {field}"


def test_prompt_drops_template_humor_persona() -> None:
    """The crisis persona replaces the template's witty/humor instructions."""
    assert "witty" not in SYSTEM_PROMPT
    assert "no humor" in SYSTEM_PROMPT or "no jokes" in SYSTEM_PROMPT


def test_prompt_retains_emoji_reaction_and_mcp_sections() -> None:
    """Emoji-reaction tool instruction and the Slack MCP capability section persist."""
    assert "add_emoji_reaction" in SYSTEM_PROMPT
    assert "SLACK MCP SERVER" in SYSTEM_PROMPT


# Each entry: (label, distinctive phrase the OFFICIAL DIRECTORIES section must keep).
OFFICIAL_DIRECTORY_ANCHORS = [
    # The section exists and names itself.
    ("section header", "OFFICIAL DIRECTORIES"),
    # The model is told about each of the three official-directory tools by name.
    ("road tool", "get_road_closures"),
    ("evac tool", "get_evac_centres"),
    ("advice tool", "get_official_advice"),
    # Every surfaced official item carries feed + fetched-at + verify note (guardrail 3).
    # Task 028: the items render as cards; the prompt defers the specifics to them.
    ("feed + fetched-at", "feed name and a `fetched_at` timestamp"),
    ("verify note", "verify before relying on this"),
    ("defer to cards", "DEFER the official specifics to those cards"),
    ("no prose re-list", "do not re-list the closures, centres, or water points in your prose"),
    # A feed error is stated by name, never silently skipped (guardrail 4).
    ("degraded by name", "name the feed that could not"),
    ("no invented feeds", "never invent or\n  guess closures, centres, or advice"),
    # Relevance pruning (task 012): include only need-relevant official items —
    # prune by relevance, never by hiding.
    ("prune by relevance", "only the official items DIRECTLY relevant to the parsed need"),
    ("water -> water point", "supply need\n  surfaces the water point(s)"),
    ("travel -> closures", "surfaces the relevant closure(s)"),
    ("shelter -> evac", "shelter or somewhere-to-stay need\n  surfaces the evacuation centre(s)"),
    # Pruning never hides a degraded feed or weakens never-assert-safety.
    ("prune not hide", "Prune by relevance, never by hiding"),
    # Task 028: a road/travel SAFETY question leads with an explicit refusal.
    ("safety refusal lead", "can't tell them whether it is safe"),
    ("safety section", "SAFETY QUESTIONS"),
    # The refusal does NOT over-apply to plain where/what info needs.
    ("refusal scoped", "ONLY for road/travel SAFETY questions"),
]


@pytest.mark.parametrize(
    ("label", "phrase"),
    OFFICIAL_DIRECTORY_ANCHORS,
    ids=[f"{label}: {phrase[:30]}" for label, phrase in OFFICIAL_DIRECTORY_ANCHORS],
)
def test_official_directories_section_anchored(label: str, phrase: str) -> None:
    """The OFFICIAL DIRECTORIES section keeps its tool names + sourcing anchors."""
    assert phrase in SYSTEM_PROMPT, f"Official-directories anchor '{label}' missing: {phrase!r}"


def test_official_directories_names_all_three_tools() -> None:
    """The prompt advertises all three mock MCP tools so the model knows they exist."""
    for tool in ("get_road_closures", "get_evac_centres", "get_official_advice"):
        assert tool in SYSTEM_PROMPT, f"Official-directory tool not advertised: {tool}"


def test_official_items_relevance_pruning_is_anchored() -> None:
    """The need-relevance pruning rule is pinned in the prompt (task 012/028).

    Born from a live finding (task 009): a need reply dumped the FULL official
    picture (every closure + water point + all evac centres) at one resident.
    The prompt must tell the model to include only official items DIRECTLY
    relevant to the parsed need, mapped per need type — and to prune by relevance,
    never by hiding, so a degraded feed is still named (guardrail 4) and safety is
    never asserted (guardrail 2). Task 028 moved the official *display* to
    deterministic cards, so the prose-brevity cap is gone; the relevance map and
    the prune-not-hide rule stay.
    """
    # Only need-relevant official items, mapped by need type (line-wrap-insensitive).
    assert "only the official items DIRECTLY relevant to the parsed need" in SYSTEM_PROMPT
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "supply need surfaces the water point(s)" in normalized
    assert "surfaces the relevant closure(s)" in normalized
    assert "shelter or somewhere-to-stay need surfaces the evacuation" in normalized
    # Pruning must not weaken guardrails 2 and 4: prune by relevance, not by hiding.
    assert "Prune by relevance, never by hiding" in SYSTEM_PROMPT


def test_official_display_defers_to_cards() -> None:
    """Task 028: the prompt defers official specifics to the rendered cards (no prose dump).

    The official items now render as deterministic, sourced cards beneath the reply
    (recall.official_blocks). The prompt must tell the model to DEFER the official
    specifics to those cards rather than re-listing closures/centres/water points in
    prose — closing the prose-duplication gap (ADR-0007). The plan-step consult and
    the degraded-by-name honesty must remain.
    """
    assert "DEFER the official specifics to those cards" in SYSTEM_PROMPT
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "do not re-list the closures, centres, or water points in your prose" in normalized
    # Plan-step consult retained.
    assert "State in your plan which" in SYSTEM_PROMPT
    # Degraded-by-name honesty retained (guardrail 4).
    assert "name the feed that could not" in SYSTEM_PROMPT


def test_road_safety_question_leads_with_explicit_refusal() -> None:
    """Task 028: a road/travel SAFETY question leads with an explicit can't-judge refusal.

    Verified live (2026-06-13): the guardrail-compliant answer surfaced the closure
    + verify note but omitted the explicit "I can't tell you whether it's safe — I
    don't make that call" lead the demo shows. The prompt now pins that lead — scoped
    to road/travel SAFETY questions, NOT plain where/what/status info needs.
    """
    assert "SAFETY QUESTIONS" in SYSTEM_PROMPT
    assert "can't tell them whether it is safe" in SYSTEM_PROMPT
    assert "do not make safety calls" in SYSTEM_PROMPT or "don't make safety calls" in SYSTEM_PROMPT
    # Scoped: must NOT over-apply to a plain information need.
    assert "ONLY for road/travel SAFETY questions" in SYSTEM_PROMPT
