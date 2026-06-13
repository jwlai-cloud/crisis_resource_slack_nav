# 020 — Situation section on the coordinator board

The coordinator Canvas (017) shows community cases + audit log. Add a "Situation"
section rendering the current official picture (road closures / water points / evac
centres) from the mock MCP feeds, each feed-stamped (feed + fetched-at) with the
verify note — the shared official-info artifact the design doc's coordinator beat
implies, so residents' replies can point to it instead of repeating the full dump.

Direction:
1. The board composer gains a situation section sourced from the official feeds.
   The feeds live in mocks/ (road_closures/evac_centres/official_advice JSON via the
   FastMCP tools). The board reads them directly (the JSON loader, not an MCP round
   trip) at compose time — keep board.py pure by passing the situation data in from
   the canvas.py boundary (mirrors the names dict pattern from 019).
2. Every situation row carries feed + fetched-at + verify note (guardrail 3/4).
3. Optional: replies end with a one-line pointer to the board for the full picture
   (pairs with 012's pruning).
4. Tests: situation composition (feed-stamped rows, empty/degraded feed), board
   stays pure. Mock the feed loader. Zero warnings.
5. [HUMAN] live: board shows a Situation section with the Narelle road/water/evac
   data, feed-stamped.

Depends on 017 (board) + 012 (pruning makes the pointer meaningful). W4/W5 polish.

## Log
