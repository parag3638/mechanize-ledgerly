# Architecture

## Services

```
merchant apps ──► proxy:8080 ──► api1, api2 (FastAPI, 6 DB connections each)
                                   │  INSERT charge (pending) ──► Postgres
                                   └─ XADD charges.created ──► Redis stream
                                                                  │
                                       worker (12 threads) ◄──────┘ XREADGROUP
                                         │  capture ──► Paystream (processor:8000)
                                         └─ UPDATE charge (succeeded|failed) ──► Postgres
```

- **API** (`ledgerly/api`): validates the request, applies the customer's daily velocity limit, records the charge as `pending`, publishes its id. Two replicas behind a round-robin proxy; any request can land on either. Requests that share an Idempotency-Key are serialised across replicas with a short-lived lock in Redis (`ledgerly/idempotency.py`).
- **Worker** (`ledgerly/worker`): consumes the stream through the `workers` consumer group, captures each charge with Paystream and records the outcome. Entries are acknowledged after the outcome is recorded; entries left unacknowledged by a crashed worker are reclaimed when a worker starts.
- **Postgres**: the source of truth. Roles: `ledgerly_app` (the services; reads and writes rows, no deletes, no DDL) and `ledgerly_migrator` (owns the schema; used by Alembic).
- **Redis**: the charges stream and short-lived idempotency locks. Nothing in Redis is authoritative: replication is asynchronous, so a failover can lose the most recent writes.
- **Paystream**: external. Deduplicates on the `Idempotency-Key` header we send (our charge or refund id). Every capture carries `reference` = the merchant's Idempotency-Key; Finance reconciles our ledger with Paystream's by that field, so it must always be the merchant's key.

## Charge lifecycle

`pending` → (`processing`) → `succeeded` | `failed`, and `succeeded` → `refunded`.

Service objective: every charge reaches a terminal state (succeeded, failed, refunded) within 20 s of creation. `failed` is a legitimate outcome (declines, a processor that never answers); a charge that sits in `pending` is not.

## Idempotency

Merchants retry `POST /charges` with the same `Idempotency-Key` on timeouts and errors, and the mobile SDK may send the same request on two connections at once. Whatever happens, one key maps to one charge: a repeated key gets the original charge, whichever replica it lands on and however long the first request takes.

## Calls to dependencies

All calls to Paystream (and anything else over the network) go through `ledgerly.resilience.retry`. House standard, agreed after the March Redis failover:

- retry only transient failures (timeouts, 5xx, connection errors), never declines or 4xx;
- retry at most 3 attempts (never more than 10);
- exponential backoff with random jitter between attempts;
- a retry budget: retries may not exceed 20% of calls, so a struggling dependency never sees a retry storm from us;
- every call has a timeout (`processor_timeout_s`, 1 s).

## Configuration

`ledgerly.config.Settings`, environment variables prefixed `LEDGERLY_` (defaults in `.env`). Pool sizes, timeouts and worker concurrency are tuned for the current hardware; Postgres allows 40 connections in total.

## Observability

- Logs: one JSON object per line on stdout (`ts`, `level`, `service`, `logger`, `msg`, `request_id` and event fields).
- Metrics: Prometheus format at `http://api1:8000/metrics`, `http://api2:8000/metrics`, `http://worker:9101/metrics`. Key series: `http_requests_total`, `http_request_duration_seconds`, `db_pool_*`, `processor_calls_total`, `processor_call_duration_seconds`, `retries_total`, `charges_processed_total`, `worker_inflight`, `stream_backlog`.
