from logging import Logger

from slack_bolt.context.set_suggested_prompts import SetSuggestedPrompts

# Crisis-domain suggested prompts shown when a resident opens a new assistant
# thread. Each ``message`` is the text SENT verbatim when the chip is tapped, so
# they are realistic, plain-language crisis messages grounded in the demo scenario
# (Exmouth WA / Severe Tropical Cyclone Narelle): a resident need, a volunteer
# offer, and a road/info question — teaching the agent's value in one glance. The
# fourth is the coordinator angle (a resolved-case recap).
SUGGESTED_PROMPTS = [
    {
        "title": "Ask for help you need",
        "message": "Family of 4 in North Exmouth, no power — we need drinking water and a generator.",
    },
    {
        "title": "Offer something you have",
        "message": "I can offer a spare room in Exmouth town for someone who needs shelter.",
    },
    {
        "title": "Check a road or official update",
        "message": "Is the road to Learmonth open right now?",
    },
    {
        "title": "Catch up on the situation",
        "message": "What's the latest on open needs and offers around Exmouth?",
    },
]

# A calm, plain-language invitation — matches the system-prompt persona and tells a
# resident exactly what to do: describe the need in their own words.
THREAD_TITLE = "What do you need? Tell me in plain language."


def handle_assistant_thread_started(set_suggested_prompts: SetSuggestedPrompts, logger: Logger):
    """Handle assistant thread started events by setting suggested prompts."""
    try:
        set_suggested_prompts(
            prompts=SUGGESTED_PROMPTS,
            title=THREAD_TITLE,
        )
    except Exception as e:
        logger.exception(f"Failed to handle assistant thread started: {e}")
