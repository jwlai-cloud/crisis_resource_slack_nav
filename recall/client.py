"""Query the Real-Time Search API for workspace recall — the *plan* step's I/O.

This is the only place the agent talks to ``assistant.search.context``. It is
async because it is I/O-bound (a network round-trip to Slack), per CLAUDE.md's
"async for I/O-bound work". ``slack_sdk``'s ``WebClient`` is synchronous and the
listeners already hand us one on ``AgentDeps``, so we run the blocking call in a
worker thread (``asyncio.to_thread``) rather than reaching for ``AsyncWebClient``
and threading a second client through the deps.

Token: the search runs on behalf of the user via their ``xoxp-`` token
(``deps.user_token``). The bot token the ``WebClient`` is constructed with would
need an ``action_token`` and only reach public channels; the user token is what
the manifest's ``search:read.*`` scopes are granted on. If no user token is
present at runtime we do **not** silently fall back — we return a typed
``RecallError`` so the reply can say workspace search is unavailable (guardrail:
degraded states are explicit).
"""

import asyncio
import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from entities import Need
from recall.models import RecallError, RecallMatch, match_from_message

logger = logging.getLogger(__name__)

_SEARCH_METHOD = "assistant.search.context"

# RTS caps results at 20 per page; one page is plenty for a single need's recall.
_RESULT_LIMIT = 20


def build_query(need: Need) -> str:
    """Build a keyword search string from a Need's structured fields.

    We concatenate ``need_type`` and ``location`` (the relevance + proximity
    signals) and deliberately keep it as plain keywords, not a question — a
    trailing ``?`` or leading "what/how" would trip RTS into semantic mode, which
    requires the Slack-AI-Search plan the sandbox may not have. Formatting is
    stripped because the docs warn it interferes with keyword matching.
    """
    return f"{need.need_type} {need.location}".strip()


async def recall_offers(
    need: Need,
    client: WebClient,
    user_token: str | None,
    team_id: str | None = None,
    bot_user_id: str | None = None,
) -> list[RecallMatch] | RecallError:
    """Search the workspace for prior offers/notices relevant to ``need``.

    Returns a list of typed :class:`RecallMatch` (possibly empty — "no prior
    offers found" is a valid, non-degraded answer the caller renders explicitly)
    or a :class:`RecallError` when the search could not run. Never raises for an
    expected failure and never returns ``None``: the caller branches on the type.
    """
    if not user_token:
        logger.info("RTS recall skipped: no user token (search:read.* unavailable)")
        return RecallError(
            reason="no_user_token",
            detail="No user token available; workspace search requires search:read.* user scopes.",
        )

    query = build_query(need)
    try:
        response = await asyncio.to_thread(
            client.api_call,
            _SEARCH_METHOD,
            params={"query": query, "limit": str(_RESULT_LIMIT)}
            | ({"team_id": team_id} if team_id else {}),
            headers={"Authorization": f"Bearer {user_token}"},
        )
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        logger.warning("RTS recall failed: %s", error)
        return RecallError(reason=error, detail=f"assistant.search.context returned {error}")
    except Exception as exc:
        logger.warning("RTS recall failed: %s", exc)
        return RecallError(reason="request_failed", detail=str(exc))

    messages = response.get("results", {}).get("messages", []) or []
    try:
        matches = [match_from_message(message) for message in messages]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("RTS recall returned an unparseable message: %s", exc)
        return RecallError(reason="malformed_response", detail=str(exc))
    return _drop_agent_noise(matches, bot_user_id)


def _drop_agent_noise(matches: list[RecallMatch], bot_user_id: str | None) -> list[RecallMatch]:
    """Remove agent-directed traffic and duplicate retries from RTS results.

    Messages that mention the bot are requests *to* the agent (needs, retries),
    not offers or notices — surfacing them as "prior offers" echoes the
    requester's own messages back at them. Near-identical retries of the same
    message by the same author collapse to the newest occurrence.
    """
    filtered: list[RecallMatch] = []
    seen: dict[tuple[str, str], int] = {}
    for match in matches:
        if bot_user_id and f"<@{bot_user_id}" in match.text:
            continue
        key = (match.author_id or match.author, " ".join(match.text.split()).lower())
        if key in seen:
            kept = filtered[seen[key]]
            if match.ts > kept.ts:
                filtered[seen[key]] = match
            continue
        seen[key] = len(filtered)
        filtered.append(match)
    return filtered
