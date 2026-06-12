from logging import Logger

from slack_bolt import BoltContext, Say, SayStream, SetStatus
from slack_sdk import WebClient

from agent import AgentDeps
from agent.deps import resolve_user_token
from listeners.channel_gate import is_crisis_channel
from listeners.recall_reply import NeedRecall, route_message
from listeners.reply import compose_reply
from thread_context import conversation_store

_STATUS_LOADING_MESSAGES = [
    "Teaching the hamsters to type faster…",
    "Untangling the internet cables…",
    "Consulting the office goldfish…",
    "Polishing up the response just for you…",
    "Convincing the AI to stop overthinking…",
]


def handle_message(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Handle DMs, engaged threads, and passive listening in the designated channel.

    Routing (after the bot/self/subtype guards):

    * **DM** -> always replied (one party, every message gets an answer).
    * **Engaged thread reply** -> replied only if the bot is already in that thread.
    * **Top-level message in the designated ``CRISIS_CHANNEL``** -> passively
      listened (task 006 / ADR-0004): the message is routed, an offer is indexed +
      acked and a need is answered in-thread, but chatter (``NotACrisisMessage``,
      where ``route_message`` returns ``None``) is silently ignored — it never reaches
      the LLM reply. This differs from DMs, which reply unconditionally.
    * **Any other top-level channel message** -> skipped (handled by app_mentioned).
    """
    # Skip message subtypes (edits, deletes, etc.) and bot messages.
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    is_dm = event.get("channel_type") == "im"
    is_thread_reply = event.get("thread_ts") is not None

    if is_dm or is_thread_reply:
        # Channel thread replies are handled only if the bot is already engaged.
        if (
            is_thread_reply
            and not is_dm
            and conversation_store.get_history(context.channel_id, event["thread_ts"]) is None
        ):
            return
        _reply_conversationally(client, context, event, logger, say, say_stream, set_status, is_dm)
        return

    # Top-level channel message: passively listen ONLY in the designated channel.
    if is_crisis_channel(context.channel_id):
        _listen_in_designated_channel(client, context, event, logger, say, say_stream, set_status)
        return

    # Every other top-level channel message is handled by app_mentioned.
    return


def _reply_conversationally(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
    is_dm: bool,
):
    """The unconditional reply path for DMs and engaged threads — every turn replies.

    A need's recall (if any) is threaded into the prose; an offer is acked by
    ``route_message`` and the agent still composes its conversational reply (this is
    a DM/engaged thread, where the user expects an answer to every message).
    """
    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]
        user_id = context.user_id

        history = conversation_store.get_history(channel_id, thread_ts)

        set_status(status="Thinking...", loading_messages=_STATUS_LOADING_MESSAGES)

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

        conversation_store.set_history(channel_id, thread_ts, result.all_messages())

    except Exception as e:
        logger.exception(f"Failed to handle message: {e}")
        say(
            text=f":warning: Something went wrong! ({e})",
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )


def _listen_in_designated_channel(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Passively route a top-level message in the designated channel (ADR-0004).

    Unlike the DM/thread path, this replies ONLY when ``route_message`` recognises a
    crisis message:

    * **Offer** -> ``route_message`` indexes it and posts its own threaded ack, then
      returns ``None``; we compose nothing more (the ack is the single reply).
    * **Need** -> ``route_message`` returns a :class:`NeedRecall`; we compose exactly
      one threaded reply (prose + sourced blocks) naming the requester.
    * **Chatter (``NotACrisisMessage``)** -> ``route_message`` returns ``None`` and
      posts nothing; we compose nothing. Channel chatter is parsed but never
      answered — it MUST NOT reach the LLM reply or produce any visible bot output.

    The ``None`` from ``route_message`` covers both "offer already acked" and
    "chatter": in both cases there is no need reply to compose, so guarding the
    compose on a returned :class:`NeedRecall` is exactly the silence guarantee.

    Mention-prefixed posts are explicitly deferred: Slack delivers BOTH an
    ``app_mention`` and a ``message.channels`` event for one user message that
    mentions the bot. To avoid a double ack / double reply / double index, a
    top-level post whose text mentions the bot is left for ``handle_app_mentioned``
    — restoring the pre-006 deferral for mention-prefixed posts.
    """
    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event["ts"]
        user_id = context.user_id

        # A post that @mentions the bot is also delivered as an app_mention event,
        # which owns it. Skip it here so it is not processed twice. (Guard is a
        # no-op when bot_user_id is unknown — defer to the app_mention handler only
        # when we can positively identify our own mention.)
        if context.bot_user_id and f"<@{context.bot_user_id}>" in text:
            logger.debug(
                "Passive listen in %s: skipping mention-prefixed post (app_mention owns it)",
                channel_id,
            )
            return

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

        if recall is None:
            # Offer was acked by route_message, or this was chatter — either way there
            # is no need reply to compose. Stay silent (debug log only) so channel
            # chatter never produces bot noise.
            logger.debug(
                "Passive listen in %s: nothing to answer (offer acked or non-crisis chatter)",
                channel_id,
            )
            return

        # A recognised need: compose exactly one threaded reply naming the requester.
        set_status(status="Thinking...", loading_messages=_STATUS_LOADING_MESSAGES)
        history = conversation_store.get_history(channel_id, thread_ts)
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
            mention_requester=True,
        )
        conversation_store.set_history(channel_id, thread_ts, result.all_messages())

    except Exception as e:
        logger.exception(f"Failed to passively handle channel message: {e}")
