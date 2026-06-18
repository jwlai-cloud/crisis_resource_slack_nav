"""Pin the coordinator board to a channel bookmark — a persistent quick link (task 023).

The board link otherwise lives only in the one announce message
(:mod:`coordinator.announce`), which scrolls away. A channel *bookmark* sits in
the top-of-channel bar: always visible, one click, never scrolls. This module
adds (or updates in place) a single ``"Community Cases board"`` bookmark in
``COORDINATOR_CHANNEL`` pointing at the board canvas, hooked into the same
canvas-create path as the announce.

``COORDINATOR_CHANNEL`` is the same env switch the announce reads (see
:mod:`coordinator.announce`): empty or unset means **off** and nothing is added.
One channel only.

**Idempotent by construction.** A board create/recreate calls this each time, so
it must not pile up duplicate bookmarks. It lists the channel's bookmarks first;
if one already carries the board title it ``bookmarks_edit``-s that bookmark to
the new url, otherwise it ``bookmarks_add``-s a fresh one. A re-run therefore
edits in place rather than duplicating.

**Best-effort, never raises.** Any failure (missing scope, channel not found, no
bot membership, API outage) is logged and swallowed — the quick link is a
convenience layered on top of the board, and a bookmark failure must never break
the canvas create it is hooked into (the same degraded-state posture as
:func:`coordinator.announce.announce_board` and the Canvas API calls themselves).

**Token.** A channel bookmark is written via ``bookmarks:write``. The write uses
the per-call ``user_token`` override when given — the standalone ``make board``
process carries only the user token (``slack run`` injects the bot token into the
agent, not the script), so the bookmark must authenticate with that same user
token there, exactly like the announce. When ``user_token`` is omitted the
client's own (bot) token is used — the natural owner of a channel bookmark in the
live agent. The ``token=`` kwarg is slack_sdk's first-class override (it flows
through ``api_call`` to token resolution); a manual ``Authorization`` header does
NOT work, the same lesson the canvas write records.
"""

import logging

from slack_sdk import WebClient

from coordinator.announce import COORDINATOR_CHANNEL_ENV, coordinator_channel_id

logger = logging.getLogger(__name__)

# The single bookmark this module owns. Idempotency keys off this exact title:
# a board create/recreate edits the bookmark with this title rather than adding
# a duplicate. The emoji rides in the title text (the bookmark bar renders it).
BOOKMARK_TITLE = "\U0001f4cb Community Cases board"


def _find_board_bookmark_id(
    client: WebClient, channel: str, token_kwargs: dict[str, str]
) -> str | None:
    """Return the id of the existing board bookmark in ``channel``, or ``None``.

    Lists the channel's bookmarks and matches on :data:`BOOKMARK_TITLE` — the
    key the upsert is idempotent on. Returns the first match's id; ``None`` when
    no bookmark carries the board title yet (the add path).
    """
    response = client.bookmarks_list(channel_id=channel, **token_kwargs)
    bookmarks = response.get("bookmarks") or []
    for entry in bookmarks:
        if entry.get("title") == BOOKMARK_TITLE:
            entry_id = entry.get("id")
            # A title-matching entry with no id is malformed; skip it rather than
            # KeyError. The upsert then falls through to the add path.
            if entry_id:
                return str(entry_id)
    return None


def upsert_board_bookmark(
    client: WebClient, *, link: str | None, user_token: str | None = None
) -> None:
    """Add or update the board's channel bookmark in ``COORDINATOR_CHANNEL``.

    A no-op when ``COORDINATOR_CHANNEL`` is off or when ``link`` is ``None`` (no
    team id upstream means no canvas deep link to point at — a bookmark with no
    url is useless). Otherwise lists the channel's bookmarks: edits the existing
    ``"Community Cases board"`` bookmark to ``link`` if present, else adds a new
    one. Idempotent — a re-run edits in place, never duplicates.

    Authenticates with the per-call ``user_token`` override when given, else the
    client's own token. Best-effort: any failure is logged and swallowed, never
    raised, so a bookmark problem can never break the canvas create that calls
    this.
    """
    channel = coordinator_channel_id()
    if channel is None:
        logger.info("Coordinator board bookmark skipped: %s not set", COORDINATOR_CHANNEL_ENV)
        return
    if link is None:
        logger.info("Coordinator board bookmark skipped: no canvas link to point at")
        return

    token_kwargs = {"token": user_token} if user_token else {}
    try:
        existing_id = _find_board_bookmark_id(client, channel, token_kwargs)
        if existing_id is not None:
            client.bookmarks_edit(
                bookmark_id=existing_id,
                channel_id=channel,
                link=link,
                title=BOOKMARK_TITLE,
                **token_kwargs,
            )
            logger.info("Updated coordinator board bookmark %s in %s", existing_id, channel)
        else:
            client.bookmarks_add(
                channel_id=channel,
                title=BOOKMARK_TITLE,
                type="link",
                link=link,
                **token_kwargs,
            )
            logger.info("Added coordinator board bookmark to %s", channel)
    except Exception as exc:
        logger.warning("Coordinator board bookmark failed (board unaffected): %s", exc)
