# 006 — Passive listening in the designated mutual-aid channel

DECIDED (user, 2026-06-12): Option B — passive listening in ONE designated channel;
everywhere else stays mention-gated.

## Acceptance criteria

1. Config: `CRISIS_CHANNEL` env var (channel id; empty = feature off). .env.example
   documented. Settings read where the listeners can reach it.
2. listeners/events/message.py: top-level messages in CRISIS_CHANNEL get the full
   route_message flow — offers indexed + acked (threaded), needs answered in-thread
   with the standard reply. All other channels keep the current "handled by
   app_mentioned" skip. DMs unchanged. Thread replies in the channel unchanged
   (still skipped).
3. NotACrisisMessage results in the channel are silently ignored (no reply, no ack)
   — chatter must not trigger bot noise; log at debug only.
4. Bot/self messages and message_changed subtypes excluded (existing guards apply).
5. ADR-0004: passive-listening posture — one channel only, why (design-doc flow vs
   token cost/noise), the env-config trigger to widen/narrow.
6. CLAUDE.md: document CRISIS_CHANNEL in commands/env surface.
7. Unit tests: channel-gating table (designated channel top-level → routed; other
   channel → skipped; thread reply → skipped; chatter → silent), mocked parse.
8. [HUMAN] live: create #exmouth-mutual-aid in sandbox, set CRISIS_CHANNEL, post a
   plain offer → indexed + acked; plain need → replied in thread; chatter → silence.

## Log

DECISION 2026-06-12: Option B per user. Demo script's volunteer-posts-plainly flow
becomes real.
