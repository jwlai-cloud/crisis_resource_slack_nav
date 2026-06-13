# 018 — Coordinator board discoverability + cross-process canvas id

Gap surfaced landing 017 (SWE flagged it honestly): the standalone `make board`
script and the live agent each hold a process-local CoordinatorBoard.canvas_id, so
a script-created canvas is NOT the one the server updates on button actions — the
server lazily creates its OWN canvas on first action, which nobody has a link to.

Fix direction (small, demo-critical for the W4/W5 coordinator beat):
1. Persist the canvas id to a known location both processes read/write — e.g. a
   gitignored `.slack/board_canvas_id` file (or a tiny settings entry). publish()
   reads it on first call; create writes it. Both `make board` and the server then
   operate on the SAME canvas.
2. Discoverability: on server startup (app.py) OR on board creation, post the
   canvas permalink once to the designated coordinator channel (CRISIS_CHANNEL or a
   new COORDINATOR_CHANNEL) so a coordinator can open it. Idempotent — announce once.
3. Update scripts/open_board.py + README/CLAUDE.md so `make board` is the single
   "mint + announce" entry and the server reuses it.

Demo impact: without this the coordinator Canvas beat (demo 1:45–2:10) is awkward to
stage. Do before the video (W5), ideally in W4 right after 017.

## Log
