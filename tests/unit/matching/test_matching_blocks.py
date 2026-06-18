"""Unit tests for matching.blocks — the informational offer acknowledgement.

Guardrail-focused: the acknowledgement is sourced (offerer) and timestamped, and
carries NO action buttons — logging an offer is informational, not an actionable
match. Composition is pure, so blocks are asserted without a live Slack call.

Task 008 aligns the ack's visual language with the recall cards: it opens with the
same colored-square rank-label cue (``🟩 INDEXED · WORKSPACE MEMORY``), matching
the mock's offer card, while staying button-free.
"""

from collections.abc import Callable

from entities import Offer
from matching.blocks import INDEXED_RANK_LABEL, build_offer_ack_blocks
from recall.blocks import WORKSPACE_BAR_EMOJI


def test_ack_opens_with_indexed_workspace_rank_label(
    make_offer: Callable[..., Offer],
) -> None:
    """The ack opens with the workspace rank-label cue, matching the recall cards/mock."""
    blocks = build_offer_ack_blocks(make_offer())

    first = blocks[0].to_dict()
    assert first["type"] == "context"
    text = " ".join(e["text"] for e in first["elements"])
    assert text == INDEXED_RANK_LABEL
    assert text.startswith(WORKSPACE_BAR_EMOJI)
    assert "INDEXED" in text
    assert "WORKSPACE MEMORY" in text


def test_ack_has_no_action_buttons(make_offer: Callable[..., Offer]) -> None:
    """The acknowledgement is informational — no 'actions' block, ever (guardrail)."""
    blocks = build_offer_ack_blocks(make_offer())

    block_types = [b.to_dict()["type"] for b in blocks]
    assert "actions" not in block_types


def test_ack_is_sourced_and_timestamped(make_offer: Callable[..., Offer]) -> None:
    """A context line carries the offerer and the logged timestamp (sourcing guardrail)."""
    offer = make_offer(offerer="U_JORDAN")

    blocks = build_offer_ack_blocks(offer)

    context_texts = [
        element["text"]
        for block in blocks
        if block.to_dict()["type"] == "context"
        for element in block.to_dict()["elements"]
    ]
    joined = " ".join(context_texts)
    assert "U_JORDAN" in joined
    assert "2026-03-21 09:30 UTC" in joined


def test_ack_confirms_human_in_the_loop(make_offer: Callable[..., Offer]) -> None:
    """The confirmation states nothing happens automatically (bounded autonomy)."""
    blocks = build_offer_ack_blocks(make_offer())

    sections = [b.to_dict() for b in blocks if b.to_dict()["type"] == "section"]
    assert len(sections) == 1
    assert "automatically" in sections[0]["text"]["text"].lower()
