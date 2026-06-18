# Live demo screenshots

Drop the real Slack screenshots here to fill the landing page's **Live** panel
(`docs/site/index.html`, the Concept ↔ Live toggle, task 028 / ADR-0007). Until a
file exists its slot shows a visible "screenshot pending" placeholder — the page is
valid before the PNGs land.

The Live side is **real Slack screenshots only** — never a re-rendered "realistic"
mockup. The Concept animation stays the explainer.

Expected files (PNG):

- `live-need.png` — a resident posts a water + generator need in the crisis channel;
  the reply shows a workspace match card (🟩) and an "Official information" water-point
  card (🟦), each sourced + UTC-stamped, with the human-confirm button.
- `live-safety.png` — "is the road to Learmonth safe?" → the agent refuses to judge
  safety and surfaces the road-closure advisory card (🟥) verbatim + verify note.
- `live-board.png` — the coordinator board Canvas: cases by status, the
  human-confirmed activity log, and the official Situation section.
