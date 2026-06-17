# Crisis Resource Navigator — always-on socket-mode worker image (multi-stage).
#
# Socket mode opens an OUTBOUND websocket to Slack (no inbound HTTP), so this is a
# long-running worker — no port to EXPOSE, no health endpoint. The same interpreter
# that runs app.py also spawns `python -m mocks.server` as a stdio MCP subprocess
# (agent/agent.py:_mock_mcp_server), so the WHOLE repo + the locked runtime venv must
# be present. Deploy targets: Fly.io or a GCE e2-micro (see deploy/README.md).
#
# Two stages keep the runtime small: the builder owns uv + the build, the runtime
# carries only the resolved venv + the source. This drops the uv binary, the apt
# build tooling, and (critically) the chown-the-world layer that otherwise duplicated
# the whole venv into a second image layer.

# ---- builder: resolve the locked venv with uv -------------------------------
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
# Runtime deps only, against the committed lockfile. --frozen: never re-resolve.
# --no-dev: drop pytest/ruff/pre-commit. --no-install-project: package=false, nothing
# to install — we run from source, copied into the runtime stage below.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- runtime: clean slim image, no uv, no build tooling ---------------------
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"
WORKDIR /app

# Non-root user created BEFORE the copies so --chown sets ownership inline — no
# separate `chown -R /app` RUN layer (that duplicated the ~320 MB venv).
RUN useradd --create-home --uid 10001 crn

# The resolved venv from the builder, then the source (app.py, agent/, listeners/,
# mocks/ + its JSON, coordinator/, recall/, matching/, entities/, scripts/, manifest).
# .dockerignore keeps tests/docs/.git/secrets out of the source copy.
COPY --from=builder --chown=crn:crn /app/.venv /app/.venv
COPY --chown=crn:crn . .

USER crn

# Socket-mode entry point: the venv's python (on PATH) execs app.py, which opens the
# Slack websocket via SocketModeHandler.start(). No `uv run` at runtime — the env is
# already baked, and the mock-MCP subprocess uses this same interpreter (sys.executable).
CMD ["python", "app.py"]
