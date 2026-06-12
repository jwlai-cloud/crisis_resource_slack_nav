import re
from logging import Logger

from slack_bolt import BoltContext, Say, SayStream, SetStatus
from slack_sdk import WebClient

from agent import AgentDeps, run_agent
from agent.deps import resolve_user_token
from listeners.recall_reply import maybe_post_recall
from listeners.views.feedback_builder import build_feedback_blocks
from thread_context import conversation_store


def handle_app_mentioned(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Handle @mentions in channels."""
    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]
        user_id = context.user_id

        # Strip the bot mention from the text
        cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

        if not cleaned_text:
            say(
                text="Hey there! How can I help you? Ask me anything and I'll do my best.",
                thread_ts=thread_ts,
            )
            return

        # Set assistant thread status with loading messages
        set_status(
            status="Thinking...",
            loading_messages=[
                "Teaching the hamsters to type faster…",
                "Untangling the internet cables…",
                "Consulting the office goldfish…",
                "Polishing up the response just for you…",
                "Convincing the AI to stop overthinking…",
            ],
        )

        # Get conversation history
        history = conversation_store.get_history(channel_id, thread_ts)

        # Workspace recall: if this is a need, surface ranked, sourced prior offers
        # (or an explicit degraded/empty state) before the LLM reply streams.
        try:
            maybe_post_recall(
                cleaned_text,
                author=user_id,
                event_ts=event["ts"],
                thread_ts=thread_ts,
                client=client,
                user_token=resolve_user_token(context.user_token),
                team_id=context.team_id,
                say=say,
            )
        except Exception as recall_error:
            logger.warning("Workspace recall failed, continuing with LLM reply: %s", recall_error)

        # Run the agent
        deps = AgentDeps(
            client=client,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=event["ts"],
            user_token=resolve_user_token(context.user_token),
        )
        result = run_agent(cleaned_text, deps, message_history=history)

        # Stream response in thread with feedback buttons
        streamer = say_stream()
        streamer.append(markdown_text=result.output)
        feedback_blocks = build_feedback_blocks()
        streamer.stop(blocks=feedback_blocks)

        # Store conversation history
        conversation_store.set_history(channel_id, thread_ts, result.all_messages())

    except Exception as e:
        logger.exception(f"Failed to handle app mention: {e}")
        say(
            text=f":warning: Something went wrong! ({e})",
            thread_ts=event.get("thread_ts") or event["ts"],
        )
