# 008 — Match-card visual parity with the landing page mock

The landing page demo (docs/site/index.html) renders the target reply UX; live replies should match it. User-confirmed direction (2026-06-12). Build alongside / right after the W3 action buttons since the buttons live on these cards.

Gap to close:
1. Parse summary as structured fields — section block with `fields` (need_type / location / urgency / household) instead of LLM prose bullets. Composed by code from the parsed Need, not by the model.
2. Match cards with colored left bar — use message `attachments` (color: green workspace / blue official MCP / red advisory), one attachment per match, blocks inside. Attachments are legacy-but-supported and the only way to get the color bar.
3. Rank label context line per card: `MATCH n · WORKSPACE · REAL-TIME SEARCH` / `· OFFICIAL · MCP FEED`.
4. Action buttons on workspace matches: Connect me / Not relevant (W3 actions task wires the handlers; this task owns the visual placement).
5. Keep: source/ts/permalink/contact/verify line (already live), single streamed reply (005).

Acceptance: side-by-side screenshot of landing-page card vs live Slack card — recognisably the same design.

## Log
