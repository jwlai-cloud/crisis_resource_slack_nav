# 033 — Deploy artifacts: one image, Fly OR GCE micro, chosen by a script

W5 needs the socket-mode agent always-on so judges can poke the sandbox during review
(submission requirement #1 "working app in the sandbox" + member access; the video
carries the scored demo). Socket mode = an OUTBOUND websocket, NO inbound HTTP, so it
needs an always-on worker (not Cloud Run scale-to-zero). Prep the artifacts NOW;
actual deploy is W5 (don't burn a month of idle cost). Support BOTH targets, chosen by
one script: **Fly.io** (~$2-5/mo, ~20-min) and **GCE e2-micro** (free-tier, more setup).

## Design decisions (locked)
- **One Dockerfile, both targets.** uv-based, Python 3.13-slim, `uv sync --frozen`,
  copies the WHOLE repo (the agent spawns `python -m mocks.server` as an MCP stdio
  subprocess — the image must run it), non-root user, `CMD ["uv","run","python","app.py"]`
  (socket mode). No EXPOSE / no port (worker). `.dockerignore` excludes `.venv .git
  __pycache__ tests docs .slack *.png` etc.
- **`deploy/deploy.sh [fly|gce]`** is the single entry; **defaults to `gce`** when no
  target is given (user's call 2026-06-13). It validates the target arg and routes.
  Reads secrets from a gitignored `deploy/.env.deploy` (NEVER committed) —
  template `deploy/.env.deploy.example` lists every var with a dummy:
  `SLACK_BOT_TOKEN SLACK_APP_TOKEN GOOGLE_VERTEX_API_KEY SLACK_USER_TOKEN CRISIS_CHANNEL
  COORDINATOR_CHANNEL BACKFILL_ON_START`. (Vertex express-mode key works on any cloud —
  no GCP-native auth needed, so Fly is fine.)
- **Fly path:** `deploy/fly.toml` — a worker app (no `[http_service]`, no ports;
  `auto_stop_machines=false`, `min_machines_running=1`, shared-cpu-1x 256-512MB).
  `deploy.sh fly`: `fly secrets import < deploy/.env.deploy` then `fly deploy`
  (assumes a one-time `fly launch --no-deploy` / app created — document it). Restart is
  Fly-managed.
- **GCE path:** `deploy.sh gce` builds + pushes the image to the user's Artifact
  Registry, then `gcloud compute instances create-with-container` an **e2-micro** in a
  **free-tier region** (default `us-central1`, overridable) with the env vars and a
  **startup-script** (`deploy/gce-startup.sh`) that adds a **1-2 GB swap file** (the 1 GB
  RAM insurance) and relies on COS's container auto-restart. Document the create vs
  update (re-deploy) commands. Always-free caveats noted in the README (1 e2-micro per
  BILLING ACCOUNT, free regions only, card-on-file required).
- **`BACKFILL_ON_START=true`** is the recommended deploy default (so the in-memory index
  repopulates from history after any restart) — set in `.env.deploy.example`.
- **Secrets never committed.** `deploy/.env.deploy` gitignored; only the `.example`
  committed. The script must fail loudly if `.env.deploy` is missing/incomplete.
- **No app code change.** `app.py` (socket mode) is unchanged. (`app_oauth.py` HTTP mode
  is NOT used — out of scope; a note in the README explains why socket mode → worker.)
- **Optional Makefile target** `deploy: ; ./deploy/deploy.sh $(TARGET)` with
  `TARGET ?= gce` (so bare `make deploy` → GCE; `make deploy TARGET=fly` for Fly).

## Acceptance criteria
1. [ ] A single `Dockerfile` builds a working image: `docker build` succeeds; the image
   runs `app.py` (socket mode) and can spawn `python -m mocks.server`. — Tester runs
   `docker build` (Docker/orbstack is available) and confirms a clean build; a smoke
   `docker run` with dummy env fails fast on auth (expected) NOT on import/2 missing files.
2. [ ] `.dockerignore` excludes venv/git/tests/docs/secrets; the build context is lean.
3. [ ] `deploy/deploy.sh <fly|gce>` validates the target (errors on a bad/missing arg),
   loads `deploy/.env.deploy` (errors loudly if absent/incomplete), and routes to the
   right path. — Tester runs it with a bad arg (→ usage error, exit≠0) and with a
   missing `.env.deploy` (→ clear error), WITHOUT performing a real deploy (no creds).
4. [ ] `deploy/fly.toml` is a valid worker config (no public port, min 1 machine,
   restart-on-crash). `deploy/gce-startup.sh` adds swap + is shell-lint clean.
5. [ ] `deploy/.env.deploy.example` lists every required var (dummy values);
   `deploy/.env.deploy` is gitignored (add to `.gitignore`); no real secret is committed.
6. [ ] `deploy/README.md`: prereqs (fly CLI auth / `gcloud auth` + Artifact Registry),
   the one-time setup, the one-command deploy for each target, the W5 timing note, the
   GCE always-free caveats (per-billing-account, free regions, card-on-file, e2-micro 1GB
   + swap), and "deploy in early July, tear down after review."
7. [ ] Optional `make deploy TARGET=fly|gce` wired (passthrough).
8. [ ] `make pre-commit` + unit + integration still green, zero warnings (no app change;
   the new files are config/scripts/docs — confirm nothing breaks ruff/pytest).
9. [ ] [HUMAN] Live deploy in W5 (fly/gce) — left unchecked; the artifacts make it
   push-button.

## Out of scope
- Actually running a live deploy (W5, needs the user's creds).
- HTTP/OAuth mode (`app_oauth.py`), Cloud Run, scale-to-zero (documented why not).
- CI deploy automation (manual `deploy.sh` for the demo is enough).

## Notes for SWE
- Docker IS available locally (orbstack) — build to verify. Keep the image small (slim +
  `uv sync --frozen --no-dev`).
- shellcheck the scripts if available; otherwise keep them POSIX-simple + `set -euo pipefail`.
- Don't break the existing Makefile/`uv` flow; the deploy target is additive.

## Log
- SWE died mid-run (API socket error) after writing Dockerfile/.dockerignore/fly.toml/.env.deploy.example. Orchestrator completed the rest (deploy.sh default-gce + target/secret guards, gce-startup.sh best-effort swap, README, .gitignore negation for the template, Makefile `deploy` TARGET?=gce).
- Self-verified (SWE pipeline flaky this session): `docker build` SUCCEEDS; `deploy.sh badarg`→exit 2 usage, `deploy.sh gce` w/o .env.deploy→exit 1 clear error; shellcheck clean; template committable + real .env.deploy ignored; `make pre-commit` 512 unit + 5 integration green, zero warnings. AC9 (live deploy) = W5 [HUMAN].
