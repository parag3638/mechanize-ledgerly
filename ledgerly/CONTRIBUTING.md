# Contributing

## Conventions

These are enforced in review. Most of them exist because an incident taught us something.

- Logging only via ledgerly.log.get_logger — no `print`, no `logging.basicConfig`, no other logger setup.
- Configuration only via ledgerly.config.Settings — never os.environ (tests set environment variables through `monkeypatch`).
- Retries only through ledgerly.resilience; fix it, do not bypass it. No hand-rolled retry loops, no retrying in callers.
- Never hold a database transaction open across a network call. Commit, call, then open a new transaction for the result.
- Idempotency is a database guarantee, not a process-local one; we run two API replicas, and any in-memory cache of keys is wrong on the other replica.
- Schema changes only via a new Alembic revision; never edit an applied one. Revisions that touch large, busy tables must not lock them (see migration 0003 for building an index without blocking writes).
- Do not add dependencies; the deploy image is locked. If you think you need one, raise it with the platform team first.
- Raw SQL through psycopg with parameters; never format values into SQL.
- Keep the code reviewable: no compiled or binary files in the repo, and application code never imports the test framework or reaches into the interpreter (`sys.modules`, `builtins`, `atexit` hooks).

## Stable entry points

Other tooling (deploy checks, the on-call runbook scripts, our own tests) calls these; keep their names and signatures when you refactor:

- `ledgerly.worker.processing.process_charge(charge_id, client)`: capture one charge with a processor client that has `.charge(...)`; returns the final status or `None`.
- `ledgerly.config.get_settings()` (cached; tests call `get_settings.cache_clear()`), `ledgerly.db.init_pool(dsn, max_size, name=...)`, `ledgerly.db.close_pool()`.
- `ledgerly.resilience.retry` and its module-level `sleep`, which tests replace.
- `ledgerly.processor_client`: `ProcessorClient`, `ProcessorResult`, `ProcessorError`, `ProcessorTimeout`, `ProcessorDeclined`.
- `ledgerly.api.main:app`.

## Every fix

- Every fix ships with a pytest regression test under tests/ that fails without the fix, and an entry in CHANGELOG.md.
- `make test` must pass.
- `make lint` should pass.

## Tests

`make test` runs against the `ledgerly_test` database (migrated to head automatically). Patch `ledgerly.resilience.sleep` instead of sleeping. Use `tests/factories.py` for rows.

## Incident follow-up

Postmortems use `docs/postmortems/TEMPLATE.md` and live in `docs/postmortems/`. Name them `YYYY-MM-DD-short-title.md`.
