# 013 — Seed the Exmouth scenario (demo-ready workspace)

Make the sandbox read as a real Cyclone Narelle mutual-aid operation so the demo
video + judges see a populated, credible workspace (design doc demo plan; "Pre-seed
the workspace before recording").

## Decided design (from live probes, 2026-06-13)
- **Matchable offers are posted via the user token (SLACK_USER_TOKEN) as the
  operator account.** Live-verified: such posts are RTS-matchable (~1 min indexing
  lag) and RTS attributes them to the real user, so the recall noise filter keeps
  them. They carry a bot_id on the raw event so the passive listener skips them
  (no ack spam — exactly what we want for seed). Trade-off: every matchable offer
  shows the operator as offerer (we can't author as the 7 seeded personas — no
  tokens; chat:write.customize posts are bot-authored and get filtered from recall).
  Accept this; the demo narration still works.
- **Texture (coordinator notices, chatter) MAY use chat:write.customize** for varied
  persona names/avatars in the "noisy channel" scroll — these are non-matchable
  (bot-authored) which is fine for flavor. Requires the `chat:write.customize` bot
  scope (add to manifest + note re-install) IF used; otherwise post texture as the
  operator too. SWE: keep it simple — operator-posted texture is acceptable if the
  scope adds friction.

## Acceptance criteria
1. `scripts/seed_demo.py` (+ `make seed-demo`): posts into CRISIS_CHANNEL
   (C0BA6LCKK42) via the user token —
   - 5–6 believable offers (e.g. 2kW generator, 20L water, two camp beds, baby
     formula, a spare room, a first-aid kit), spread across Exmouth/North
     Exmouth/Learmonth, matching the demo script beats;
   - 1–2 coordinator notices (SES/DFES-style update);
   - a few lines of believable chatter for the "before" scroll.
2. **Idempotent**: tag seeded messages (a trailing hidden marker, or record posted
   ts to a gitignored file) and skip on re-run — running twice does not duplicate.
   A `--reset`/`--fresh` flag may delete prior seeds for a clean re-seed.
3. Document the RTS indexing lag (offers are matchable ~1 min after seeding) and the
   operator-attribution limitation in the script docstring + CLAUDE.md commands.
4. Unit tests: message-building (the scenario content + marker), idempotency logic
   (skip when marker present) — mock the WebClient, NO live posting in tests.
   filterwarnings=error, zero warnings.
5. [HUMAN] live: run `make seed-demo`; confirm the channel is populated; wait ~1 min;
   post a need; confirm a seeded offer matches in the reply + appears on the board.

## Out of scope
The Mara/second-account path (abandoned — domain-locked invites). Persona-authored
matchable offers (impossible without their tokens).

## Log
DECISION 2026-06-13: self-account seeding (live-probed RTS-matchable). Mara dropped.
