# Crisis Resource Navigator — Demo Video Script

*Target length: ~3:00 · Slack Agent Builder Challenge*

**Recording principles**
- The first 60 seconds must be the working product solving the real scenario. No title cards longer than 3 seconds, no architecture talk up front.
- **Pre-seed + warm up before recording** (so matching has something to find):
  1. Confirm the **deployed VM agent is live**. Do **NOT** start a local `slack run` while the VM is up — two agents share the app token and Slack splits events → double replies on camera. One instance only.
  2. `make seed-demo ARGS=--fresh` — posts the realistic offers + SES/DFES notices; the live VM agent indexes each as it lands (organic indexing).
  3. The **Community Cases** tab already exists (the VM agent creates it on startup) — just open it. Skip a local `make board ARGS=--fresh`; it can fail on a stale canvas id.
  4. Wait ~60 s so the Real-Time Search index catches up before you post the hero need.
- Record the agent on the **native agent surface / the crisis channel** at a clean zoom so Block Kit blocks, sources, and timestamps are legible on a laptop.
- Speak to the screen action; let the agent's output carry it. Don't narrate the UI.

---

| Time | On screen | Voiceover |
|------|-----------|-----------|
| **0:00–0:10** | 2–3 s of real Narelle headlines ("Cyclone Narelle isolates Exmouth — only road cut"), then hard cut into the Slack workspace. | "In March, Cyclone Narelle cut Exmouth off from the world. One road, gone. Power and water, down. And like most emergencies — the coordination happened in a group chat." |
| **0:10–0:22** | Scroll the noisy `#exmouth-mutual-aid` channel: offers, needs, official notices tangled together, scrolling past. | "Offers, needs, official updates — all scrolling past each other. The family that needs a generator never sees that someone two streets over offered one an hour ago." |
| **0:22–0:50** | In the channel, **post the need as a plain message** (no command, no mention): *"Family of 4 in North Exmouth, no power — need water and a generator."* The agent replies **in a thread**: a parsed-fields block (need_type / location / urgency / household), then a ranked match. | "Crisis Resource Navigator listens in the channel. A resident just types what they need, in plain language — and the agent reasons over it: what's needed, where, how urgent. Then it does two things at once." |
| **0:50–1:15** | Highlight the **🟩 workspace match card** (the generator offer — who posted it, when) and the **"Official information"** section: a **🟦 card** for the open water point, each line stamped `feed · fetched <UTC>` and carrying a verify note. | "First — using Real-Time Search — it finds what the workspace already knows: Jo offered a generator, hours ago, nearby. Second — through an MCP server — it pulls the official picture: the open water point, from a DFES-style directory. Every item is sourced and timestamped. Nothing invented." |
| **1:15–1:35** | Post a second message: *"Is the road to Learmonth safe to drive?"* The agent replies: an explicit **"I can't tell you whether it's safe"** line, then a **🟥 OFFICIAL · ADVISORY** card relaying *Minilya-Exmouth Rd — CLOSED* verbatim + verify note. | "Ask it the hard question and watch what it refuses to do. It will not tell you a road is safe — it doesn't make that call. It gives you the official status, sourced, and leaves the decision to a human. When the stakes are this high, that restraint is the feature." |
| **1:35–1:55** | Back on the need reply, tap **Connect me** → a DM to the offerer fires. Tap **Mark resolved** → the card flips. | "The agent surfaces and ranks — a person decides. One tap opens a DM to the offerer. One tap marks it resolved. Every actionable match ends at a human's button — never an automatic action." |
| **1:55–2:20** | Click the **Community Cases** tab in the channel's top bar: the board — cases grouped **Open / Connected / Resolved**, the dated **activity log** of confirmed actions, and the official **Situation** section. | "Coordinators get a permanent board — every case by status, a timestamped log of every confirmed action, and the current official situation. A record of what humans did, not advice." |
| **2:20–2:40** | Post a *second, similar* need (another family needing power/water). The agent answers noticeably faster, surfacing the still-relevant offers / the earlier case. | "And it compounds. A second family posts a similar need — and because the workspace remembers, the agent answers faster. The longer the crisis runs, the better the community gets at helping itself." |
| **2:40–2:55** | Quick cut to the architecture diagram; point to the three labelled layers. | "Under the hood: Slack AI reasons, Real-Time Search remembers, and MCP reaches out to live external data. All three challenge technologies — each doing real work." |
| **2:55–3:00** | Back to the workspace; the Community Cases board on screen. End card: project name + track. | "Crisis Resource Navigator. When a community gets cut off, Slack becomes the relief operation." |

---

## Shot checklist (capture before editing)

- Real Narelle headline(s) — screenshot or brief screen-record.
- Noisy channel scroll (the "before").
- Need posted in-channel → agent's threaded reply: parsed fields + 🟩 workspace match card + 🟦 official water card, sources + timestamps visible.
- Safety question → refusal line + 🟥 road-closure advisory card.
- Connect me → DM firing. Mark resolved → card flips.
- The **Community Cases** top-bar tab: cases by status + activity log + situation.
- Second similar need answered faster.
- Architecture diagram (the SVG).
- Clean end card.
- *(Optional B-roll: the branded App Home tab and the crisis suggested prompts on a new thread — strong for the Design score if you have time.)*

## Notes
- **Never claim live government feeds.** The MCP *integration* is real (Slack's MCP server + our own FastMCP directory servers); the *data* is simulated static JSON because live Main Roads WA / DFES feeds aren't public. Say "a DFES-**style** directory" / "official-style data via MCP", never "the live DFES feed". The integration pattern is what's judged.
- The four guardrails are the spine of the demo — make sure the **refusal beat (1:15)** and the **human-confirms beat (1:35)** both land on camera; they're what separates this from a chatbot.
- If a live action stalls on camera, re-run it — don't talk over a spinner. Judges read hesitation as fragility.
- Keep total VO under ~430 words; at a calm pace that lands around 3:00 with room for the action beats to breathe.
- Caption the sources on screen (small text is fine) even as you say them — reviewers often watch muted on a first pass.
- The four live screenshots in `docs/site/img/` (need / safety / board / app-home) mirror these beats — reuse them for thumbnails or stills.
