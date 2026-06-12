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

Visual parity with the landing-page mock (task 008): the reply opens with a
code-composed parse-summary ``section`` (``fields``: need_type / location /
urgency / household, drawn straight from the parsed :class:`~entities.Need`,
never the LLM, with unknown fields omitted), and each match card opens with a
rank-label context line — ``🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH``. The
mock's colored *left bar* is rendered with a leading colored-square emoji rather
than a message ``attachment``: the single streamed reply finalises through
``ChatStream.stop(blocks=...)`` (task 005), which exposes no ``attachments``
parameter, and the 010 action handlers rewrite cards by ``block_id`` within the
message's *top-level* blocks — burying the action row inside an attachment would
break that state machine. The emoji is the equivalent, top-level-safe cue.

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

from entities import Need
from recall.models import RecallError, RecallMatch
from recall.payload import ConnectPayload

VERIFY_NOTE = "Verify before relying on this."

# The mock renders a colored *left bar* per card (green = workspace). Block Kit's
# streamed-reply surface (``ChatStream.stop``) has no ``attachments`` hook and the
# action-button state machine needs the rows to stay top-level blocks, so we use a
# leading colored-square emoji as the equivalent cue. Green matches the workspace
# card; future MCP-card work owns the blue/red variants.
WORKSPACE_BAR_EMOJI = "🟩"

# The per-card rank label, mirroring the mock's `MATCH n · WORKSPACE · REAL-TIME
# SEARCH` context line. Every match rendered here is a workspace/RTS or index hit,
# so the source label is uniform; official MCP cards (future work) compose their
# own `· OFFICIAL · MCP FEED` label elsewhere and are not styled by this module.
_RANK_LABEL = "{emoji} *MATCH {n}* · WORKSPACE · REAL-TIME SEARCH"

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

# Slack caps messages at 50 blocks. Each match now renders rank-context + section
# + sourcing-context + actions (4 blocks) plus a divider between cards, and the
# reply also carries a leading parse-summary section, a header, and an optional
# "showing top N" line. Worst case: 1 + 1 + (5 * 4) + 4 + 1 = 27 blocks, plus the
# feedback row appended by the caller — comfortably under the 50-block cap.
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


def _parse_summary_block(need: Need) -> SectionBlock | None:
    """Compose the structured parse summary as a ``fields`` section, or ``None``.

    The reply's structured region opens with what the agent understood — drawn
    verbatim from the parsed :class:`~entities.Need` (``need_type`` / ``location``
    / ``urgency`` / ``household``), composed by code, never by the LLM. Each label
    is a bold mrkdwn line; empty/unknown values are *omitted* entirely rather than
    shown as a placeholder (the no-placeholder rule). Returns ``None`` if every
    field is unknown so we never emit an empty section. Slack caps a section at 10
    ``fields``; four here stays well under.
    """
    fields: list[MarkdownTextObject] = []
    need_type = (need.need_type or "").strip()
    if need_type:
        fields.append(MarkdownTextObject(text=f"*need_type*\n{need_type}"))
    location = (need.location or "").strip()
    if location and location.lower() != "unknown":
        fields.append(MarkdownTextObject(text=f"*location*\n{location}"))
    # Urgency is a required StrEnum, so it is always known and rendered.
    fields.append(MarkdownTextObject(text=f"*urgency*\n{need.urgency.value}"))
    # household_size is a required int; render when it is a real count (> 0).
    if need.household_size > 0:
        fields.append(MarkdownTextObject(text=f"*household*\n{need.household_size}"))
    if not fields:
        return None
    return SectionBlock(fields=fields)


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


def _rank_label_block(index: int) -> ContextBlock:
    """The card's rank-label header line: ``🟩 MATCH n · WORKSPACE · REAL-TIME SEARCH``.

    Mirrors the mock's per-card rank line; the leading colored square stands in for
    the mock's green left bar (workspace source). ``index`` is zero-based; the label
    is one-based for humans.
    """
    text = _RANK_LABEL.format(emoji=WORKSPACE_BAR_EMOJI, n=index + 1)
    return ContextBlock(elements=[MarkdownTextObject(text=text)])


def _match_blocks(match: RecallMatch, index: int) -> list[Block]:
    """The blocks for one match: rank label, snippet, source/contact/verify line, actions.

    Each card opens with its rank-label context line (the colored-square cue +
    `MATCH n · WORKSPACE · REAL-TIME SEARCH`), then the snippet, then the sourcing
    context line. The trailing :class:`ActionsBlock` is the only place a recall
    match becomes *actionable*. Every match rendered here is a workspace/RTS or
    index hit (a person's offer), so every one gets the confirmation buttons;
    official MCP results are composed elsewhere and stay informational (no actions).
    """
    elements: list[MarkdownTextObject] = [MarkdownTextObject(text=_source_line(match))]
    contact = _contact_line(match)
    if contact is not None:
        elements.append(MarkdownTextObject(text=contact))
    elements.append(MarkdownTextObject(text=VERIFY_NOTE))
    return [
        _rank_label_block(index),
        SectionBlock(text=MarkdownTextObject(text=match.text or "_(no text)_")),
        ContextBlock(elements=elements),
        _match_action_block(match, index),
    ]


def build_recall_blocks(
    result: list[RecallMatch] | RecallError,
    *,
    need: Need | None = None,
) -> list[Block]:
    """Compose the Block Kit reply for a recall result.

    ``result`` is whatever ``recall.client.recall_offers`` returned — already
    ranked when it is a list. When ``need`` is supplied (every recognised Need),
    the structured region *opens* with the code-composed parse-summary fields
    section, ahead of every branch below. Branches:

    * :class:`RecallError` -> a single "search unavailable" block (degraded).
    * empty list -> a single "no prior offers found" block.
    * non-empty list -> a header, then one match group per item, divider-separated.
      Each match card opens with its rank-label context line.

    Every match group carries source, timestamp, and the verify note.
    """
    blocks: list[Block] = []
    if need is not None:
        summary = _parse_summary_block(need)
        if summary is not None:
            blocks.append(summary)

    if isinstance(result, RecallError):
        blocks.append(SectionBlock(text=MarkdownTextObject(text=_SEARCH_UNAVAILABLE)))
        return blocks

    if not result:
        blocks.append(SectionBlock(text=MarkdownTextObject(text=_NO_MATCHES)))
        return blocks

    blocks.append(HeaderBlock(text=PlainTextObject(text=_HEADER)))
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
