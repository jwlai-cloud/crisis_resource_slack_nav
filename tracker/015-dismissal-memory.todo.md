# 015 — Per-user dismissal memory

Live finding (2026-06-12): "Not relevant" rewrites only the clicked card; a new
need re-queries RTS and resurfaces the same match with fresh buttons. The old
copy promised "I won't surface this match again" — softened to "Dismissed for
this request" (accurate) pending this task.

Direction: in-memory dismissal store keyed (user_id, match identity: offer_id or
permalink or text-hash), consulted in the recall filter for that user's needs.
Same persistence posture as the offer index (process-lifetime; W4 persistence
decision covers both). Audit already records the dismiss signal — reuse it as
the store if convenient. Pairs with 014 (need-echo filter), which removes the
echo case observed here.

## Log
