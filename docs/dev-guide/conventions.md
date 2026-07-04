# Conventions & contributing

The authoritative version of these rules lives in
[`CLAUDE.md`](https://github.com/gebauer/labbutler/blob/main/CLAUDE.md) at the
repository root (it is written for AI assistants and humans alike). The short
form:

## Working style

- **Understand before changing.** Read the relevant code and nearby tests first;
  match existing patterns over introducing new ones.
- **Smallest change that fully solves the problem.** One logical change per
  commit/PR — no drive-by refactors, reformatting, or dependency bumps.
- **Leave it runnable.** Tests and `ruff check` green before a change is done.

## Code style

- `ruff format` is the source of truth — don't hand-format against it.
- Descriptive, intention-revealing names; functions are verbs, variables/types
  are nouns. Functions small and single-purpose; prefer early returns.
- Comments explain **why**, not what. No commented-out code.
- Pure core, effectful edges: keep business logic pure and testable; push I/O to
  views, tasks, and command entry points.

## Commits

Conventional Commits, imperative mood, ~50-char summary:

```
type(scope): summary        # feat, fix, refactor, docs, test, chore, perf, build, ci
```

e.g. `fix(procurement): make receiving without an item terminal`. Explain the
*why* in the body when it isn't obvious. Small, atomic commits that each leave
the tree green. Never commit secrets, `sample_data/`, or generated artifacts.

## Security ground rules

- All configuration via environment variables; **no secrets in the repo**.
- Every view checks its permission; every queryset is lab-scoped. Fail closed.
- Parameterized queries only; validate external input (the importers treat
  spreadsheets as hostile).
- User-safe error messages; diagnostic detail goes to logs, never responses.

## Dependencies

Prefer the standard library and what's already in the project. A new dependency
needs a justification (maintenance, size, security, license) and gets pinned via
`uv.lock`.

## Documentation

This site lives in `docs/` and is built with MkDocs Material
(`uv run mkdocs serve` for live preview, `uv run mkdocs build --strict` must
pass). It deploys to GitHub Pages automatically on push to `main`. Update the
docs in the same PR as a behaviour change — the docs build is part of the
definition of done.
