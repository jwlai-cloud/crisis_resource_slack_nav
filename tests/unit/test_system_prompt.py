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
