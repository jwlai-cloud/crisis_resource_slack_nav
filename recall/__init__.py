"""RTS workspace recall: search prior offers, rank them, compose a sourced reply.

The *plan -> rank -> compose* slice of the agent loop for in-workspace memory
(design doc §"Real-Time Search API — in-workspace memory"):

* :func:`recall_offers` queries ``assistant.search.context`` for messages
  relevant to a Need and returns typed :class:`RecallMatch` results (or a typed
  :class:`RecallError` when the search cannot run).
* :func:`rank_matches` orders matches best-fit-first (keyword overlap + recency).
* :func:`build_recall_blocks` composes the ranked result into Block Kit, with
  source + timestamp + verify note on every item and explicit degraded/empty
  states.
"""

from recall.blocks import (
    ACTION_CONNECT,
    ACTION_NOT_RELEVANT,
    ACTION_RESOLVE,
    VERIFY_NOTE,
    WORKSPACE_BAR_EMOJI,
    build_recall_blocks,
)
from recall.client import build_query, recall_offers
from recall.models import RecallError, RecallMatch, match_from_message
from recall.payload import ConnectPayload
from recall.ranking import need_keywords, rank_matches, score_match, tokenize

__all__ = [
    "ACTION_CONNECT",
    "ACTION_NOT_RELEVANT",
    "ACTION_RESOLVE",
    "VERIFY_NOTE",
    "WORKSPACE_BAR_EMOJI",
    "ConnectPayload",
    "RecallError",
    "RecallMatch",
    "build_query",
    "build_recall_blocks",
    "match_from_message",
    "need_keywords",
    "rank_matches",
    "recall_offers",
    "score_match",
    "tokenize",
]
