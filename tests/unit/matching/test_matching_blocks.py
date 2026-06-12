"""Unit tests for matching.blocks — the informational offer acknowledgement.

Guardrail-focused: the acknowledgement is sourced (offerer) and timestamped, and
carries NO action buttons — logging an offer is informational, not an actionable
match. Composition is pure, so blocks are asserted without a live Slack call.
"""

from collections.abc import Callable

from entities import Offer
from matching.blocks import build_offer_ack_blocks


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

    section = blocks[0].to_dict()
    assert section["type"] == "section"
    assert "automatically" in section["text"]["text"].lower()
