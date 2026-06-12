# HANDOFF — design → build

Bridge from the design phase (done in chat) into the Claude Code build sessions. One-time read; once you're a session or two in, `CLAUDE.md` + the design doc are what matter.

---

## Kickoff prompt (paste into the first Claude Code session)

> You're working in the `crisis_resource_slack_nav` repo on the `dev` branch. Read `CLAUDE.md` and `crisis_resource_navigator_design_doc.md` first — the design doc is the source of truth for scope and architecture.
>
> This is a Slack agent for the Slack Agent Builder Challenge (deadline 2026-07-13), "for Good" track. The conceptual design is settled; we're now building.
>
> Goal for this session — **Week 1 of the build plan**: scaffold the agent with `slack create agent`, get it responding in-thread on the agent surface, and render a minimal Block Kit reply skeleton. Don't build matching, RTS, or MCP yet.
>
> Before writing code: confirm the Slack CLI is installed and the sandbox is provisioned, walk me through the scaffold options, and check that `.env` is gitignored. After scaffolding, update the "Commands" section of `CLAUDE.md` with the real run commands. Keep commits small and tied to the milestone.
>
> Flag anything that conflicts with the design doc before acting.

---

## Where we are

**Design phase: complete.** Problem, solution, architecture, three-tech mapping, build plan, demo script, and abstract are all written and committed.

**Build phase: W1 done (2026-06-12).** Sandbox `crisis-resource-nav` (Team `E0B9Z77AX2R`) provisioned via Developer Program (work-identity eligibility, no card). App scaffolded from the pydantic-ai starter-agent template, installed to the sandbox as "Crisis Resource Navigator (local)" (App `A0B9ZKSDZ9B`), and verified live: message in → Gemini reasoning → reply + emoji-reaction tool call + feedback buttons. Gemini via `GEMINI_API_KEY` (free tier; transient 503s observed — graceful degraded-state handling is W4). W2 done (2026-06-12, same day): tasks 001-005 — crisis system prompt with guardrail
regression net, typed Need/Offer/Resolution core + structured parsing, RTS recall with
domain ranking and explicit degraded states, in-memory offer index (ADR-0003), unified
single-reply UX with contact mentions. All live-verified; 13 bugs found and fixed in
live testing. Gemini now runs via Vertex AI express mode (no free-tier caps). Stage PR:
https://github.com/jwlai-cloud/crisis_resource_slack_nav/pull/1. W3 done (2026-06-12, same day): tasks 008-010 — mock MCP servers (FastMCP, stdio,
Narelle scenario feeds with structured degraded states), Connect / Mark resolved /
Not relevant action buttons (group DM intro, index locking, audit-trail seed), and
match-card visual parity with the landing page. All live-verified. Backlog groomed:
006/007/011/012/013/014. Next: **W4 — coordinator Canvas + situation board,
persistence decision (statuses + audit), seed data via task 013, polish.**

## Artifacts in the repo

- `crisis_resource_navigator_design_doc.md` — source of truth.
- `crisis_resource_navigator_architecture.svg` — architecture diagram (already on `dev`).
- `crisis_resource_navigator_demo_script.md` — 3-min video script.
- `CLAUDE.md` — standing context for Claude Code.
- `HANDOFF.md` — this file.

## Decided (don't relitigate without reason)

- Track: Slack Agent for Good. (Not Organizations — that needs Marketplace submission, more overhead.)
- All three required techs used, each load-bearing: Slack AI = reasoning/interface, RTS = workspace memory, MCP = external data.
- MCP servers are thin mocks for the demo, not real feeds.
- Language: Python + Bolt.
- Scenario: Exmouth / Cyclone Narelle.
- Safety posture: surface-and-rank, human confirms, never assert safety, always source. (See CLAUDE.md guardrails.)

## Build order (from the design doc plan)

1. **W1 — Foundation:** scaffold; agent responds on the surface; Block Kit skeleton. ← start here
2. **W2 — Reasoning + RTS:** parse need/offer into structured fields; RTS recall + ranking; index offers on post.
3. **W3 — MCP + actions:** mock MCP servers; action buttons (Connect / Mark resolved / Escalate / Log) end-to-end.
4. **W4 — Polish + safety:** coordinator Canvas + audit log; sourcing/timestamps/verify framing; bounded-autonomy confirm; seed Exmouth data.
5. **W5 — Demo + submit:** record video, finalize diagram + write-up, grant sandbox access to required reviewer emails, submit.

## Submission requirements (from hackathon welcome email, 2026-06-11)

Deadline: **July 13, 2026, 5:00 PM PT** (editable until then). Every submission needs:

- Working Slack app installed in the developer sandbox.
- Text description (what it does + impact).
- ~3-min demo video, public on YouTube or Vimeo.
- Architecture diagram uploaded via Devpost file upload.
- Sandbox URL with **Member access granted to `slackhack@salesforce.com` and `testing@devpost.com`**.

Do early: open the Devpost submission form now (no finished project needed); join `#slack-agent-builder-challenge`.

## Open items to resolve early (not blockers, but do them soon)

- Confirm sandbox is live and you can `slack run` a hello-world agent before investing in structure.
- Decide the thin matching index location (in-memory for the demo vs. a small store) — design doc keeps it light; pick the simplest that drives the Canvas.
- The agent **system prompt** (enforcing the loop + guardrails) isn't written yet. Best done in Claude Code so it's tested against live runs — pick it up at the start of W2, or earlier if you want the skeleton to feel real.

## Still open to do in chat (not code)

- Block Kit response mockup + one-page UX spec (cold-start / working / results / confirm / error states). Can be done here or generated as files in Claude Code — lean Claude Code since you'll render and tweak live.
- Devpost write-up polish.
- Competitive/Marketplace pressure-test, if you want it before committing more time.
