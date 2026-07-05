# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repository.
This is a general engineering baseline; fill in the `[bracketed]` placeholders per project and delete what doesn't apply.

---

## How to work here

- **Understand before changing.** Read the relevant code and nearby tests before editing. Match existing patterns over introducing new ones.
- **Plan non-trivial work.** For anything beyond a small fix, outline the approach first, then implement. Prefer the smallest change that fully solves the problem.
- **Ask when genuinely ambiguous; otherwise proceed.** State the assumption you're making inline rather than stopping for trivial confirmations.
- **Keep diffs focused.** One logical change per commit/PR. Don't bundle unrelated refactors, reformatting, or dependency bumps into a feature change.
- **Don't invent.** No fabricated APIs, file paths, config keys, or library behaviour. If unsure whether something exists, check the code or say so.
- **Leave it runnable.** Never end on a state that doesn't build, with broken imports, or with failing tests you introduced.

## Commands

> Fill these in so the assistant can verify its own work.

- Install deps: `uv sync` (Python) · `npm install` (Tailwind build only)
- Local Postgres: `scripts/pg.sh init` once, then `scripts/pg.sh start` / `stop`
- Run (dev): `uv run python manage.py runserver` · CSS watch: `npm run dev` · worker: `uv run celery -A labbutler worker -l info`
- Run tests: `uv run pytest`
- Lint / format: `uv run ruff check .` / `uv run ruff format .`
- Type check: _(none configured yet — no type checker in the toolchain)_
- Migrations: `uv run python manage.py makemigrations` / `migrate`
- CSS build (prod): `npm run build`
- Build (prod image): `docker compose build`

Always run the tests and linter before considering a change done. (No type checker is
configured yet; if one is added, wire it in here and run it too.)

## Project structure

- `labbutler/` — Django project: `settings.py` (env-driven), `urls.py`, `celery.py`, `wsgi`/`asgi`, `static/`.
- `apps/` — application code, one Django app per domain:
  - `tenancy/` — `User`, `Lab`, `Membership`, `Role`, `Permission` (multi-lab scoping & auth).
  - `inventory/` — `Item`, `Location`, `Tag`, `FieldDefinition`/`FieldPreset`, `HazardStatement`.
  - `procurement/` — `Request` workflow, `Budget`, `Vendor`, `ShippingAddress`.
  - `imports/` — LabSuit profile + generic mapper, parsers, dry-run preview.
  - `audit/` — append-only `AuditEntry`.
- Tests live in each app under `<app>/tests/`, mirroring the module under test.
- `templates/` — project-level Django templates (HTMX + Tailwind). `scripts/` — dev helpers (`pg.sh`).
- Config and tooling (`pyproject.toml`, `package.json`, `docker-compose.yml`, `.env.example`) live at the repo root.

> Models/UI for inventory & procurement are landing incrementally; see [TODO.md](TODO.md) for status.

## Code style & conventions

- Follow the language's standard style guide and the configured linter/formatter. The formatter is the source of truth — don't hand-format against it.
- **Naming:** descriptive, intention-revealing names. No single-letter names except trivial loop indices. Functions are verbs, variables/types are nouns.
- **Functions small and single-purpose.** Prefer early returns over deep nesting. Keep cyclomatic complexity low.
- **Explicit over clever.** Optimize for readability and the next maintainer, not brevity.
- **Comments explain _why_, not _what_.** The code shows what; comment intent, trade-offs, and non-obvious constraints. Remove commented-out code.
- **Immutability by default;** mutate only when there's a reason. Avoid shared mutable global state.
- **Pure core, effectful edges.** Push I/O, network, and side effects to the boundaries; keep business logic pure and testable.
- **Match existing import ordering, file organization, and module boundaries.**

## Testing

- Add or update tests with every behavioural change. A bug fix starts with a failing test that reproduces it.
- Test behaviour and public contracts, not implementation details. Cover the happy path, edge cases, and error cases.
- Tests must be deterministic and independent — no reliance on ordering, wall-clock time, network, or shared state. Inject clocks/randomness; mock external services.
- Keep them fast; reserve slow/integration tests for a separate suite or marker.

## Git & commits

- **Conventional Commits:** `type(scope): summary` (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`). Imperative mood, ~50-char summary.
- Explain the _why_ in the body when it isn't obvious. Reference issues where relevant.
- Small, atomic commits that each leave the tree green.
- Never commit secrets, credentials, large binaries, or generated artifacts. Don't commit directly to the protected/main branch unless asked.

## Versioning & the version footer

- Every page shows a footer with the app version (linking to that version's GitHub release page) and the build commit in parentheses (linking to the commit on GitHub). The footer derives everything from `version` in `pyproject.toml` and git (read by `labbutler/version.py`) — **never hardcode the version or commit anywhere else**.
- The commit is resolved at startup from `$LABBUTLER_COMMIT` or `git rev-parse`. Docker images have no `.git`, so builds must pass it: `GIT_COMMIT=$(git rev-parse --short HEAD) docker compose build`.
- **On every commit, check the footer stays correct:** if the commit changes what users get (features, fixes), bump `version` in `pyproject.toml` (PEP 440, e.g. `1.0.0rc1`, `1.1.0`) as part of the commit.
- When a version is final, tag it `v<version>` with a hyphen before any pre-release segment (`1.0.0rc1` → `v1.0.0-rc1`), push the tag, and create the matching GitHub release (`gh release create <tag> --generate-notes`, add `--prerelease` for rc/alpha/beta) so the footer link resolves.

## Dependencies

- Prefer the standard library and what's already in the project. Justify any new dependency (maintenance, size, security, license).
- Pin/lock versions via the project's lockfile. Don't upgrade unrelated dependencies inside a feature change.
- Avoid adding a library for something trivial you can write in a few lines.

## Security

- **Never hardcode secrets.** Use environment variables / a secrets manager. Don't print, log, or commit secrets, tokens, or PII.
- Validate and sanitize all external input. Treat anything from users, files, or the network as untrusted.
- Use parameterized queries; never build SQL/shell/HTML by string concatenation of untrusted input.
- Apply least privilege. Fail closed on auth/permission checks.
- Keep error messages user-safe; put diagnostic detail in logs, not in responses.

## Errors, logging & observability

- Handle errors explicitly; don't swallow them. Fail fast on programmer errors, recover gracefully from expected runtime errors.
- Raise/return errors with enough context to debug. Don't use exceptions for normal control flow.
- Use structured logging with appropriate levels. No `print`-debugging left in committed code. Never log secrets or PII.

## Performance & data

- Make it correct and clear first; optimize only with a measurement showing it matters. Note real hot paths.
- Watch for N+1 queries and unbounded loops/allocations over user-controlled input. Paginate large result sets.
- Treat database migrations as append-only and reversible; review destructive changes carefully.

## Documentation

- Update the README and relevant docs when behaviour, setup, commands, or public APIs change.
- Document public functions/modules with their contract: purpose, params, returns, errors, side effects.
- Keep this file current as conventions evolve.

## Do / Don't (quick reference)

**Do:** read first · match existing patterns · small focused diffs · test every change · run lint+tests+types before finishing · ask when truly blocked.
Use Claude worktrees, whenever the user states their are multiple workers running - Suggest to merge the worktree at the end of the job.

**Don't:** invent APIs or paths · commit secrets · bundle unrelated changes · leave the build broken · disable/skip tests to make them pass · reformat files you aren't otherwise touching.