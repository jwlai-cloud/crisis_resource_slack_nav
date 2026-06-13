"""Backfill the in-memory offer index from channel history on startup (task 026).

The coordinator board renders the **in-memory** ``offer_index`` (matching/index.py),
which is populated only by offers the live agent parses as they arrive and is wiped
on every restart (ADR-0003). Seeded offers (``make seed-demo``) and any offer posted
while the agent was down therefore never reach the board — they live only in Slack's
RTS index, which feeds *recall* (the need reply), not the board.

This module sweeps the designated channel's message **history** at startup, parses
each eligible message, and adds every parsed :class:`~entities.Offer` to the index so
prior/seeded offers show as "Open" cases. See
``docs/adr/0006-startup-offer-index-backfill.md`` for the full rationale.

Why history, not RTS: RTS (``assistant.search.context``) is keyword search — it
cannot enumerate a channel's messages, only those matching a query, and it lags. The
bot token already holds ``channels:history``, so ``conversations.history`` is the
complete, immediate, deterministic dump that maps one-to-one onto ``parse_message``'s
inputs. RTS stays the *recall* path; history is the *backfill* path.

Design posture (ADR-0006):

* **Opt-in** via ``BACKFILL_ON_START`` (default off) — the dev file-watcher restarts
  the agent on every ``.py`` save, and an always-on backfill would fire an LLM parse
  per history message on every save (a parse storm). Additionally gated on
  ``CRISIS_CHANNEL`` being set (no channel -> nothing to back-fill).
* **Best-effort, never raises.** A history-fetch failure, or a parse failure on any
  single message, is logged and skipped — backfill is a convenience and must never
  break agent startup or the socket connection.
* **Idempotent.** ``offer_index.add`` overwrites by ``offer.id`` =
  ``deterministic_id(author, source_ts)``, so re-parsing a message the agent later
  also sees live yields the SAME id — no duplicate row. Re-running is safe.
* **Offers only.** The board renders Offers; Needs and chatter are parsed and ignored.
* **Non-blocking.** The sweep runs in a background daemon thread so it never delays
  the socket-mode connection; the board is published once after the sweep so the
  canvas reflects the backfilled cases.
"""

import logging
import os
import threading
from datetime import UTC, datetime

from slack_sdk import WebClient

from agent.parsing import parse_message
from coordinator import update_board
from entities import Offer
from listeners.channel_gate import designated_channel_id
from matching.index import offer_index

logger = logging.getLogger(__name__)

BACKFILL_ON_START_ENV = "BACKFILL_ON_START"

# The history page size. The demo channel holds a modest seed; one page of 100 is
# the complete history. Backfill is a startup convenience, not a paginating crawler.
_DEFAULT_HISTORY_LIMIT = 100

# Truthy spellings for BACKFILL_ON_START (mirrors common bool-env conventions). Read
# at call time, not cached — same env-at-call-time posture as CRISIS_CHANNEL (ADR-0004).
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _event_ts_to_utc(ts: str) -> datetime:
    """Convert a Slack message ``ts`` (string Unix seconds) to an aware-UTC datetime.

    Mirrors :func:`listeners.recall_reply._event_ts_to_utc` (the live-path helper);
    replicated here so the backfill module does not depend on the recall wiring. The
    Need/Offer source-ts validator rejects naive datetimes, so this must stay aware.
    """
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _backfill_enabled() -> bool:
    """Whether ``BACKFILL_ON_START`` is set to a truthy value (read at call time)."""
    return os.environ.get(BACKFILL_ON_START_ENV, "").strip().lower() in _TRUTHY


def backfill_offer_index(
    client: WebClient,
    *,
    channel_id: str,
    user_token: str | None,
    limit: int = _DEFAULT_HISTORY_LIMIT,
) -> int:
    """Sweep ``channel_id``'s recent history, indexing every parsed Offer; return count.

    Fetches up to ``limit`` messages via ``conversations.history`` (the bot token
    already has ``channels:history``), then for each message:

    * skips bot messages (``bot_id``), message subtypes (edits/joins/etc.), and
      messages with no ``text`` or no ``user`` — mirroring ``handle_message``'s
      guards so the agent's own acks and the system join/announce posts are not
      re-parsed as offers;
    * parses the remaining messages with :func:`agent.parsing.parse_message`, each
      wrapped in its own try/except so one bad parse skips only that message;
    * adds every parsed :class:`~entities.Offer` to the module-level
      :data:`~matching.index.offer_index` (Needs and chatter are parsed and ignored).

    Idempotent: ``offer_index.add`` overwrites by deterministic id, so re-running
    over the same history (or seeing a message live after backfilling it) never
    produces a duplicate row.

    Best-effort: a history-fetch failure is logged and yields ``0`` — backfill must
    never raise into agent startup. ``user_token`` is accepted for signature
    stability and as an optional override; the bot client already carries
    ``channels:history``, so the default fetch uses the client's own token.
    """
    try:
        response = client.conversations_history(channel=channel_id, limit=limit)
    except Exception as exc:
        logger.warning("Backfill skipped: conversations.history failed for %s: %s", channel_id, exc)
        return 0

    messages = response.get("messages") or []
    indexed = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        # Mirror handle_message's skip guards: bot posts, subtypes (edits, joins,
        # the agent's own acks come back as bot messages), and message-less events.
        if message.get("bot_id") or message.get("subtype"):
            continue
        text = message.get("text")
        user = message.get("user")
        ts = message.get("ts")
        if not text or not user or not ts:
            continue
        try:
            parsed = parse_message(text, user, _event_ts_to_utc(ts))
        except Exception as exc:
            logger.debug("Backfill skipping message %s (parse failed): %s", ts, exc)
            continue
        if isinstance(parsed, Offer):
            offer_index.add(parsed)
            indexed += 1

    logger.info(
        "Backfill complete for %s: scanned %d message(s), indexed %d offer(s)",
        channel_id,
        len(messages),
        indexed,
    )
    return indexed


def maybe_backfill_on_start(
    client: WebClient,
    *,
    user_token: str | None,
    team_id: str | None = None,
) -> None:
    """Spawn the startup backfill sweep when both gates are open; else no-op (logged).

    Gates (both must be open):

    * ``BACKFILL_ON_START`` is truthy (opt-in — default off, so the dev file-watcher
      restarts never trigger an LLM parse storm); and
    * ``CRISIS_CHANNEL`` is set (:func:`listeners.channel_gate.designated_channel_id`
      returns a channel) — there is nothing to back-fill without a channel.

    When open, a background **daemon** thread runs :func:`backfill_offer_index` over
    that channel and then publishes the board once via
    :func:`coordinator.update_board`, so the canvas reflects the backfilled cases
    (and is no longer republished from an empty index after a restart). The thread is
    a daemon so it never blocks ``SocketModeHandler.start()`` nor delays interpreter
    shutdown.

    Never raises: the gate checks are cheap and the spawned work is best-effort.
    """
    if not _backfill_enabled():
        logger.info("Startup offer-index backfill disabled (%s not set)", BACKFILL_ON_START_ENV)
        return
    channel_id = designated_channel_id()
    if channel_id is None:
        logger.info("Startup offer-index backfill skipped: no CRISIS_CHANNEL configured")
        return

    def _run() -> None:
        backfill_offer_index(client, channel_id=channel_id, user_token=user_token)
        update_board(client, user_token, team_id)

    logger.info("Starting offer-index backfill for %s in the background", channel_id)
    threading.Thread(target=_run, name="offer-index-backfill", daemon=True).start()
