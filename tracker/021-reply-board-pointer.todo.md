# 021 — One-line "full picture on the board" pointer in need replies

Deferred from 020 (Direction item 3). A need reply now shows only need-relevant
official items (012 pruning); add a single trailing line pointing the resident to
the coordinator board for the full road/water/evac picture, so brevity doesn't lose
discoverability. Lives in the reply/compose path (listeners/reply.py or the
recall reply composition), not the board. Best-effort, only when the board exists
(a canvas id is known). Small. W4/W5 polish.

## Log
