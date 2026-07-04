# Testing

```bash
uv run pytest            # whole suite
uv run pytest apps/procurement          # one app
uv run pytest -k self_approve           # by keyword
```

The suite uses **pytest + pytest-django** against a real PostgreSQL (the
project-local dev instance — make sure `scripts/pg.sh start` has run). SQLite is
not supported, so there is no "lite" test mode.

## Organisation

Tests live in each app under `<app>/tests/`, mirroring the module under test —
`apps/procurement/services.py` is covered by
`apps/procurement/tests/test_services.py`, and so on.

## Ground rules

- **Every behavioural change comes with a test.** A bug fix starts with a failing
  test that reproduces it.
- Test **behaviour and public contracts**, not implementation details. Cover the
  happy path, edge cases, and error cases — especially the *fail-closed* cases:
  a user without the permission must be refused, a transition from the wrong
  status must raise.
- Deterministic and independent: no reliance on ordering, wall-clock time,
  network, or shared state. Inject clocks/randomness; mock external services.
- Email is asserted via Django's test outbox.
- Keep tests fast; anything slow belongs behind a separate marker.

Two project-wide autouse fixtures in the root `conftest.py` are worth knowing:
tests run with the plain static-files storage (no `collectstatic` manifest
needed), and django-axes is disabled so `force_login`-based tests aren't
affected — the brute-force test re-enables it explicitly.

## What the existing tests show

Good examples to crib from:

- `apps/procurement/tests/` — state-machine coverage: allowed and refused
  transitions, permission checks per move, item creation on check-in.
- `apps/imports/tests/` — pure-parser tests (prices, dates, TAGS) and plan/commit
  round-trips on fixture workbooks.
- `apps/notifications/tests/` — builder output, recipient selection, outbox
  sends, and the `transaction.on_commit` hook.
