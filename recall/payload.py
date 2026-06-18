"""Typed button payloads for the bounded-autonomy action buttons (task 010).

A match card's action buttons carry the identity of the match they act on in the
button ``value`` — Slack's only per-button data channel. The value is a compact
JSON object, parsed back into a typed :class:`ConnectPayload` on receipt so a
handler never index-fumbles a raw dict. Two product constraints shape it:

* **No auto-actions.** The payload names *who* offered and *what* (an offer id
  when the match came from the in-memory index, a permalink when it came from
  RTS) — never the requester. The requester is always the human who pressed the
  button (``body["user"]["id"]`` at click time), so the agent can never act on a
  match on someone's behalf.
* **Slack's 2000-char value limit.** The free-text snippet is truncated so the
  serialised value stays well under the cap even for a long offer; ids and the
  permalink are bounded by Slack itself.

The same payload rides every button on a card (Connect / Resolve / Not relevant);
each handler reads only the fields it needs.

This lives in the ``recall`` layer (not ``listeners``) because the recall compose
step builds the buttons and so owns the payload contract; the Bolt action
handlers in ``listeners.actions`` are the consumers and import it from here. That
keeps the dependency arrow pointing one way (``listeners`` -> ``recall``).
"""

import json
from dataclasses import dataclass

# Slack rejects an interactive element ``value`` longer than this. We truncate the
# snippet so even a pathological offer text plus ids and a permalink stays under it.
_SLACK_VALUE_LIMIT = 2000

# The snippet is for a human-readable intro line, not matching — a short prefix is
# plenty and keeps the serialised value comfortably below the Slack cap.
_SNIPPET_MAX = 280


@dataclass(frozen=True)
class ConnectPayload:
    """The match identity carried on a card's action buttons.

    ``offerer_id`` is the Slack user who posted the offer (always present — it is
    how the connect handler reaches the offerer). ``offer_id`` is the in-memory
    index id when the match came from the index (so ``crisis_resolve`` can call
    ``mark_resolved``); it is empty for an RTS-only hit, which instead carries a
    ``permalink`` to the original workspace message. ``snippet`` is a short,
    truncated offer text used only to compose the sourced intro line.
    """

    offerer_id: str
    offer_id: str = ""
    permalink: str = ""
    snippet: str = ""

    def to_value(self) -> str:
        """Serialise to a compact JSON string for a Slack button ``value``.

        The snippet is truncated to keep the value under Slack's 2000-char limit;
        empty fields are dropped so the value stays small.
        """
        data: dict[str, str] = {"offerer_id": self.offerer_id}
        if self.offer_id:
            data["offer_id"] = self.offer_id
        if self.permalink:
            data["permalink"] = self.permalink
        if self.snippet:
            data["snippet"] = self.snippet[:_SNIPPET_MAX]
        value = json.dumps(data, separators=(",", ":"))
        if len(value) > _SLACK_VALUE_LIMIT:
            # Defensive: a very long permalink could still overflow. Drop the
            # snippet entirely rather than emit an over-limit value Slack rejects.
            data.pop("snippet", None)
            value = json.dumps(data, separators=(",", ":"))
        return value

    @classmethod
    def from_value(cls, value: str) -> "ConnectPayload":
        """Parse a button ``value`` JSON string back into a typed payload.

        Tolerates missing optional fields (they default to empty). Raises
        ``ValueError`` on malformed JSON or a missing ``offerer_id`` so a handler
        degrades explicitly rather than acting on a half-parsed match.
        """
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"button value is not valid JSON: {value!r}") from exc
        if not isinstance(data, dict) or not data.get("offerer_id"):
            raise ValueError(f"button value missing offerer_id: {value!r}")
        return cls(
            offerer_id=str(data["offerer_id"]),
            offer_id=str(data.get("offer_id", "")),
            permalink=str(data.get("permalink", "")),
            snippet=str(data.get("snippet", "")),
        )
