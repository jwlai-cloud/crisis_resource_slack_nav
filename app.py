import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from agent import get_model
from agent.deps import resolve_user_token
from listeners import register_listeners
from listeners.backfill import maybe_backfill_on_start

load_dotenv(dotenv_path=".env", override=False)
get_model()  # Fail fast if no AI provider key is configured

logging.basicConfig(level=logging.DEBUG)

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    client=WebClient(
        base_url=os.environ.get("SLACK_API_URL", "https://slack.com/api"),
        token=os.environ.get("SLACK_BOT_TOKEN"),
    ),
)

register_listeners(app)

# Backfill the in-memory offer index from CRISIS_CHANNEL history so seeded/prior
# offers reach the coordinator board after a restart (task 026, ADR-0006). Opt-in
# (BACKFILL_ON_START) and gated on CRISIS_CHANNEL; runs in a background daemon
# thread, so it never blocks SocketModeHandler.start() below.
maybe_backfill_on_start(app.client, user_token=resolve_user_token(None))

if __name__ == "__main__":
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
