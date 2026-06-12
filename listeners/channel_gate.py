"""The single-channel passive-listening gate (task 006 / ADR-0004).

By default the agent is mention-gated everywhere — it answers ``@mentions`` and DMs.
Passive listening (parsing every top-level message and replying to offers/needs) is
expensive: it costs an LLM parse per message and risks bot noise in busy channels.
ADR-0004 confines that posture to **one** designated channel, named by the
``CRISIS_CHANNEL`` env var (a Slack channel id). Empty or unset means the feature is
off — no channel is designated, so passive listening never engages and the pre-006
mention-gated behavior holds everywhere.

The var is read from the environment at call time, not cached: it is cheap (a dict
lookup) and lets an operator widen/narrow the posture by changing config and
restarting, with no code change. Widening to more channels is a future fork with its
own ADR, not a config list — see ADR-0004.
"""

import os

CRISIS_CHANNEL_ENV = "CRISIS_CHANNEL"


def designated_channel_id() -> str | None:
    """Return the configured crisis channel id, or ``None`` when the feature is off.

    Whitespace is trimmed; an empty (or whitespace-only) value reads as off.
    """
    raw = os.environ.get(CRISIS_CHANNEL_ENV, "").strip()
    return raw or None


def is_crisis_channel(channel_id: str | None) -> bool:
    """Whether ``channel_id`` is the one channel where passive listening is enabled.

    ``False`` when the feature is off (unset/empty ``CRISIS_CHANNEL``) or when
    ``channel_id`` is missing or any other channel — so callers can guard the
    passive-listening branch on a single boolean.
    """
    if channel_id is None:
        return False
    return channel_id == designated_channel_id()
