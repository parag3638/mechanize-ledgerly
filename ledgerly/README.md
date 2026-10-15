# Ledgerly

Ledgerly takes card charges from merchants' apps and captures them with our payment processor, Paystream.

- `POST /charges` creates a charge (`pending`) and puts it on the charges stream. Clients send an `Idempotency-Key` header and retry with the same key.
- The worker reads the stream and captures each charge with Paystream (`succeeded` or `failed`).
- `POST /refunds` refunds a succeeded charge in full (`refunded`).

How the pieces fit: `ARCHITECTURE.md`. How we work: `CONTRIBUTING.md`. Operating it: `RUNBOOK.md`.

## Layout

```
ledgerly/config.py           Settings: the only place that reads the environment
ledgerly/log.py              get_logger(): JSON logs
ledgerly/db.py               connection pool
ledgerly/resilience.py       retry helper used for every call to a dependency
ledgerly/processor_client.py Paystream client
ledgerly/queue.py            charges stream (Redis Streams)
ledgerly/api/                FastAPI app: charges, refunds, health
ledgerly/worker/             stream consumer and charge capture
migrations/                  Alembic revisions
tests/                       pytest suite (runs against the ledgerly_test database)
tools/loadtest.py            replays profiles/public.json against the stack
incident/                    evidence exported for incident reviews
```

## Common commands

```
make test       # pytest against ledgerly_test
make loadtest   # replay the public load profile against http://proxy:8080
make migrate    # alembic upgrade head (migrator role)
make lint       # ruff
```

The staging stack runs two API replicas (`api1`, `api2`) behind `proxy:8080`, one `worker`, `postgres`, `redis` and the Paystream sandbox (`processor:8000`). Code changes reload the API and the worker automatically.
