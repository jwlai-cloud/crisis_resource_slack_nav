# 0001. Record architecture decisions

**Status:** Accepted
**Date:** 2026-06-10

## Context

We expect to make architectural decisions over the lifetime of this project — choices that the code itself doesn't fully explain (which datastore, which queue, which async model, which auth boundary). Six months from now, we will not remember why we chose what we chose. Without a record, we will re-litigate the same decisions and probably reach different conclusions.

## Decision

We will use Architecture Decision Records, as described by Michael Nygard, stored in `docs/adr/` as `NNNN-kebab-title.md`. Each ADR has four sections: Status, Context, Decision, Consequences.

## Consequences

- Every non-obvious architectural choice gets a one-page record.
- New contributors can read `docs/adr/` to understand why the codebase is shaped the way it is.
- The `/architecture-review` skill can read prior ADRs and avoid re-proposing settled questions.
- Cost: ~30 minutes per ADR. We accept this cost because the alternative — re-deriving past reasoning — is more expensive.
