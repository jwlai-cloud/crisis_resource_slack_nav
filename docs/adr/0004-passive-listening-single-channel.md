# 0004. Passive listening in a single designated channel

**Status:** Accepted
**Date:** 2026-06-12

## Context

By default the agent is mention-gated: it answers `@mentions` (`app_mention`) and
DMs, and skips top-level channel messages. The design doc's demo scenario, though,
has volunteers posting offers and residents posting needs **plainly** in a
mutual-aid channel — no `@mention` — and expecting the agent to pick them up,
index the offers, and answer the needs in-thread. The demo script's
"volunteer-posts-plainly" flow needs the agent to *passively listen*.

Passive listening is not free. Every top-level message it sees runs an LLM parse
(`parse_message`) to decide offer / need / neither, which costs tokens and latency.
Turn that on workspace-wide and a busy channel becomes a stream of parse calls, and
any chatter that the parser mis-reads risks bot noise (a stray ack or reply) in a
channel where residents are coordinating under stress — directly against the
"surface, don't intrude" posture of the safety guardrails.

So there is a real fork in *where* passive listening applies:

- **A:** workspace-wide — every channel the bot is in is passively listened.
- **B:** one designated channel, configured by id; everywhere else stays
  mention-gated.
- **C:** an operator-managed allowlist of channels.

Option A maximises recall but maximises cost and noise, and gives no kill-switch.
Option C is the eventual shape for a real deployment but needs a stored list, an
admin surface to manage it, and tests for the empty/partial cases — more than the
v1 demo scope (one channel, `#exmouth-mutual-aid`) needs.

## Decision

**Option B: passive listening is confined to one channel, named by the
`CRISIS_CHANNEL` env var (a Slack channel id).** `listeners/channel_gate.py`
reads it at message-handle time; `listeners/events/message.py` routes a top-level
message through the full `route_message` flow **only** when its channel id matches
`CRISIS_CHANNEL`. Empty or unset means the feature is **off** — no channel is
designated, every channel stays mention-gated (the pre-006 behavior).

In the designated channel:

- an **offer** is indexed (`matching.index`) and acked in-thread (its own single,
  sourced reply);
- a **need** is answered in-thread with the standard recall reply (prose + sourced
  match blocks), naming the requester;
- **chatter** (`NotACrisisMessage` — `route_message` returns `None`) is silently
  ignored. It is parsed but never answered: the compose step is guarded on a
  returned `NeedRecall`, so non-crisis messages never reach the LLM reply and never
  produce a visible bot reply or reaction in the channel. This differs from DMs,
  where every message gets a reply.

The var is read from the environment at handle time rather than cached: it is a
cheap dict lookup, and reading live lets an operator widen/narrow the posture by
changing config and restarting, with no code change.

## Consequences

- **Per-message LLM parse cost in the one channel.** Every top-level message in
  `CRISIS_CHANNEL` runs `parse_message` (an LLM call) to classify it. This is the
  accepted cost of the plain-posting demo flow — and it is bounded to one channel,
  never workspace-wide. Outside that channel no parse happens at all (the handler
  skips before routing).
- **Widening or narrowing is a config change, not a deploy.** Pointing
  `CRISIS_CHANNEL` at a different channel (or clearing it to disable passive
  listening) is an env-var edit + restart. There is no code path for *multiple*
  channels: supporting a channel allowlist (option C) is a future fork with its own
  ADR — we do not pre-build it.
- **Chatter is parsed but unanswered — explicitly silent.** A non-crisis message in
  the channel costs one parse and produces no output (debug log only). The risk
  here is a mis-parse that acks/answers genuine chatter; that is contained because
  the agent only ever *surfaces* an offer ack or a need reply with sources and a
  confirmation step — it never asserts safety or takes an automatic action (the
  four guardrails still hold). A failed parse in the passive path logs the exception
  and stays silent too — it does **not** post a `:warning:` into the channel the way
  the DM path does, because an error reply on every failed parse would itself be the
  bot noise this decision is trying to avoid.
- **DMs and engaged threads are unchanged.** The gate touches only the top-level
  channel path. DMs still reply to every message; channel thread replies are still
  handled only when the bot is already engaged in that thread.
- **No new dependency, no new stored state.** The gate is one env var read through
  a small helper. If a real deployment needs an admin-managed channel list, that is
  the option-C fork above.
