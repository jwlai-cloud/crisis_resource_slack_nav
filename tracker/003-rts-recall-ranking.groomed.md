# 003 — RTS recall + ranking

When the agent handles a need, search the workspace for relevant prior offers and coordinator notices via the Real-Time Search API, rank them, and compose a sourced, timestamped Block Kit reply.

## Pre-work (SWE: research before coding)

The RTS API is new — verify the actual API surface (endpoint names, token type, slack_sdk support) against current docs (context7 / docs.slack.dev) before writing code. Manifest already carries the `search:read.*` user scopes. Record findings in this Log; if the integration shape forks from the design doc's assumption (user-token search calls from the agent), write an ADR.

## Acceptance criteria

1. A search module that queries RTS for messages matching the parsed need (resource_type/location keywords) and returns typed results: text, author, channel, ts, permalink.
2. Ranking: recency + keyword overlap with the need's structured fields (simple scoring fine — CPU-bound, sync, unit-tested).
3. Reply is composed Block Kit: each match shows source (author, channel) + timestamp + permalink + "verify before relying on this" note. No bare text dumps.
4. Degraded state explicit: RTS error/empty → reply says "couldn't search the workspace right now" / "no prior offers found" — never silent.
5. Unit tests: ranking table-driven; composition snapshot of Block Kit payload; RTS client mocked.
6. Live verification: seed sandbox #general with 2 offers, post a need, agent reply surfaces the matching offer with source + ts.

## Out of scope

MCP external sources (W3), action buttons (W3), Canvas (W4).

## Log
