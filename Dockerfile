# Crisis Resource Navigator — always-on socket-mode worker image.
#
# Socket mode opens an OUTBOUND websocket to Slack (no inbound HTTP), so this is a
# long-running worker — there is no port to EXPOSE and no health endpoint. The same
# interpreter that runs app.py also spawns `python -m mocks.server` as a stdio MCP
# subprocess (agent/agent.py:_mock_mcp_server), so the WHOLE repo is copied and the
# locked runtime deps must be present. Deploy targets: Fly.io or a GCE e2-micro
# (see deploy/README.md). Built once, run on either.

FROM python:3.13-slim

# uv is the only package manager (CLAUDE.md). Pull the static binary from the
# official distroless image — no pip bootstrap, pinned by digest-able tag.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime deps first, against the committed lockfile only, so this layer
# caches across code-only changes. --frozen: never re-resolve (fail if the lock is
# stale). --no-dev: drop pytest/ruff/pre-commit (the [dependency-groups] dev group).
# --no-install-project: this repo is package=false; there is nothing to install.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the whole repo: app.py, agent/, listeners/, mocks/ (+ its static JSON),
# coordinator/, recall/, matching/, entities/, scripts/, manifest.json. The mock
# MCP subprocess (`python -m mocks.server`) and BACKFILL need them all at runtime.
COPY . .

# Run as a non-root user. Create it after the copy so it owns nothing it shouldn't;
# the venv + code are world-readable, which is all the worker needs.
RUN useradd --create-home --uid 10001 crn \
    && chown -R crn:crn /app
USER crn

# Put the project venv on PATH so `python` resolves to the locked interpreter even
# without `uv run` wrapping it.
ENV PATH="/app/.venv/bin:${PATH}"

# Socket-mode entry point. `uv run` re-checks the (frozen) environment and execs
# app.py, which opens the Slack websocket via SocketModeHandler.start().
CMD ["uv", "run", "--frozen", "--no-dev", "python", "app.py"]
