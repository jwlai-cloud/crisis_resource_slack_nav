from slack_bolt import App

from .crisis_buttons import CRISIS_ACTIONS
from .feedback_buttons import handle_feedback_button


def register(app: App):
    app.action("feedback")(handle_feedback_button)
    # The bounded-autonomy confirmation buttons (task 010): Connect / Mark resolved
    # / Not relevant. Each action_id is wired to its handler from the one mapping
    # the handler module owns, so the ids stay in sync with the rendered buttons.
    for action_id, handler in CRISIS_ACTIONS.items():
        app.action(action_id)(handler)
