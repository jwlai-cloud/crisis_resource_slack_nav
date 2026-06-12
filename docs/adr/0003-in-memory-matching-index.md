# 0003. In-memory matching index for parsed offers

**Status:** Accepted
**Date:** 2026-06-12

## Context

The agent parses each volunteer offer into a typed `Offer` (entities.models) and
needs to match later Needs against prior offers quickly. The design doc keeps the
matching layer "light" and the agent "mostly stateless, leaning on the workspace
as its store"; HANDOFF.md flags the open fork explicitly: **pick the matching
index location — in-memory for the demo vs. a small persistent store.**

Two forces pull against each other:

- **Latency / freshness.** An offer posted seconds ago should surface for a
  matching Need immediately. The Real-Time Search API has its own indexing lag,
  so an offer that was *just* posted may not yet be findable via RTS.
- **Durability.** The matching state must not be the single point of truth for
  what offers exist — losing it must not lose offers.

The candidates were: (A) a process-local in-memory `dict`; (B) a small embedded
store (SQLite / a JSON file) persisted across restarts; (C) an external datastore
(Redis / Postgres). Options B and C add a schema, a migration story, a connection
/ lifecycle to manage, and a second source of truth to keep consistent with the
workspace — none of which the v1 demo scope needs.

## Decision

Use a **process-local in-memory index** (option A): a module-level `OfferIndex`
singleton wrapping a `dict[UUID, Offer]`, keyed by the offer's deterministic id
(`matching/index.py`). It supports add, lookup, status transitions
(`mark_matched` / `mark_resolved`), and a keyword lookup against a Need that
reuses `recall.ranking`'s tokenizer so index hits and RTS hits share one notion
of relevance. Index hits are converted to the same `RecallMatch` shape RTS hits
use and merged into one ranked, sourced reply.

The durability gap is covered by the **Real-Time Search API recall path**: every
offer indexed here was *also* posted as a normal Slack message, so the workspace —
queried via RTS — is the durable system of record. The index is a latency
optimisation layered over that durable store, never a replacement for it.

## Consequences

- **No persistence across restarts.** The index dies with the process. This is
  acceptable: after a restart, RTS recall still finds every offer (it lives in the
  workspace), so the system degrades from "instant + RTS" to "RTS only", never to
  "offer lost". Documented in `matching/index.py` and surfaced as a deliberate
  demo constraint.
- **Single-process only.** The singleton is per-process; it is not shared across
  multiple workers. The demo runs one socket-mode process, so this is sufficient.
  Scaling to multiple processes would require revisiting this ADR (an external
  store, option C).
- **Not thread-safe.** Bolt's socket-mode dispatch is effectively serial for our
  load; we do not add locking. A concurrency model that fans message handling
  across threads would require revisiting this too.
- **Cheapest thing that works.** No schema, no migration, no connection lifecycle,
  no second source of truth to reconcile — the matching layer stays as "light" as
  the design doc asks. If a future requirement needs durable matching state
  (e.g. the coordinator Canvas surviving restarts, W4), that is a new fork with
  its own ADR; we do not pre-build it here.
