# 024 — Seed persona variety + invisible marker (demo realism)

Live seed (013) exposed two demo problems (user-flagged): every seeded message shows
as the single operator account ("all by myself?"), and the `·crn-seed` idempotency
marker renders literally in every message.

## Direction
1. **Invisible marker.** Replace the literal `·crn-seed` suffix with a zero-width
   marker (e.g. U+200B sentinel sequence) — still greppable by the script for
   skip/`--fresh`, invisible to humans and on camera. Migrate the marker constant in
   scripts/seed_demo.py + its tests; `--fresh` should clean BOTH old (`·crn-seed`)
   and new markers during transition.
2. **Authorship split by matchability:**
   - HERO offers (1–2 the demo will match, e.g. the 2kW generator) → operator-authored
     via the user token (RTS-matchable, unchanged).
   - All other offers + coordinator notices + chatter → post via
     `chat:write.customize` (username + icon per persona: "SES Exmouth", "Jo",
     "Mara", "Exmouth Recovery") so the channel reads multi-person. These are
     texture, non-matchable (bot-authored → recall filter drops them) — which is fine.
   - Add `chat:write.customize` to the manifest bot scopes (note the re-install).
3. Keep idempotency working across both authorship paths (marker on every message;
   `--fresh` deletes all seeded regardless of author — note customize posts are
   bot-authored so chat_delete needs the bot token, operator posts need the user
   token; handle both).
4. Document the split + which offers are matchable in the script docstring.

## Acceptance criteria
1. Invisible marker; no visible tag in any seeded message; idempotency + `--fresh`
   still work (and clean legacy `·crn-seed` messages).
2. Hero offer(s) operator-authored + matchable; the rest persona-attributed via
   customize with distinct usernames; coordinator notices look official.
3. chat:write.customize scope added (manifest + re-install note).
4. Tests: marker invisibility (zero-width), authorship routing (which messages go
   customize vs user-token), idempotency across both, `--fresh` deletes both author
   types. Mocked clients, no live posting. Zero warnings.
5. [HUMAN] live: re-seed; channel shows varied persona names + official notices, no
   visible markers; the hero offer still matches a posted need.

## Out of scope
Making persona offers matchable (impossible — bot-authored posts are recall-filtered).

## Log
