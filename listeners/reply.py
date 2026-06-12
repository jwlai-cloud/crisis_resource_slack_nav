"""Compose the agent's single reply for a turn — prose + sourced blocks, one message.

Both the DM/thread listener and the app-mention listener funnel through here so the
"one reply per need" rule lives in exactly one place. The flow:

* Run the agent, threading any pre-computed workspace recall context into the call so
  the prose reasons over the real data instead of inventing sources.
* Stream the prose into the thread; finalise the *same* streamed message with the
  authoritative, sourced match blocks (when this turn was a need) followed by the
  feedback buttons. One streamed message carries the whole answer — no second,
  source-diverging reply.
* In a channel the reply opens with a real ``<@requester_id>`` mention so the resident
  is named; DMs omit it (there is only one other party).
"""

from slack_bolt import SayStream
from slack_sdk.models.blocks import Block

from agent import AgentDeps, run_agent
from listeners.recall_reply import NeedRecall
from listeners.views.feedback_builder import build_feedback_blocks


def compose_reply(
    text: str,
    deps: AgentDeps,
    *,
    say_stream: SayStream,
    message_history: object | None = None,
    recall: NeedRecall | None = None,
    mention_requester: bool = False,
) -> object:
    """Run the agent and post its single, sourced reply; return the agent result.

    ``recall`` (when present) supplies both the LLM context (so the prose composes
    around the real matches) and the structured match blocks rendered beneath the
    prose. ``mention_requester`` prepends a tappable ``<@requester_id>`` mention to
    the streamed reply for channel replies; DM callers leave it ``False``.
    """
    recall_context = recall.llm_context if recall is not None else None
    result = run_agent(text, deps, message_history=message_history, recall_context=recall_context)

    streamer = say_stream()
    if mention_requester:
        streamer.append(markdown_text=f"<@{deps.user_id}> ")
    streamer.append(markdown_text=result.output)

    trailing_blocks: list[Block] = []
    if recall is not None:
        trailing_blocks.extend(recall.blocks)
    trailing_blocks.extend(build_feedback_blocks())
    streamer.stop(blocks=trailing_blocks)

    return result
