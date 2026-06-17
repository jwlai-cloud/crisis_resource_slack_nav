#!/usr/bin/env bash
# Container entrypoint — start the persistent mock MCP server, then the agent (task 034).
#
# Why two processes in one container: the mock official-directories MCP server
# (mocks/server.py) used to be spawned per reply over stdio. On the constrained
# free-tier e2-micro the cold FastMCP import (~5-12s) blew past the MCP init timeout
# and hung the whole reply. Here we import it ONCE at container start and serve it
# persistently over HTTP on localhost, so every reply reaches a warm, long-lived
# server (agent/agent.py connects via MCPServerStreamableHTTP when MOCK_MCP_URL is set).
#
# Localhost only: the HTTP mock is reached solely by app.py in THIS container — there
# is no inbound port to the box (socket mode is an outbound websocket to Slack). With
# --container-restart-policy=always, a crash of either process restarts the container.
#
# bash (Debian slim ships /bin/bash): -e exit on error, -u error on unset var,
# pipefail so a failure anywhere in a pipe is not masked.
set -euo pipefail

MOCK_MCP_HTTP_PORT="${MOCK_MCP_HTTP_PORT:-8765}"
export MOCK_MCP_HTTP_PORT

echo ">> Starting persistent mock MCP server over HTTP on 127.0.0.1:${MOCK_MCP_HTTP_PORT}"
python -m mocks.server &
MOCK_PID=$!

# If the agent exits, take the mock server down with it (and vice versa via the
# container restart policy) so we never leave an orphan holding the port.
trap 'kill "$MOCK_PID" 2>/dev/null || true' EXIT INT TERM

# Wait for the mock server to bind the port before the agent connects. A plain TCP
# connect check via Python (no curl/nc dependency in the slim image); ~30s budget.
echo ">> Waiting for the mock MCP server to bind…"
i=0
until python -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1', int('${MOCK_MCP_HTTP_PORT}')))==0 else 1)"; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: mock MCP server did not bind 127.0.0.1:${MOCK_MCP_HTTP_PORT} within 30s." >&2
    exit 1
  fi
  # Also fail fast if the background server already died.
  if ! kill -0 "$MOCK_PID" 2>/dev/null; then
    echo "ERROR: mock MCP server process exited before binding." >&2
    exit 1
  fi
  sleep 1
done

MOCK_MCP_URL="http://127.0.0.1:${MOCK_MCP_HTTP_PORT}/mcp"
export MOCK_MCP_URL
echo ">> Mock MCP server is up; agent will connect to ${MOCK_MCP_URL}"

echo ">> Starting the agent (socket mode) — exec app.py"
exec python app.py
