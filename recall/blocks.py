"""Compose the recall reply as Block Kit — the *compose* step.

Every path here honours the product guardrails (CLAUDE.md, design doc safety):

* **Every item is sourced and timestamped.** Each match renders its text, then a
  context line carrying who posted it, which channel, and when — plus a
  permalink and a tappable ``Contact: <@author_id>`` mention. No match block omits
  source or timestamp.
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
    ActionsBlock,
    Block,
    ButtonElement,
    ContextBlock,
    DividerBlock,
    HeaderBlock,
    MarkdownTextObject,
    PlainTextObject,
    SectionBlock,
)

from recall.models import RecallError, RecallMatch
from recall.payload import ConnectPayload

VERIFY_NOTE = "Verify before relying on this."

# Action ids for the bounded-autonomy confirmation buttons (task 010). The match
# card offers Connect / Not relevant; a connected card swaps in Mark resolved. The
# handlers in ``listeners.actions`` register against exactly these ids.
ACTION_CONNECT = "crisis_connect"
ACTION_NOT_RELEVANT = "crisis_not_relevant"
ACTION_RESOLVE = "crisis_resolve"

# Button block id prefix so a handler can locate the card's action row when it
# rewrites the buttons (Connect -> Mark resolved, or -> Dismissed). One row per
# rendered match, suffixed with the match index.
ACTIONS_BLOCK_PREFIX = "crisis_actions_"

_CONNECT_LABEL = "Connect me"
_NOT_RELEVANT_LABEL = "Not relevant"

_HEADER = "Prior offers from this workspace"

# Slack caps messages at 50 blocks; each match renders section+context+actions
# (3 blocks) plus a divider, so 5 matches stays well under the cap.
_MAX_RENDERED_MATCHES = 5
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


def _contact_line(match: RecallMatch) -> str | None:
    """A tappable `Contact: <@author_id>` Slack mention, or ``None`` if no id.

    The author id (the Slack user who posted the offer) renders as a real, tappable
    mention so the human can reach the contact in one tap. When the id is missing we
    return ``None`` rather than an empty ``<@>`` — a broken mention would mislead.
    """
    if not match.author_id:
        return None
    return f"Contact: <@{match.author_id}>"


def _button_value(match: RecallMatch) -> str:
    """Serialise the match identity onto the action buttons' shared ``value``.

    Carries the offerer (always), the index ``offer_id`` (for an index hit, so the
    resolve handler can ``mark_resolved`` it), the ``permalink`` (for an RTS-only
    hit, so the intro can cite the original message), and a short snippet. The
    requester is deliberately *not* here — it is the human who clicks.
    """
    return ConnectPayload(
        offerer_id=match.author_id,
        offer_id=match.offer_id,
        permalink=match.permalink,
        snippet=match.text,
    ).to_value()


def _match_action_block(match: RecallMatch, index: int) -> ActionsBlock:
    """The bounded-autonomy confirmation row for one match: Connect / Not relevant.

    Both buttons carry the same match-identity ``value`` (the handler reads the
    fields it needs). Nothing fires automatically — a button is the human's
    confirmation step (guardrail 1). The block id is stable+unique per rendered
    match so a handler can rewrite this exact row after a click.
    """
    value = _button_value(match)
    return ActionsBlock(
        block_id=f"{ACTIONS_BLOCK_PREFIX}{index}",
        elements=[
            ButtonElement(
                text=_CONNECT_LABEL,
                action_id=ACTION_CONNECT,
                value=value,
                style="primary",
            ),
            ButtonElement(
                text=_NOT_RELEVANT_LABEL,
                action_id=ACTION_NOT_RELEVANT,
                value=value,
            ),
        ],
    )


def _match_blocks(match: RecallMatch, index: int) -> list[Block]:
    """The blocks for one match: snippet, source/timestamp/contact/verify line, actions.

    The trailing :class:`ActionsBlock` is the only place a recall match becomes
    *actionable*. Every match rendered here is a workspace/RTS or index hit (a
    person's offer), so every one gets the confirmation buttons; official MCP
    results are composed elsewhere and stay informational (no actions).
    """
    elements: list[MarkdownTextObject] = [MarkdownTextObject(text=_source_line(match))]
    contact = _contact_line(match)
    if contact is not None:
        elements.append(MarkdownTextObject(text=contact))
    elements.append(MarkdownTextObject(text=VERIFY_NOTE))
    return [
        SectionBlock(text=MarkdownTextObject(text=match.text or "_(no text)_")),
        ContextBlock(elements=elements),
        _match_action_block(match, index),
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
    shown = result[:_MAX_RENDERED_MATCHES]
    for index, match in enumerate(shown):
        if index > 0:
            blocks.append(DividerBlock())
        blocks.extend(_match_blocks(match, index))
    if len(result) > len(shown):
        blocks.append(
            ContextBlock(
                elements=[
                    MarkdownTextObject(
                        text=f"Showing the top {len(shown)} of {len(result)} matches."
                    )
                ]
            )
        )
    return blocks
