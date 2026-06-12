# 006 — Decide: passive offer listening in the mutual-aid channel

Design doc §5 ("Volunteer offers a resource") implies the agent passively indexes a plain channel post like "I've got a spare 2kW generator in town." The current build (inherited template routing, kept in 005) ignores top-level channel messages — offers are only captured via DM or @mention.

Decision needed before the demo:
- **Option A — keep mention-gated.** No LLM call per random channel message (Gemini quota, privacy, noise). Demo script adjusts to @mention or DM for offers.
- **Option B — passive listening in ONE dedicated channel** (e.g. #exmouth-mutual-aid): top-level messages there get parse → (offer ⇒ index + ack; need ⇒ recall reply); all other channels stay mention-gated. Matches the design doc's flow; costs one parse call per message in that channel.

If B: gate by channel id/name config (env var), document in CLAUDE.md, ADR if it forks from the design doc posture. Demo-script impact either way.

## Log
