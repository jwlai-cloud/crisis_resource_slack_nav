"""Resolve Slack user ids to display names for the coordinator board — the
*impure* lookup boundary (task 019).

The board markdown (:mod:`coordinator.board`) cannot rely on ``<@id>`` mention
syntax: a Slack **Canvas** renders that literally rather than resolving it to a
name (the live W4 finding). So the board has to substitute real display names
itself. Composition stays pure — it just receives an ``{id: name}`` dict — and
this module is where that dict is built, by calling ``users.info`` for each
distinct id.

**Token.** The lookup authenticates as the acting *user* via slack_sdk's
first-class per-call ``token=`` override — the same lesson the canvas write
learned (:mod:`coordinator.canvas`): a manual ``Authorization`` header does NOT
work for the typed ``users_info`` method (slack_sdk resets Authorization from its
own token after merging custom headers), so the user token must be passed as the
``token=`` kwarg. With no user token the lookup is skipped and an empty map is
returned — the caller falls back to bare ids.

**Best-effort, never raises** (the degraded-state guardrail). Each id is fetched
in isolation: a failed or malformed lookup omits that one id from the map rather
than aborting the rest, and the caller renders the bare id for any id the map
does not cover. A board refresh is never broken by a names lookup.
"""

import logging
from collections.abc import Iterable

from slack_sdk import WebClient

logger = logging.getLogger(__name__)


def _display_name(user: dict[str, object]) -> str | None:
    """Pick the best on-screen name from a ``users.info`` user object.

    Precedence mirrors what Slack shows for an at-mention: the chosen
    ``profile.display_name`` first, then the profile/real name, then the bare
    username. Returns ``None`` when none is set, so the caller omits the id and
    falls back to rendering it raw.
    """
    profile = user.get("profile")
    candidates: list[object] = []
    if isinstance(profile, dict):
        candidates.append(profile.get("display_name"))
        candidates.append(profile.get("real_name"))
    candidates.append(user.get("real_name"))
    candidates.append(user.get("name"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def resolve_display_names(
    client: WebClient, user_token: str | None, user_ids: Iterable[str]
) -> dict[str, str]:
    """Map each distinct user id to its display name, best-effort.

    Issues one ``users.info`` call per distinct id (authenticated as the user via
    the ``token=`` override) and returns ``{id: name}`` for every id that
    resolves. Ids that fail to look up — an API error, a malformed response, or a
    profile with no usable name — are simply absent from the returned map; the
    caller renders the bare id for those. Never raises: a names failure must not
    break the board refresh.

    With no ``user_token`` the lookup is skipped entirely (empty map). De-duped
    internally, so a caller need not pre-dedupe.
    """
    distinct = {uid for uid in user_ids if uid}
    if not distinct or not user_token:
        return {}
    names: dict[str, str] = {}
    for user_id in distinct:
        try:
            response = client.users_info(user=user_id, token=user_token)
            user = response.get("user")
            if not isinstance(user, dict):
                logger.info("users.info for %s returned no user object; using bare id", user_id)
                continue
            name = _display_name(user)
            if name is not None:
                names[user_id] = name
        except Exception as exc:
            # Per-id isolation: one failure must not block the rest, and the
            # caller falls back to the bare id for any id missing from the map.
            logger.info("Display-name lookup for %s failed (using bare id): %s", user_id, exc)
    return names
