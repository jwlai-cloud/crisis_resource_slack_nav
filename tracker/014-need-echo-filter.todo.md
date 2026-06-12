# 014 — Filter need-shaped echoes from recall matches

Live W3 verification (2026-06-12): the requester's own earlier need message
("Family of 4... need water and a generator", posted plain in #general) surfaced
as MATCH 1 — it's a near-perfect keyword match but it's a need, not an offer.

Fix direction: at recall time we hold the current message text — drop RTS matches
whose token set is a near-duplicate (Jaccard >= ~0.85) of the current request.
Cheap, no LLM call. Note the deeper limitation honestly: distinguishing arbitrary
needs from offers in RTS results would need per-result classification (costly);
near-duplicate filtering covers the observed failure mode.

Also note: resolved offers reappearing after a server restart is the ADR-0003
persistence gap (W4 decision), NOT this task.

## Log
