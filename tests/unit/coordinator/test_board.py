"""Unit tests for coordinator.board — the pure board-markdown composition.

The composer is ``state -> markdown`` with no Slack: these tests pin the contract
the publisher renders. Status grouping, an empty-board state, sourcing on every
case row, and an actor/action/target/when line per audit event are all asserted
against the produced markdown. Guardrails covered: every row carries source +
timestamp; the board reads from the audit trail only (no auto-actions); the verify
note is present and the board never asserts safety.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from coordinator.board import BOARD_TITLE, VERIFY_NOTE, compose_board_markdown
from entities import Offer, Status
from matching.audit import AuditEvent


def test_empty_board_renders_every_heading_and_empty_states() -> None:
    """With no offers and no events, the board still renders every section."""
    markdown = compose_board_markdown([], [])

    assert f"# {BOARD_TITLE}" in markdown
    assert "## Open (0)" in markdown
    assert "## Connected (0)" in markdown
    assert "## Resolved (0)" in markdown
    assert "## Activity log" in markdown
    assert "_No cases yet._" in markdown
    assert "_No actions recorded yet._" in markdown


def test_offers_grouped_by_status_under_their_headings(
    make_offer: Callable[..., Offer],
) -> None:
    """Each offer appears under the heading for its lifecycle status, with a count."""
    open_offer = make_offer(offerer="U_OPEN", resource_type="generator", status=Status.OPEN)
    matched_offer = make_offer(offerer="U_MATCHED", resource_type="water", status=Status.MATCHED)
    resolved_offer = make_offer(offerer="U_DONE", resource_type="fuel", status=Status.RESOLVED)

    markdown = compose_board_markdown([open_offer, matched_offer, resolved_offer], [])

    assert "## Open (1)" in markdown
    assert "## Connected (1)" in markdown
    assert "## Resolved (1)" in markdown
    # Each resource lands under its own status section (order: Open, Connected, Resolved).
    open_pos = markdown.index("## Open (1)")
    connected_pos = markdown.index("## Connected (1)")
    resolved_pos = markdown.index("## Activity log")
    assert open_pos < markdown.index("generator") < connected_pos
    assert connected_pos < markdown.index("water") < resolved_pos
    assert markdown.index("fuel") < resolved_pos


def test_every_case_row_is_sourced_and_timestamped(
    make_offer: Callable[..., Offer],
) -> None:
    """A case row carries offerer (by display name), resource, location, post time."""
    offer = make_offer(
        offerer="U_OFFERER",
        resource_type="generator",
        location="Exmouth",
        source_ts=datetime(2026, 3, 21, 9, 30, tzinfo=UTC),
    )

    markdown = compose_board_markdown([offer], [], names={"U_OFFERER": "Rosario Bennet"})

    assert "*generator*" in markdown
    assert "Exmouth" in markdown
    assert "Rosario Bennet" in markdown
    assert "2026-03-21 09:30 UTC" in markdown


def test_activity_lines_carry_actor_action_target_and_time(
    make_event: Callable[..., AuditEvent],
) -> None:
    """Every audit event renders one line with actor / action verb / target / when."""
    event = make_event(
        actor_id="U_REQUESTER",
        action="connect",
        target="offer:abc-123",
        ts=datetime(2026, 3, 21, 11, 30, tzinfo=UTC),
    )

    markdown = compose_board_markdown([], [event], names={"U_REQUESTER": "Dana Lee"})

    assert "Dana Lee" in markdown
    assert "connected" in markdown
    # No offer for that id is in the list, so the target renders verbatim.
    assert "offer:abc-123" in markdown
    assert "2026-03-21 11:30 UTC" in markdown


def test_action_codes_render_as_human_verbs(
    make_event: Callable[..., AuditEvent],
) -> None:
    """resolve / not_relevant codes render as their human-readable verbs."""
    resolve = make_event(action="resolve", target="offer:1")
    dismiss = make_event(action="not_relevant", target="offer:2")

    markdown = compose_board_markdown([], [resolve, dismiss])

    assert "marked resolved" in markdown
    assert "dismissed" in markdown


def test_unknown_action_code_is_not_dropped(
    make_event: Callable[..., AuditEvent],
) -> None:
    """An unrecognised action code still produces a line (verbatim), never silence."""
    event = make_event(action="escalate", target="offer:9")

    markdown = compose_board_markdown([], [event])

    assert "escalate" in markdown
    assert "offer:9" in markdown


def test_activity_log_renders_newest_first(
    make_event: Callable[..., AuditEvent],
) -> None:
    """Events render most-recent-first even though the trail stores insertion order."""
    first = make_event(actor_id="U_A", action="connect", target="offer:first")
    second = make_event(actor_id="U_B", action="resolve", target="offer:second")

    markdown = compose_board_markdown([], [first, second])

    assert markdown.index("offer:second") < markdown.index("offer:first")


def test_offers_within_a_status_render_newest_first(
    make_offer: Callable[..., Offer],
) -> None:
    """Within a status group the freshest offer is listed first."""
    older = make_offer(
        offerer="U_OLD",
        resource_type="oldresource",
        source_ts=datetime(2026, 3, 21, 8, 0, tzinfo=UTC),
    )
    newer = make_offer(
        offerer="U_NEW",
        resource_type="newresource",
        source_ts=datetime(2026, 3, 21, 10, 0, tzinfo=UTC),
    )

    markdown = compose_board_markdown([older, newer], [])

    assert markdown.index("newresource") < markdown.index("oldresource")


def test_board_carries_verify_note_and_asserts_no_safety(
    make_offer: Callable[..., Offer],
) -> None:
    """The board shows the standing verify note and never asserts safety."""
    offer = make_offer()

    markdown = compose_board_markdown([offer], [])

    assert VERIFY_NOTE in markdown
    lowered = markdown.lower()
    assert "is safe" not in lowered
    assert "safe to travel" not in lowered
    assert "okay to" not in lowered


def test_resolved_offer_does_not_appear_under_open(
    make_offer: Callable[..., Offer],
) -> None:
    """A resolved offer is grouped under Resolved only — Open stays empty."""
    resolved = make_offer(resource_type="generator", status=Status.RESOLVED)

    markdown = compose_board_markdown([resolved], [])

    open_section = markdown.split("## Connected")[0]
    assert "_No cases yet._" in open_section
    assert "generator" not in open_section
    assert "## Resolved (1)" in markdown


def test_output_ends_with_single_trailing_newline(
    make_offer: Callable[..., Offer],
) -> None:
    """The composed document is a clean markdown string ending in one newline."""
    markdown = compose_board_markdown([make_offer()], [])

    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")


# --- Display-name resolution on case rows (task 019) -------------------------


def test_case_row_renders_display_name_when_resolved(
    make_offer: Callable[..., Offer],
) -> None:
    """When a name is known for the offerer, the row shows it (not the raw id)."""
    offer = make_offer(offerer="U_ROSARIO", resource_type="camp beds")

    markdown = compose_board_markdown([offer], [], names={"U_ROSARIO": "Rosario Bennet"})

    assert "Rosario Bennet" in markdown
    # The raw mention syntax (which the canvas does not resolve) is gone.
    assert "<@U_ROSARIO>" not in markdown
    assert "U_ROSARIO" not in markdown


def test_case_row_falls_back_to_bare_id_when_name_unknown(
    make_offer: Callable[..., Offer],
) -> None:
    """An unresolved offerer renders the bare id — never a crash, never empty."""
    offer = make_offer(offerer="U_UNKNOWN", resource_type="generator")

    markdown = compose_board_markdown([offer], [], names={})

    assert "U_UNKNOWN" in markdown


def test_names_param_is_optional_and_defaults_to_bare_ids(
    make_offer: Callable[..., Offer],
) -> None:
    """With no names dict the composer stays pure and shows bare ids."""
    offer = make_offer(offerer="U_NONAME")

    markdown = compose_board_markdown([offer], [])

    assert "U_NONAME" in markdown


# --- Audit-target humanization on activity lines (task 019) ------------------


def test_activity_line_humanizes_offer_target_to_resource(
    make_offer: Callable[..., Offer],
    make_event: Callable[..., AuditEvent],
) -> None:
    """An offer:<uuid> target resolves to the offer's resource_type via the offers list."""
    offer = make_offer(resource_type="camp beds")
    event = make_event(action="connect", target=f"offer:{offer.id}")

    markdown = compose_board_markdown([offer], [event])

    assert "camp beds" in markdown
    # The internal uuid is no longer surfaced raw in the activity log.
    assert str(offer.id) not in markdown


def test_activity_line_falls_back_to_bare_target_when_offer_absent(
    make_event: Callable[..., AuditEvent],
) -> None:
    """An offer:<uuid> target whose offer is not in the list renders verbatim."""
    event = make_event(action="connect", target="offer:not-in-index")

    markdown = compose_board_markdown([], [event])

    assert "offer:not-in-index" in markdown


def test_activity_line_resolves_offerer_target_to_name(
    make_event: Callable[..., AuditEvent],
) -> None:
    """An offerer:<id> target resolves to the offerer's name via the names dict."""
    event = make_event(action="connect", target="offerer:U_ROSARIO")

    markdown = compose_board_markdown([], [event], names={"U_ROSARIO": "Rosario Bennet"})

    assert "Rosario Bennet" in markdown
    assert "U_ROSARIO" not in markdown


def test_activity_line_offerer_target_falls_back_to_bare_id(
    make_event: Callable[..., AuditEvent],
) -> None:
    """An offerer:<id> target with no resolved name shows the bare id."""
    event = make_event(action="connect", target="offerer:U_UNKNOWN")

    markdown = compose_board_markdown([], [event], names={})

    assert "U_UNKNOWN" in markdown


def test_activity_line_actor_renders_display_name(
    make_event: Callable[..., AuditEvent],
) -> None:
    """The acting human renders by display name when resolved (not the raw id)."""
    event = make_event(actor_id="U_ACTOR", action="connect", target="offer:x")

    markdown = compose_board_markdown([], [event], names={"U_ACTOR": "Dana Lee"})

    assert "Dana Lee" in markdown
    assert "<@U_ACTOR>" not in markdown
