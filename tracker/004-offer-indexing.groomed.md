# 004 — Offer indexing on post

When a volunteer posts an offer ("I've got a spare 2kW generator in town"), the agent acknowledges it, parses it into an `Offer`, and indexes it so future needs match fast.

## Acceptance criteria

1. Thin in-memory index keyed by offer id, holding parsed `Offer` rows (design doc keeps it light; the workspace via RTS remains the durable store). Decision + trade-off recorded as an ADR (matching-index location — flagged in HANDOFF and CLAUDE.md as ADR-worthy).
2. Message listener routing: offer-shaped messages → parse (002) → index → acknowledge with a short confirmation (sourced, timestamped) — acknowledgement is informational, no actions.
3. Need handling (003) consults the index first, then RTS — both sets merged in ranking.
4. Index survives nothing (process-local) — restart behavior documented; explicitly fine for the demo.
5. Unit tests: index add/lookup/status transitions; listener routing mocked.
6. Live verification: post an offer, then a matching need — reply surfaces the indexed offer.

## Out of scope

Persistence, Canvas board (W4), Connect/Resolve buttons (W3).

## Log
