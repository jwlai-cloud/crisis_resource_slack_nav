import os
from dataclasses import dataclass

from slack_sdk import WebClient


def resolve_user_token(context_user_token: str | None) -> str | None:
    """Prefer the OAuth-provided user token; fall back to SLACK_USER_TOKEN.

    Socket-mode dev (`slack run`) never populates `context.user_token` — that
    only happens in the OAuth/HTTP deployment. RTS search and the Slack MCP
    toolset both need user-scope auth, so local runs read the installed app's
    User OAuth Token from the environment instead.
    """
    return context_user_token or os.environ.get("SLACK_USER_TOKEN") or None


@dataclass
class AgentDeps:
    client: WebClient
    user_id: str
    channel_id: str
    thread_ts: str
    message_ts: str
    user_token: str | None = None
