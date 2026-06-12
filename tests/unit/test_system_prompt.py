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
]


@pytest.mark.parametrize(
    ("label", "phrase"),
    GUARDRAIL_ANCHORS,
    ids=[f"{label}: {phrase[:30]}" for label, phrase in GUARDRAIL_ANCHORS],
)
def test_guardrail_phrase_present(label: str, phrase: str) -> None:
    """Each safety guardrail keeps its distinctive anchor phrase in the prompt."""
    assert phrase in SYSTEM_PROMPT, f"Guardrail '{label}' anchor missing: {phrase!r}"


def test_all_four_guardrails_have_anchors() -> None:
    """Sanity check: every guardrail label has at least one anchor in this test."""
    labels = {label for label, _ in GUARDRAIL_ANCHORS}

    assert labels == {
        "human decides",
        "never assert safety",
        "sourced + timestamped",
        "degraded states explicit",
    }


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
