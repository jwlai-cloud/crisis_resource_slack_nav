# Deploy — always-on socket-mode worker

The agent runs in **Socket Mode**: it opens an **outbound** WebSocket to Slack and
Slack pushes events down it. There is **no inbound HTTP**, so it must run as a
**long-lived worker**, not a request-driven / scale-to-zero service (that's why Cloud
Run min-0 doesn't work — nothing inbound ever wakes it; a stopped instance just drops
the socket and the agent goes silent).

One image, two targets, chosen by the script:

```sh
make deploy                 # → GCE e2-micro (default)
make deploy TARGET=fly      # → Fly.io
# or directly:
deploy/deploy.sh [gce|fly]  # default: gce
```

> **Timing (W5):** these artifacts are prepped now; **deploy in early July**, keep it
> up through the judges' review window, then tear it down. Standing it up a month
> early just burns idle cost.

## How the sandbox connects to the deployed agent

It doesn't — **the agent connects out to Slack**, not the other way around. There is
no inbound URL to configure and nothing to re-point in the sandbox:

1. On the VM/Fly, `app.py` starts and `SocketModeHandler` calls `apps.connections.open`
   using `SLACK_APP_TOKEN` (the `xapp-…`, `connections:write` scope).
2. Slack returns a `wss://…` URL; the agent holds a **persistent outbound WebSocket**.
3. Slack **pushes every sandbox event down that socket** — to wherever the agent runs.

Deploying = running the **same `app.py` with the same tokens**, just on the VM instead
of your laptop. The app (already installed in the sandbox) is untouched; the socket is
the link. `deploy/.env.deploy` carries the tokens up.

### ⚠ Only ONE instance at a time

Two processes sharing the same app token open two sockets, and Slack then
**duplicates / splits events** (double replies, dropped messages). So:

- **When the VM goes live, stop the local `slack run`** (`pkill -f "slack run"`). The
  VM becomes the sole agent.
- **To test locally again,** stop the VM (`gcloud compute instances stop …`) or scale
  Fly to 0 (`fly scale count 0`), then `slack run`.

**Verify after deploy:** post a need in `#exmouth-mutual-aid` → a reply means the
deployed agent is live. No reply → check the container logs (`gcloud compute ssh … --
'sudo docker logs $(sudo docker ps -q)'` or `fly logs`) and that every secret is set.

## Secrets (both targets)

Copy the template and fill in real values — **never commit `deploy/.env.deploy`** (it's
gitignored):

```sh
cp deploy/.env.deploy.example deploy/.env.deploy
$EDITOR deploy/.env.deploy
```

Required: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `GOOGLE_VERTEX_API_KEY`,
`SLACK_USER_TOKEN`, `CRISIS_CHANNEL`. Optional: `COORDINATOR_CHANNEL`,
`BACKFILL_ON_START` (recommended `true` so the in-memory board repopulates from channel
history after any restart). The Vertex **express-mode** key works on any cloud — no
GCP-native auth needed — so Fly is fine too.

`deploy.sh` refuses to run if `deploy/.env.deploy` is missing or any required value is blank.

---

## GCE e2-micro (default — free tier)

Runs the container on a Container-Optimized OS VM with auto-restart.

**One-time setup**
1. `gcloud auth login` and select/create a project.
2. Create an Artifact Registry Docker repo (once):
   ```sh
   gcloud artifacts repositories create crn --repository-format=docker --location=us-central1
   gcloud auth configure-docker us-central1-docker.pkg.dev
   ```
3. Point the script at your image:
   ```sh
   export GCE_IMAGE=us-central1-docker.pkg.dev/<YOUR_PROJECT>/crn/crn:latest
   # optional: GCE_PROJECT, GCE_ZONE (default us-central1-a), GCE_INSTANCE
   ```

**Deploy / re-deploy**
```sh
make deploy            # builds, pushes, create-with-container (or updates if it exists)
```
Logs: `gcloud compute ssh crisis-resource-navigator --zone us-central1-a -- 'sudo docker logs $(sudo docker ps -q)'`
Tear down: `gcloud compute instances delete crisis-resource-navigator --zone us-central1-a`

**Always-free caveats**
- **1 e2-micro free per BILLING ACCOUNT** (not per project) — aggregated across all
  projects. A 2nd e2-micro anywhere under the account is billed (~$6–8/mo).
- **Free regions only:** `us-central1`, `us-west1`, `us-east1`. Outside → billed.
- A **card on file is required** even for the free tier (overages billed).
- **1 GB RAM** is plenty for this I/O-bound agent (~400 MB; the LLM compute is remote).
  The startup-script adds best-effort swap (a no-op on COS — harmless). If it ever
  OOMs, switch to **e2-small** (2 GB, ~$13/mo): `--machine-type e2-small`.
- `--container-env` carries the secrets into the VM's instance metadata. Fine for a
  short demo window; for a hardened deploy use Secret Manager instead.

---

## Fly.io (alternate, ~$2–5/mo)

**One-time setup**
```sh
fly auth login
fly launch --no-deploy --copy-config --dockerfile ../Dockerfile -c deploy/fly.toml
# (edit the `app` name in deploy/fly.toml if Fly assigned a different one)
```

**Deploy / re-deploy**
```sh
make deploy TARGET=fly   # imports secrets from .env.deploy, fly deploy, scales to 1 machine
```
Logs: `fly logs -c deploy/fly.toml` · Tear down: `fly apps destroy <app>`

Fly config is a pure worker (no `[http_service]`, no ports; one always-on machine,
restart-on-crash).

---

## Mock MCP server: persistent HTTP in the container

The mock official-directories MCP server (`mocks/server.py`) used to be spawned **per
reply** over stdio. On the constrained free-tier e2-micro the cold FastMCP import
(~5–12s) blew past the MCP init timeout and **hung the reply**. In the container the
`entrypoint.sh` instead runs it **persistently over HTTP on localhost** and points the
agent at it, so the import happens **once at startup** and every reply hits a warm
server (task 034):

1. `entrypoint.sh` sets `MOCK_MCP_HTTP_PORT` and starts `python -m mocks.server` in the
   background (it serves `transport="http"` on `127.0.0.1:<port>`).
2. It waits for the port to bind, then exports `MOCK_MCP_URL=http://127.0.0.1:<port>/mcp`.
3. It `exec`s `app.py`; `agent/agent.py` connects to that URL via
   `MCPServerStreamableHTTP` (same shape as the Slack MCP integration).

It's all automatic — **you don't set `MOCK_MCP_HTTP_PORT` / `MOCK_MCP_URL` yourself**.
Localhost only: there's no inbound port to the box (socket mode is an outbound
websocket). Local `slack run` is **unchanged** — it never uses this entrypoint, so it
stays on the zero-config stdio mock.

A flaky MCP source also no longer takes a reply down: if an MCP toolset can't be
reached the agent retries once without it and still composes the reply, and the
official cards (read directly, not via the toolset) still render — with an explicit
"couldn't reach the official directories" alert when the official picture is fully
unavailable.

## Files
- `../Dockerfile` / `../.dockerignore` — the shared worker image (uv, `--frozen --no-dev`,
  non-root; copies the whole repo so `python -m mocks.server` runs). Runtime `CMD` is
  `entrypoint.sh`.
- `entrypoint.sh` — container entrypoint (task 034): starts the persistent HTTP mock
  MCP server, waits for it to bind, then execs `app.py`. The only `deploy/` file baked
  into the image.
- `deploy.sh` — the entry point (default `gce`); validates target + secrets, routes.
- `fly.toml` — Fly worker config.
- `gce-startup.sh` — best-effort swap on the GCE host.
- `.env.deploy.example` — the secret template (real values go in the gitignored `.env.deploy`).
