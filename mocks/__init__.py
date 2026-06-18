"""Thin mock MCP servers for the external-reach pillar (design doc §3/§9).

A single FastMCP server (:mod:`mocks.server`) exposes the Exmouth / Cyclone
Narelle official directories — road closures, evacuation centres, and official
advice — backed by static JSON in this package. The integration *pattern* is
what the challenge judges; these never wire real government feeds, and the
project must never claim live feeds (design doc §9).
"""
