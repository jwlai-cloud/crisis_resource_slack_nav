# 013 — Demo seed data: personas, offers, channel noise

Demo prerequisites (script: "Pre-seed the demo workspace before recording — a few realistic offers, one coordinator notice, and the mock MCP data"). Also kills the self-connect quirk seen in 010's live test (requester == offerer collapses the group DM).

## Constraint discovered 2026-06-12
Recall now drops bot-authored messages (echo fix in `recall/client.py:_drop_agent_noise`). Bot-customized persona posts (`chat:write.customize`) are therefore invisible to matching — by design. Split accordingly:

## Acceptance criteria

1. **Matchable offers come from real accounts.** Document the manual step: invite ≥1 alias account ("Mara V.") to the sandbox; post 3-4 offers from it in #general (or #exmouth-mutual-aid if 006 lands): 2kW generator, bottled water, spare room/shelter, camping stoves. Content matches the demo script beats.
2. **Seeder script** (`scripts/seed_demo.py`, runs with the user/bot tokens from .env): posts non-matchable channel texture — coordinator notice ("SES update: ..."), misc community chatter, a resolved-case thread — via chat:write.customize personas (requires adding that bot scope to the manifest). Idempotent: tags seeds (e.g. invisible marker or recorded ts file) so re-runs don't duplicate.
3. Channel plan: the noisy "before" scroll (demo 0:10-0:25) needs ~10-15 mixed messages in one channel; script seeds them with believable timestamps spread (as far as Slack allows — postMessage is now-stamped, so order matters more than times; document the limitation).
4. Entry in CLAUDE.md Commands (make seed-demo) + .env.example for any new var.
5. Unit tests for the script's message-building (no live posting in tests).
6. [HUMAN] verification: run the seeder, post a need from the main account, confirm Mara's generator offer matches and Connect opens a real group DM with Mara.

## Out of scope
Real timestamp backdating (Slack doesn't allow), Canvas board content (W4/012).

## Log
