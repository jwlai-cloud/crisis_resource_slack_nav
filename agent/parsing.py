"""Free-text -> typed Need/Offer parsing via pydantic-ai structured output.

The ``parse`` step of the agent loop (parse -> plan -> rank -> compose) turns a
Slack message into one of three typed results using a *dedicated*, small
pydantic-ai ``Agent`` whose ``output_type`` is a union. pydantic-ai drives the
model to emit one of those types directly — no JSON scraping, no regex.

This is intentionally a separate Agent from ``agent.agent.agent`` (the big
reasoning/system-prompt agent): parsing wants a tight, single-purpose prompt and
a constrained output type, not the full crisis persona.
"""

from datetime import datetime

from pydantic import BaseModel
from pydantic_ai import Agent

from agent.agent import get_model
from entities import Need, Offer, deterministic_id

PARSING_PROMPT = """\
You classify a single Slack message from a disaster mutual-aid workspace into one
of three structured results, then extract its fields.

- A NEED is a resident asking for a resource (water, generator, shelter, a lift,
  medication, etc.). Extract: need_type (what is needed), location (where),
  urgency (one of: low, medium, high, critical), and household_size (how many
  people; default 1 if unstated).
- A NEED also includes a question seeking crisis-relevant official or situational
  information that an official feed or the workspace could answer about the
  disaster, such as:
    - road / travel safety ("is the road to X safe?", "can I drive to X?")
    - where to evacuate / shelter ("where do we evacuate?")
    - where to get water / power / supplies ("where can I get drinking water?")
    - the status of an official warning / closure
  For an information need, set need_type to the information being sought
  (e.g. "road safety: Learmonth", "where to evacuate", "where to get water"),
  location to the place it concerns (if any), urgency on a best-effort reading of
  the message (default medium if unclear), and household_size 1 unless stated.
- An OFFER is a volunteer offering a resource. Extract: resource_type (what is
  offered), location, and availability (when / how it can be collected).
- Anything else — greetings, thanks, social chatter, coordinator status updates
  ("power's back in town"), and off-topic or social questions — is
  NotACrisisMessage. A question is only a NEED when an official feed or the
  workspace could answer it about the disaster; everything social or off-topic
  stays NotACrisisMessage.

Extract only what the message states. Do not invent locations or quantities. If
the message is not clearly a need or an offer, return NotACrisisMessage.
"""


class ParsedNeed(BaseModel):
    """Fields the model extracts for a need (id/requester/ts added by us)."""

    need_type: str
    location: str
    urgency: str
    household_size: int = 1


class ParsedOffer(BaseModel):
    """Fields the model extracts for an offer (id/offerer/ts added by us)."""

    resource_type: str
    location: str
    availability: str


class NotACrisisMessage(BaseModel):
    """Marker result: the message is neither a need nor an offer.

    Carries the model's brief reason so callers can log why a message was
    skipped without re-running the parse.
    """

    reason: str = ""


parsing_agent: Agent[None, ParsedNeed | ParsedOffer | NotACrisisMessage] = Agent(
    output_type=[ParsedNeed, ParsedOffer, NotACrisisMessage],
    system_prompt=PARSING_PROMPT,
    # Structured-output unions are where small models fail most; give the
    # validation loop room before the whole turn errors out.
    retries=3,
)


def parse_message(
    text: str,
    author: str,
    ts: datetime,
) -> Need | Offer | NotACrisisMessage:
    """Parse one Slack message into a typed Need, Offer, or NotACrisisMessage.

    ``author`` and ``ts`` (the Slack message author and its timestamp) are
    threaded in by us, not extracted by the model: they are the trust-critical
    source fields and the basis for the deterministic id. ``ts`` must be a
    timezone-aware UTC datetime — the Need/Offer validator rejects naive ones.

    The model is selected by ``agent.agent.get_model()``. Unit tests drive this
    with ``parsing_agent.override(model=...)`` (a ``TestModel``/``FunctionModel``),
    which takes precedence over the passed-in model, so no live LLM is called.
    """
    result = parsing_agent.run_sync(text, model=get_model())
    parsed = result.output

    if isinstance(parsed, ParsedNeed):
        return Need(
            id=deterministic_id(author, ts),
            requester=author,
            need_type=parsed.need_type,
            location=parsed.location,
            urgency=parsed.urgency,
            household_size=parsed.household_size,
            source_ts=ts,
        )
    if isinstance(parsed, ParsedOffer):
        return Offer(
            id=deterministic_id(author, ts),
            offerer=author,
            resource_type=parsed.resource_type,
            location=parsed.location,
            availability=parsed.availability,
            source_ts=ts,
        )
    return parsed
