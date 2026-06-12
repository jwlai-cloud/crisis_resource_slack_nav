# 012 — Reply brevity + shared situation board

User feedback (2026-06-12, after 009 live test): the need reply dumped the full official picture (roads + water + evac) at one user — too long, and the general MCP content is identical for everyone in the same time frame.

## Direction

1. **Relevance pruning (prompt + compose):** a need reply includes only official items directly relevant to the parsed need — water need → water point; explicit travel/road mention → that closure; shelter need → evac centres. Hard cap (~2-3 official lines). Anchor-test the prompt rule.
2. **Shared situation board:** the general official picture lives in ONE shared artifact — fold into W4's coordinator Canvas as a "situation board" section (roads / water / evac / advice, each feed-stamped with fetched-at), refreshed on demand or per significant change. Individual replies end with a one-line pointer ("Full road and evac status: situation board, updated HH:MM UTC") instead of repeating it.
3. Threading stays as-is: channel replies in-thread (already true), DMs linear.

Groom with W4 (Canvas task) — the board is the Canvas's first concrete content.

## Log

Addendum (2026-06-12, token-cost review): serialize_recall_context sends ALL ranked
matches with untruncated text to the LLM while blocks render top 5 — cap the context
at the same 5 and truncate snippets (~200 chars). Also add an RTS observability log
line (query latency + pre/post-filter counts) alongside the W4 audit work.
