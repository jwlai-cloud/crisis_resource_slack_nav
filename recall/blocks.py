"""Compose the recall reply as Block Kit — the *compose* step.

Every path here honours the product guardrails (CLAUDE.md, design doc safety):

* **Every item is sourced and timestamped.** Each match renders its text, then a
  context line carrying who posted it, which channel, and when — plus a
  permalink. No match block omits source or timestamp.
* **Verify before relying.** Every match carries the standing "verify before
  relying on this" note; the agent never asserts a match is correct or safe.
* **Degraded states are explicit.** A :class:`RecallError` composes a calm
  "couldn't search the workspace right now" block; zero matches composes an
  explicit "no prior offers found" block. Neither path is silent and neither
  fabricates a result.

The composition is pure and deterministic (timestamp formatting is UTC), so the
block structure can be snapshot/asserted in unit tests without a live Slack call.
"""

from datetime import datetime

from slack_sdk.models.blocks import (
    Block,
    ContextBlock,
    DividerBlock,
    HeaderBlock,
    MarkdownTextObject,
    PlainTextObject,
    SectionBlock,
)

from recall.models import RecallError, RecallMatch

VERIFY_NOTE = "Verify before relying on this."

_HEADER = "Prior offers from this workspace"
_NO_MATCHES = (
    "I found *no prior offers* in this workspace for that need yet. "
    "I'll keep what you posted on record so it can be matched as offers come in."
)
_SEARCH_UNAVAILABLE = (
    ":warning: I couldn't search the workspace right now, so I can't show prior "
    "offers from here. Nothing was found or ruled out — please try again shortly."
)

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M UTC"


def _format_ts(ts: datetime) -> str:
    """Render an aware-UTC timestamp for on-screen display (deterministic)."""
    return ts.strftime(_TIMESTAMP_FORMAT)


def _source_line(match: RecallMatch) -> str:
    """The sourcing context line: who / where / when, with a permalink if present."""
    author = match.author or "Unknown author"
    channel = f"#{match.channel}" if match.channel else "an unknown channel"
    when = _format_ts(match.ts)
    line = f"Posted by *{author}* in {channel} · {when}"
    if match.permalink:
        line += f" · <{match.permalink}|View message>"
    return line


def _match_blocks(match: RecallMatch) -> list[Block]:
    """The blocks for a single match: snippet, then its source+timestamp+verify line."""
    return [
        SectionBlock(text=MarkdownTextObject(text=match.text or "_(no text)_")),
        ContextBlock(
            elements=[
                MarkdownTextObject(text=_source_line(match)),
                MarkdownTextObject(text=VERIFY_NOTE),
            ]
        ),
    ]


def build_recall_blocks(result: list[RecallMatch] | RecallError) -> list[Block]:
    """Compose the Block Kit reply for a recall result.

    ``result`` is whatever ``recall.client.recall_offers`` returned — already
    ranked when it is a list. Branches:

    * :class:`RecallError` -> a single "search unavailable" block (degraded).
    * empty list -> a single "no prior offers found" block.
    * non-empty list -> a header, then one match group per item, divider-separated.

    Every match group carries source, timestamp, and the verify note.
    """
    if isinstance(result, RecallError):
        return [SectionBlock(text=MarkdownTextObject(text=_SEARCH_UNAVAILABLE))]

    if not result:
        return [SectionBlock(text=MarkdownTextObject(text=_NO_MATCHES))]

    blocks: list[Block] = [HeaderBlock(text=PlainTextObject(text=_HEADER))]
    for index, match in enumerate(result):
        if index > 0:
            blocks.append(DividerBlock())
        blocks.extend(_match_blocks(match))
    return blocks
