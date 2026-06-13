"""Bounded-autonomy action-button handlers — Connect / Mark resolved / Dismiss.

This is where guardrail 1 ("the agent surfaces and ranks; a human decides")
becomes real UI. Each handler is wired to one ``action_id`` rendered by
``recall.blocks``:

* ``crisis_connect`` — the human confirms a match. Opens a conversation that
  includes the requester (the clicker) *and* the offerer, posts a short sourced
  intro, marks the index offer ``MATCHED``, and swaps the card's Connect button for
  a "Mark resolved" button. Falls back to a DM with the offerer (mentioning the
  requester) when a group DM cannot be opened — never going silent.
* ``crisis_resolve`` — the human marks the match done. Marks the index offer
  ``RESOLVED`` (so it stops matching, 004 behaviour), flips the card to a Resolved
  state, and posts a brief threaded confirmation.
* ``crisis_not_relevant`` — the human dismisses the match. Mutes the card's button
  row to a "Dismissed" state and records the signal.

Every handler ``ack()``s immediately, then does its work, and **every** failure
path posts a visible, explicit message rather than failing silently (the degraded
guardrail). Nothing here ever acts on its own — a handler only ever does what the
click asked. Every action appends to the in-memory audit trail.
"""

from logging import Logger
from uuid import UUID

from slack_bolt import Ack, BoltContext
from slack_sdk import WebClient

from agent.deps import resolve_user_token
from coordinator import update_board
from entities import Offer, Status
from matching import audit_trail, offer_index
from recall import ACTION_CONNECT, ACTION_NOT_RELEVANT, ACTION_RESOLVE, ConnectPayload
from recall.dismissals import dismissal_store, match_identity

# Audit action labels (kept distinct from the Slack action_ids so the trail reads
# as plain verbs).
_AUDIT_CONNECT = "connect"
_AUDIT_RESOLVE = "resolve"
_AUDIT_NOT_RELEVANT = "not_relevant"

_RESOLVE_LABEL = ":white_check_mark: Connected — Mark resolved"
_RESOLVED_NOTE = ":white_check_mark: Resolved — this offer is now closed and won't match again."
_DISMISSED_NOTE = ":heavy_multiplication_x: Dismissed for this request."

_PARSE_FAIL = (
    ":warning: I couldn't read this match's details, so I didn't do anything. "
    "Nothing was changed — please try again from a fresh result."
)


def _channel_and_ts(body: dict) -> tuple[str | None, str | None]:
    """The channel id and message ts the clicked card lives in (for chat_update)."""
    channel = (body.get("channel") or {}).get("id")
    ts = (body.get("message") or {}).get("ts")
    return channel, ts


def _parse_payload(body: dict, client: WebClient, logger: Logger) -> ConnectPayload | None:
    """Parse the clicked button's value, or post an explicit failure and return None.

    A malformed value is a degraded state, not a silent no-op: we post an ephemeral
    "couldn't read this match" to the clicker so they know nothing happened.
    """
    try:
        value = body["actions"][0]["value"]
        return ConnectPayload.from_value(value)
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("Could not parse button payload: %s", exc)
        channel, _ = _channel_and_ts(body)
        user = (body.get("user") or {}).get("id")
        if channel and user:
            client.chat_postEphemeral(channel=channel, user=user, text=_PARSE_FAIL)
        return None


def _replace_action_row(blocks: list[dict], block_id: str, replacement: dict) -> list[dict]:
    """Return ``blocks`` with the action row whose id is ``block_id`` swapped out.

    Used to flip a card's button row after a click (Connect -> Mark resolved, or
    -> a muted Dismissed/Resolved context line). Blocks arrive from Slack as raw
    dicts (``body["message"]["blocks"]``); we rewrite the one matching row and
    leave the rest — and every other match's row — untouched.
    """
    return [replacement if block.get("block_id") == block_id else block for block in blocks]


def _resolve_button_block(block_id: str, value: str) -> dict:
    """The post-connect action row: a single Mark-resolved button (same payload)."""
    return {
        "type": "actions",
        "block_id": block_id,
        "elements": [
            {
                "type": "button",
                "action_id": ACTION_RESOLVE,
                "text": {"type": "plain_text", "text": _RESOLVE_LABEL, "emoji": True},
                "value": value,
                "style": "primary",
            }
        ],
    }


def _muted_context_block(block_id: str, note: str) -> dict:
    """A muted context line replacing a card's buttons (Resolved / Dismissed state)."""
    return {
        "type": "context",
        "block_id": block_id,
        "elements": [{"type": "mrkdwn", "text": note}],
    }


def _update_card(body: dict, client: WebClient, logger: Logger, new_block: dict) -> None:
    """Rewrite the clicked card's action row in place via chat_update.

    Best-effort: if the update can't be applied (e.g. the message is gone), the
    handler's separately-posted confirmation/intro still stands, so the human is
    never left without feedback. We log rather than raise.
    """
    channel, ts = _channel_and_ts(body)
    blocks = (body.get("message") or {}).get("blocks")
    block_id = body["actions"][0].get("block_id")
    if not (channel and ts and blocks and block_id):
        logger.warning("Cannot update card: missing channel/ts/blocks/block_id")
        return
    updated = _replace_action_row(blocks, block_id, new_block)
    try:
        client.chat_update(channel=channel, ts=ts, blocks=updated, text="Match updated")
    except Exception as exc:
        logger.warning("Card update failed (confirmation still posted): %s", exc)


def _offer_target(payload: ConnectPayload) -> str:
    """Audit target string for a payload (offer id when present, else the offerer)."""
    return f"offer:{payload.offer_id}" if payload.offer_id else f"offerer:{payload.offerer_id}"


def _mark_offer(payload: ConnectPayload, status: Status, logger: Logger) -> Offer | None:
    """Transition the index offer to ``status`` when the payload carries a valid id.

    A no-op (returns ``None``) when there is no offer id (an RTS-only match has none)
    or the id is malformed — a bad id is logged and skipped rather than raised, so a
    handler that has already opened a conversation never crashes half-done.
    """
    if not payload.offer_id:
        return None
    try:
        offer_id = UUID(payload.offer_id)
    except ValueError:
        logger.warning("Skipping index update: malformed offer id %r", payload.offer_id)
        return None
    if status is Status.MATCHED:
        return offer_index.mark_matched(offer_id)
    return offer_index.mark_resolved(offer_id)


def _intro_text(requester: str, payload: ConnectPayload) -> str:
    """A short, sourced connect intro — names both parties, cites the offer, never asserts safety."""
    snippet = payload.snippet.strip() or "their offer"
    source = f" (<{payload.permalink}|original message>)" if payload.permalink else ""
    return (
        f"Connecting <@{requester}> and <@{payload.offerer_id}>. "
        f"<@{requester}> is looking for help; <@{payload.offerer_id}> offered: "
        f"{snippet}{source}. Sort the details out together and verify anything "
        f"before relying on it — I just made the introduction."
    )


def handle_crisis_connect(
    ack: Ack, body: dict, client: WebClient, context: BoltContext, logger: Logger
) -> None:
    """Connect the requester (clicker) and the offerer; flip the card to Mark resolved.

    Opens a group DM with both users and posts a sourced intro. Falls back to a DM
    with the offerer (mentioning the requester) if a group DM can't be opened.
    Marks the index offer MATCHED when an offer id is present. Never auto-acts: it
    only introduces the two people the human chose to connect.
    """
    ack()
    payload = _parse_payload(body, client, logger)
    if payload is None:
        return

    requester = (body.get("user") or {}).get("id", "")
    offerer = payload.offerer_id

    # Double-click guard: an index-backed offer that is already MATCHED/RESOLVED
    # means this card was connected before — don't open a second DM.
    if payload.offer_id:
        try:
            guard_id = UUID(payload.offer_id)
        except ValueError:
            guard_id = None
        existing = offer_index.lookup(guard_id) if guard_id else None
        if existing is not None and existing.status is not Status.OPEN:
            channel, _ = _channel_and_ts(body)
            if channel and requester:
                client.chat_postEphemeral(
                    channel=channel,
                    user=requester,
                    text=(
                        f"This offer is already {existing.status.value} — "
                        "no new introduction was sent."
                    ),
                )
            return

    audit_trail.record(actor_id=requester, action=_AUDIT_CONNECT, target=_offer_target(payload))

    intro = _intro_text(requester, payload)
    try:
        opened = client.conversations_open(users=f"{requester},{offerer}")
        dm_channel = opened["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text=intro)
    except Exception as exc:
        logger.warning("Group DM unavailable, falling back to offerer DM: %s", exc)
        try:
            opened = client.conversations_open(users=offerer)
            dm_channel = opened["channel"]["id"]
            client.chat_postMessage(channel=dm_channel, text=intro)
        except Exception as fallback_exc:
            logger.warning("Offerer DM also failed: %s", fallback_exc)
            channel, _ = _channel_and_ts(body)
            if channel and requester:
                client.chat_postEphemeral(
                    channel=channel,
                    user=requester,
                    text=(
                        ":warning: I couldn't open a message with "
                        f"<@{offerer}> right now. Nothing was sent — you can "
                        "reach them directly while I retry later."
                    ),
                )
            return

    # Confirmed match: mark the index offer MATCHED (no-op if it's an RTS-only hit).
    _mark_offer(payload, Status.MATCHED, logger)

    block_id = body["actions"][0].get("block_id", "")
    _update_card(body, client, logger, _resolve_button_block(block_id, payload.to_value()))

    # Refresh the coordinator board last — best-effort, already isolated inside
    # update_board (never raises), so a Canvas hiccup cannot undo the connection.
    update_board(client, resolve_user_token(context.user_token), context.team_id)


def handle_crisis_resolve(
    ack: Ack, body: dict, client: WebClient, context: BoltContext, logger: Logger
) -> None:
    """Mark a connected match resolved; flip the card to a Resolved state.

    Marks the index offer RESOLVED when an offer id is present (so it stops matching
    future needs — 004 behaviour, now reachable from the UI), mutes the card's
    button row to a Resolved note, and posts a brief threaded confirmation.
    """
    ack()
    payload = _parse_payload(body, client, logger)
    if payload is None:
        return

    actor = (body.get("user") or {}).get("id", "")
    audit_trail.record(actor_id=actor, action=_AUDIT_RESOLVE, target=_offer_target(payload))

    _mark_offer(payload, Status.RESOLVED, logger)

    block_id = body["actions"][0].get("block_id", "")
    _update_card(body, client, logger, _muted_context_block(block_id, _RESOLVED_NOTE))

    channel, ts = _channel_and_ts(body)
    if channel and ts:
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f":white_check_mark: <@{actor}> marked this match resolved.",
        )

    # Refresh the coordinator board last — best-effort (update_board never raises).
    update_board(client, resolve_user_token(context.user_token), context.team_id)


def handle_crisis_not_relevant(
    ack: Ack, body: dict, client: WebClient, context: BoltContext, logger: Logger
) -> None:
    """Dismiss a match: mute its button row, audit it, and remember the dismissal.

    No connection, no index change — dismissing is just the human saying "not this
    one". The card's buttons collapse to a muted Dismissed note so it's clear the
    action registered (never a silent click), the signal is audited, and the
    dismissal is recorded per-user in the :data:`dismissal_store` (task 015) keyed
    on the match identity (offer id -> permalink -> snippet-text hash). A later
    need from the *same* requester then filters this match out instead of
    resurfacing it with fresh buttons.
    """
    ack()
    payload = _parse_payload(body, client, logger)
    if payload is None:
        return

    actor = (body.get("user") or {}).get("id", "")
    audit_trail.record(actor_id=actor, action=_AUDIT_NOT_RELEVANT, target=_offer_target(payload))
    identity = match_identity(
        offer_id=payload.offer_id, permalink=payload.permalink, text=payload.snippet
    )
    dismissal_store.dismiss(actor, identity)
    logger.info("Match dismissed by %s: %s", actor, _offer_target(payload))

    block_id = body["actions"][0].get("block_id", "")
    _update_card(body, client, logger, _muted_context_block(block_id, _DISMISSED_NOTE))

    # Refresh the coordinator board last — the dismissal is a human-confirmed action
    # the activity log records. Best-effort (update_board never raises).
    update_board(client, resolve_user_token(context.user_token), context.team_id)


# Registered action_ids, exported so the package registrar wires the right handler
# to the right id (and tests can assert the wiring without a live App).
CRISIS_ACTIONS = {
    ACTION_CONNECT: handle_crisis_connect,
    ACTION_RESOLVE: handle_crisis_resolve,
    ACTION_NOT_RELEVANT: handle_crisis_not_relevant,
}
