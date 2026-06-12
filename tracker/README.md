# File-based task tracker

Tasks for the `/day` and `/night` pipelines live here as markdown files. The filename encodes the state; transitions are file renames. Full workflow rules: [`docs/PROCESS.md`](../docs/PROCESS.md).

```
tracker/
├── 001-add-feature.todo.md         # raw, awaiting grooming
├── 002-pagination.groomed.md       # PM-groomed, in Tasks Plan
├── 003-search.in-progress.md       # SWE/Tester actively working
└── done/
    └── 000-bootstrap.md            # accepted, committed
```

State transitions:

- New task → `NNN-slug.todo.md`
- After PM grooming → `NNN-slug.groomed.md`
- When SWE picks up → `NNN-slug.in-progress.md`
- After PM accepts and the commit lands → `git mv` to `done/NNN-slug.md`

Numbering is monotonic — never reused. Each task file carries a `## Log` section: append-only, timestamped entries per role (`### [ROLE] YYYY-MM-DD HH:MM — Subject`). Dependencies are declared with `Depends on: NNN` lines.
