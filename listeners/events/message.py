from logging import Logger

from slack_bolt import BoltContext, Say, SayStream, SetStatus
from slack_sdk import WebClient

from agent import AgentDeps
from agent.deps import resolve_user_token
from listeners.recall_reply import NeedRecall, route_message
from listeners.reply import compose_reply
from thread_context import conversation_store


def handle_message(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Handle messages sent to the agent via DM or in threads the bot is part of."""
    # Skip message subtypes (edits, deletes, etc.) and bot messages.
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    is_dm = event.get("channel_type") == "im"
    is_thread_reply = event.get("thread_ts") is not None

    if is_dm:
        pass
    elif is_thread_reply:
        # Channel thread replies are handled only if the bot is already engaged
        history = conversation_store.get_history(context.channel_id, event["thread_ts"])
        if history is None:
            return
    else:
        # Top-level channel messages are handled by app_mentioned
        return

    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]

        user_id = context.user_id

        # Get conversation history
        history = conversation_store.get_history(channel_id, thread_ts)

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

        # Workspace recall: if this is a need, gather ranked, sourced prior offers
        # (or an explicit degraded/empty state). An offer is acked here and returns
        # None; a need returns its recall so we compose ONE reply (prose + blocks).
        recall: NeedRecall | None = None
        try:
            recall = route_message(
                text,
                author=user_id,
                event_ts=event["ts"],
                thread_ts=thread_ts,
                client=client,
                user_token=resolve_user_token(context.user_token),
                team_id=context.team_id,
                bot_user_id=context.bot_user_id,
                say=say,
            )
        except Exception as recall_error:
            logger.warning("Workspace recall failed, continuing with LLM reply: %s", recall_error)

        # Run the agent and post its single, sourced reply. DMs omit the requester
        # mention (only one other party); channel thread replies name the requester.
        deps = AgentDeps(
            client=client,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=event["ts"],
            user_token=resolve_user_token(context.user_token),
        )
        result = compose_reply(
            text,
            deps,
            say_stream=say_stream,
            message_history=history,
            recall=recall,
            mention_requester=not is_dm,
        )

        # Store conversation history
        conversation_store.set_history(channel_id, thread_ts, result.all_messages())

    except Exception as e:
        logger.exception(f"Failed to handle message: {e}")
        say(
            text=f":warning: Something went wrong! ({e})",
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )
