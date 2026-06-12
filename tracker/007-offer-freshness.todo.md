# 007 — Offer freshness: re-confirmation + staleness signals

Reality gap (user-raised, 2026-06-12): offers get taken via side channels — requester contacts the offerer directly and nobody tells the agent. The index then surfaces stale offers.

Existing mitigations (by design, keep): every match is a sourced, timestamped lead with a verify note — never an availability promise; 7-day recency decay buries untouched offers; W3 adds one-tap Mark-resolved; W4 Canvas gives the coordinator a sweepable board.

Proposed additions (groom before building — likely W4 or post-v1):
1. Offers older than N days (configurable) trigger one agent DM to the offerer: "Is this still available?" One re-confirmation per offer, never nagging.
2. Unconfirmed-stale offers render with an explicit "unconfirmed for X days" tag in match blocks (degraded-state guardrail applied to data freshness) and take a rank penalty.
3. Offerer reply ("yes"/"gone") updates status; "gone" → resolved, removed from lookup.

Out of scope: hard deletion, inventory counts, reservations — the agent surfaces and a human decides; it does not bookkeep stock.

## Log

Addendum (same conversation): no hard age cutoff exists — recency shapes rank (7-day linear decay, weight 0.3), never inclusion. Keep it that way (silent exclusion would violate the explicit-degradation posture), but add relative age ("posted 2h ago") next to the absolute timestamp in match blocks, and consider a configurable cutoff only if real noise demands it.
