# 016 — Dedup index/RTS twins + index-match display polish

Live 006 verification (2026-06-12): a freshly indexed offer appeared TWICE in one
reply — MATCH 1 from RTS (the channel message) and MATCH 2 from the in-memory
index (same content) — and the LLM prose mirrored the duplicate. The index card
also leaks raw ids: "Posted by U0BA67L9HRS in #indexed offers".

## Acceptance criteria

1. Cross-source dedup in _merge_recall_results: an index hit and an RTS hit that
   near-duplicate each other (same author_id AND text Jaccard >= 0.85, reusing the
   echo-filter machinery) collapse to ONE match — prefer the INDEX hit (it carries
   offer_id, enabling status transitions via the buttons) but adopt the RTS hit's
   permalink/channel for display when present.
2. Index-match display polish in matching/conversion.py: author renders as a
   mention (<@id>), channel label becomes the real channel when known or
   "workspace memory" (no fake #indexed offers).
3. LLM context reflects the deduped list (it already serializes post-merge — verify).
4. Unit tests: twin collapse (keeps offer_id + adopts permalink), non-twin offers
   from the same author survive, display fields. Zero warnings.
5. [HUMAN] live: repeat the 006 need test — the cooker offer appears exactly once,
   with offer_id-backed buttons and the real channel label.

## Log
