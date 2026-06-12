# 002 — Need/Offer entities + structured parsing

Create the typed core from design doc §6 and a parsing path from free text to those types using pydantic-ai structured output.

## Acceptance criteria

1. `entities/` package with Pydantic models:
   - `Need`: id, requester, need_type, location, urgency, household_size, status (open/matched/resolved), source_ts
   - `Offer`: id, offerer, resource_type, location, availability, status, source_ts
   - `Resolution`: need_id, offer_id, confirmed_by, timestamp
2. Enums for status + urgency; `source_ts` timezone-aware UTC (naive datetimes rejected by validator — guardrail: timestamps are product requirements).
3. Deterministic ids (UUID5 from requester+ts or similar), not bare uuid4.
4. `agent/parsing.py` (or equivalent): `parse_message(text, author, ts) -> Need | Offer | NotACrisisMessage` using pydantic-ai with `output_type` — typed result, no JSON scraping.
5. Unit tests: model validation (incl. naive-datetime rejection), parametrized parse cases mocked via pydantic-ai `TestModel`/`FunctionModel` — no live LLM in unit tests.
6. Integration test (optional, marked): one live parse against the configured model.

## Out of scope

Indexing/storage (003), wiring into listeners (003/004).

## Log
