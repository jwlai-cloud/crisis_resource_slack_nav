"""Seed the Cyclone Narelle / Exmouth scenario into the demo workspace (task 013).

Before recording the demo (or showing judges a live workspace) the crisis channel
needs to read like a real mutual-aid operation: a handful of believable offers, a
coordinator notice or two, and some community chatter for the "before" scroll. This
one-shot posts exactly that into ``CRISIS_CHANNEL``.

    uv run python -m scripts.seed_demo            # seed (idempotent)
    uv run python -m scripts.seed_demo --fresh    # wipe prior seed, then re-seed clean

How it posts (live-verified, 2026-06-13)
----------------------------------------
Messages are posted with the **user token** (``SLACK_USER_TOKEN``) as slack_sdk's
per-call ``token=`` override on the bot-token WebClient — the same override the
coordinator board uses (see ``coordinator/canvas.py``; a manual ``Authorization``
header is silently reset by slack_sdk for typed methods, so ``token=`` is the path
that works). Two live-verified consequences the demo relies on:

- **RTS indexing lag (~1 minute).** Real-Time Search picks up these posts about a
  minute after they land — so seed, wait ~60s, *then* post a need and the seeded
  offers will match. Seeding immediately before hitting "record" will look empty.
- **Operator attribution.** Every seeded message is attributed to the acting user
  (the operator), not to the named personas in the text — there are no persona
  tokens, and ``chat:write.customize`` posts are bot-authored and get dropped by
  the recall noise filter, so they would not match. The narration still works: the
  offer text names the offerer ("Jo at North Exmouth"); attribution is cosmetic.

Idempotency
-----------
Every seeded message is tagged with a trailing :data:`SEED_MARKER` suffix
(``·crn-seed`` — a middle dot + literal tag, inert on screen). A run scans the
channel's recent history for that marker, skips any scenario message already
present, and posts only the rest — so running twice never duplicates. ``--fresh``
first deletes every marker-bearing message (and only those — ordinary chatter is
never touched) for a clean re-seed before recording.

Requires ``SLACK_USER_TOKEN`` (user token; ``chat:write`` + ``channels:history``)
and ``CRISIS_CHANNEL`` (the channel id to seed into) in ``.env`` or the environment
— see ``.env.example``. ``SLACK_BOT_TOKEN`` carries the WebClient; the user token
overrides auth per call.
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Literal

# Bootstrap logging at module level, before any project import (CLAUDE.md
# "Entry-point scripts call the logging bootstrap at module level").
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv  # noqa: E402
from slack_sdk import WebClient  # noqa: E402
from slack_sdk.errors import SlackApiError  # noqa: E402

from agent.deps import resolve_user_token  # noqa: E402
from listeners.channel_gate import designated_channel_id  # noqa: E402

logger = logging.getLogger(__name__)

# Trailing tag on every seeded message. A middle dot keeps it visually inert in the
# channel (it reads as stray punctuation, not a hashtag) while staying a stable,
# greppable substring for the idempotency scan + ``--fresh`` cleanup. Plain real
# chatter will not contain it, so detection has no realistic false positives.
SEED_MARKER = "·crn-seed"

# How many recent messages to scan when detecting prior seeds. The full scenario is
# ~12 messages; 200 leaves generous headroom for chatter posted between seed runs
# without paging the whole channel history.
_HISTORY_SCAN_LIMIT = 200

Kind = Literal["offer", "notice", "chatter"]


@dataclass(frozen=True)
class SeedMessage:
    """One scripted message to seed, tagged by ``kind`` for counts/tests.

    ``kind`` drives nothing at post time (every message is posted identically as the
    operator with the marker) — it exists so the scenario is self-describing and the
    unit tests can assert the mix of offers / notices / chatter.
    """

    kind: Kind
    text: str


# The Cyclone Narelle / Exmouth scenario, as data so it is unit-testable without
# posting. Offers are phrased like real mutual-aid posts ("Offering: ...") and name
# their offerer + locality so the agent's reply reads naturally despite operator
# attribution. Spread across Exmouth / North Exmouth / Learmonth per the demo beats.
SCENARIO: tuple[SeedMessage, ...] = (
    # --- chatter (the "before" scroll: needs + talk, tangled together) ---
    SeedMessage(
        "chatter",
        "Anyone heard when the power might be back on this side of town? Been out since the cyclone hit.",
    ),
    SeedMessage(
        "chatter",
        "Family of 4 in North Exmouth here — we're okay but down to our last few bottles of water. If anyone's got spare please shout.",
    ),
    SeedMessage(
        "chatter",
        "Phone lines patchy out at Learmonth. If you can't reach someone try the group here, a few of us are checking through the day.",
    ),
    SeedMessage(
        "chatter",
        "Reminder the IGA is cash-only while eftpos is down. They've still got some tinned food and nappies as of this morning.",
    ),
    # --- coordinator notices (SES/DFES-style) ---
    SeedMessage(
        "notice",
        "SES update (Exmouth): Minilya-Exmouth Rd remains CLOSED in both directions due to flooding and debris. No estimated reopening. Do not attempt the route - turn around, don't drown. Verify before relying on this.",
    ),
    SeedMessage(
        "notice",
        "DFES community notice: the recovery centre at the Exmouth Sports Club is open 8am-6pm for water, charging, and welfare checks. Bring ID if you can. Updates will be posted here.",
    ),
    # --- offers (the matchable inventory; "Offering: ..." mutual-aid phrasing) ---
    SeedMessage(
        "offer",
        "Offering: a 2kW petrol generator, fuelled and tested. Jo on the North Exmouth side — collect any time today, can help carry it.",
    ),
    SeedMessage(
        "offer",
        "Offering: 20L of bottled water (and a few extra 1.5L bottles) here in Exmouth town. Happy to drop within a few streets if you can't get out.",
    ),
    SeedMessage(
        "offer",
        "Offering: two camp beds plus blankets, clean and ready. We're in Exmouth near the marina — message me if a family needs somewhere to sleep tonight.",
    ),
    SeedMessage(
        "offer",
        "Offering: a sealed tin of baby formula (stage 1) and some spare nappies. North Exmouth — can meet halfway if the roads near you are okay.",
    ),
    SeedMessage(
        "offer",
        "Offering: a spare room with a proper bed out at Learmonth, dry and has back-up power. Can take a couple or a small family if anyone's been flooded out.",
    ),
    SeedMessage(
        "offer",
        "Offering: a stocked first-aid kit and a working battery radio. Exmouth town centre — grab whatever you need, no need to return it.",
    ),
)


def with_marker(text: str) -> str:
    """Return ``text`` with the idempotency marker appended."""
    return f"{text} {SEED_MARKER}"


def is_seeded_message(text: str) -> bool:
    """Whether a channel message ``text`` was posted by a previous seed run."""
    return SEED_MARKER in text


def pending_messages(
    scenario: tuple[SeedMessage, ...], already_posted: set[str]
) -> list[SeedMessage]:
    """Scenario messages not yet present in the channel (by marked text).

    ``already_posted`` is the set of marked message texts already found in the
    channel history; a scenario message whose ``with_marker`` text is in that set is
    skipped so a re-run never duplicates it.
    """
    return [m for m in scenario if with_marker(m.text) not in already_posted]


def _scan_seeded(client: WebClient, channel: str, user_token: str) -> list[dict[str, str]]:
    """Recent channel messages that carry the seed marker (``ts`` + ``text``).

    Best-effort: an API error is logged and read as "no prior seed found" so a
    history hiccup degrades to attempting a fresh post (idempotency may then re-post,
    which the operator can clean with ``--fresh``) rather than aborting.
    """
    try:
        response = client.conversations_history(
            channel=channel, limit=_HISTORY_SCAN_LIMIT, token=user_token
        )
    except SlackApiError as exc:
        logger.warning("Could not scan channel history (treating as no prior seed): %s", exc)
        return []
    messages = response.get("messages", []) or []
    return [
        {"ts": str(m["ts"]), "text": str(m.get("text", ""))}
        for m in messages
        if m.get("ts") and is_seeded_message(str(m.get("text", "")))
    ]


def _delete_prior_seed(client: WebClient, channel: str, user_token: str) -> int:
    """Delete every marker-bearing message in the channel; return the count deleted.

    Only marked messages are touched — ordinary chatter is never deleted. Each delete
    is best-effort: a failure on one message is logged and the rest proceed.
    """
    seeded = _scan_seeded(client, channel, user_token)
    deleted = 0
    for message in seeded:
        try:
            client.chat_delete(channel=channel, ts=message["ts"], token=user_token)
            deleted += 1
        except SlackApiError as exc:
            logger.warning("Could not delete prior seed message %s: %s", message["ts"], exc)
    if deleted:
        logger.info("Deleted %d prior seed message(s) for a clean re-seed.", deleted)
    return deleted


def _post_messages(
    client: WebClient, channel: str, user_token: str, messages: list[SeedMessage]
) -> int:
    """Post each scenario message (marked) as the operator; return the count posted."""
    posted = 0
    for message in messages:
        client.chat_postMessage(channel=channel, text=with_marker(message.text), token=user_token)
        posted += 1
    return posted


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="seed_demo",
        description="Seed the Cyclone Narelle / Exmouth scenario into CRISIS_CHANNEL.",
    )
    parser.add_argument(
        "--fresh",
        "--reset",
        dest="fresh",
        action="store_true",
        help="Delete every prior seeded message before re-seeding (clean demo re-run).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Seed the scenario into ``CRISIS_CHANNEL``; return a process exit code.

    Fails fast (exit 1, no posting) when ``SLACK_USER_TOKEN`` or ``CRISIS_CHANNEL``
    is missing. Otherwise scans for prior seeds, optionally wipes them (``--fresh``),
    posts only the messages not already present, and exits 0.
    """
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    load_dotenv(dotenv_path=".env", override=False)

    user_token = resolve_user_token(None)
    if not user_token:
        logger.error(
            "SLACK_USER_TOKEN is not set — the seeder posts matchable offers as the "
            "operator and needs a user token with chat:write + channels:history. Add "
            "it to .env (see .env.example) and retry."
        )
        return 1

    channel = designated_channel_id()
    if not channel:
        logger.error(
            "CRISIS_CHANNEL is not set — the seeder needs the channel id to seed into. "
            "Add it to .env (see .env.example) and retry."
        )
        return 1

    client = WebClient(
        base_url=os.environ.get("SLACK_API_URL", "https://slack.com/api"),
        token=os.environ.get("SLACK_BOT_TOKEN"),
    )

    if args.fresh:
        _delete_prior_seed(client, channel, user_token)
        already_posted: set[str] = set()
    else:
        already_posted = {m["text"] for m in _scan_seeded(client, channel, user_token)}

    pending = pending_messages(SCENARIO, already_posted)
    if not pending:
        logger.info(
            "Channel already seeded (%d scenario messages present) — nothing to post. "
            "Use --fresh to wipe and re-seed.",
            len(SCENARIO),
        )
        return 0

    posted = _post_messages(client, channel, user_token, pending)
    skipped = len(SCENARIO) - posted
    logger.info(
        "Seeded %d message(s) into %s (%d already present, skipped). RTS will index "
        "them in ~1 min — wait before posting a need.",
        posted,
        channel,
        skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
