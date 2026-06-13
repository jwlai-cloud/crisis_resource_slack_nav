# 022 — Slack-native UX: crisis suggested prompts + branded App Home dashboard

Targets the Design / Best-UX prize. Two surfaces are still the generic starter
template and are the FIRST things a user/judge sees. Make them distinctly
crisis-domain and well-crafted Slack-native UX.

## Part A — Crisis suggested prompts (assistant surface)
`listeners/events/assistant_thread_started.py` currently sets the template trio
("Write a Message" / "Summarize" / "Brainstorm"). Replace with scenario-relevant
prompts that teach the agent's value in one glance, e.g.:
- "Family of 4, North Exmouth, no power — need water and a generator"
- "I can offer a spare room in Exmouth town"
- "Is the road to Learmonth open?"
- (one more: a resolved-case / coordinator angle if a 4th fits)
Update the greeting title to something calm + on-brand (e.g. "What do you need? Tell
me in plain language."). Keep it warm but crisis-appropriate (matches the system
prompt persona).

## Part B — Branded App Home dashboard
`listeners/views/app_home_builder.py` is the generic "I'm your Slack assistant" home.
Rebuild it as a Crisis Resource Navigator dashboard:
1. Branded header + one-line what-it-does.
2. "How to use" — post a need or an offer in plain language; tap to connect; a human
   always confirms (the bounded-autonomy guardrail stated as a feature).
3. A "Current situation" summary — reuse `coordinator.situation.read_situation()`
   (best-effort) to show a compact road/water/evac snapshot, feed-stamped + verify
   note. Degraded feed named, never silent (guardrail 4).
4. A link to the live **coordinator board** — best-effort read of the canvas id via
   `coordinator.canvas_store.load_canvas_id()`; render an "Open the cases board"
   link when present, omit cleanly when not.
5. Drop / reframe the template's MCP-connection status block (it assumes OAuth mode;
   in socket-mode it's noise). Keep the home useful, not a status dump.
Every external/situation item keeps source + verify framing (guardrails hold on the
Home tab too).

## Acceptance criteria
1. Crisis suggested prompts + greeting title (Part A); the generic trio is gone.
2. App Home renders the branded dashboard (Part B) with how-to, the human-confirms
   note, a best-effort situation summary, and a best-effort board link. Pure
   block-builder where possible; the situation/canvas reads happen in the
   app_home_opened handler (the impure boundary) and degrade silently on failure —
   a Home render must never crash (it's the first impression).
3. manifest assistant_description stays crisis-framed (already is) — tweak only if it
   improves clarity. If suggested_prompts static fallback in manifest helps, set it
   too (the dynamic listener is the live path).
4. Tests: suggested-prompts content; app-home block structure (header + how-to +
   human-confirms + situation section present/degraded + board-link present/absent),
   situation + canvas reads mocked. Existing app-home tests updated. filterwarnings
   =error, zero warnings.
5. [HUMAN] live: open the app's Home tab → branded dashboard; open a new assistant
   thread → crisis prompts shown.

## Out of scope
Match-card colored-bar restyle (separate; streaming-API constrained). Canvas visual
restyle (020 covers content). Any model/prompt change.

## Log
