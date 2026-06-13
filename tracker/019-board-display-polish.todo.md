# 019 — Coordinator board display polish

W4 live verification (2026-06-13) confirmed the board lifecycle works
(Open → Connected → Resolved + activity log). Two cosmetic gaps to fix before
the demo video (W5):

1. **Raw user ids instead of names.** Case rows + activity lines render
   `<@U0BA67L9HRS>` literally — Slack canvas markdown does NOT resolve `<@id>`
   mention syntax the way chat messages do. Options: (a) resolve display names via
   `users.info` (cache per id; one lookup per distinct actor/offerer) and show the
   name, or (b) research whether canvas markdown has a mention syntax that resolves.
   Investigate (a) is most reliable. Best-effort — fall back to the id on lookup
   failure.
2. **Raw audit target `offer:<uuid>` in the activity log.** Show the human resource
   instead (e.g. "connected the camp-beds offer"). The board composer already
   receives the offers list, so `_activity_line` can resolve an `offer:<uuid>`
   target against it and render the resource_type; fall back to the bare target if
   the offer isn't found.

Both are pure-composition changes in coordinator/board.py (+ a names helper for #1).
Keep the sourcing/verify guardrails intact. Unit-test the name resolution + target
humanization with mocked lookups.

## Log
