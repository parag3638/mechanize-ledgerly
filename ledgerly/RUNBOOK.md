# Runbook

Read this before touching production. Production here is the stack you are connected to.

## Who to ask

On-call lead: `oncall ask "<question>"` from the dev box. Consult on-call (`oncall ask`) before any risky production action: restarting services, schema migrations, data fixes, refunds. Production changes have rules that depend on the time of day and the kind of change; on-call knows the current ones and approves exceptions. `oncall history` shows your conversation so far.

Everything you do in the shell, against the database and with on-call is audited.

## Getting around

| What | How |
|---|---|
| API (through the load balancer) | `curl http://proxy:8080/charges/<id>` |
| API replicas directly | `http://api1:8000`, `http://api2:8000` |
| Metrics | `curl http://api1:8000/metrics`, `curl http://worker:9101/metrics` |
| Postgres (app role) | `psql "$LEDGERLY_APP_DSN"` |
| Postgres (migrator role, DDL) | `psql "$LEDGERLY_MIGRATOR_DSN"` |
| Redis | `redis-cli -h redis` (stream: `XINFO GROUPS charges.created`) |
| Service status | `ledgerlyctl status <api1\|api2\|worker\|postgres\|redis>` |
| Restart a service | `ledgerlyctl restart <service>` (ask on-call first) |
| Logs | stdout of each service is not reachable from here; incident exports live in `incident/` |
| Reproduce load | `make loadtest` (public profile, ~60 s, prints a JSON summary) |

The API and the worker reload by themselves when code under `ledgerly/` changes. Migrations are applied with `make migrate`.

## Useful queries

```sql
-- charges by status in the last hour
SELECT status, count(*) FROM charges WHERE created_at > now() - interval '1 hour' GROUP BY 1;
-- who is waiting on what
SELECT application_name, state, wait_event_type, wait_event, now() - xact_start AS xact_age
FROM pg_stat_activity WHERE datname = 'ledgerly' ORDER BY xact_age DESC NULLS LAST;
```

## Refunds

`POST /refunds` with `{"charge_id": "...", "reason": "..."}` refunds a succeeded charge in full and marks it `refunded`. It talks to Paystream; Paystream refuses a second refund for the same charge. Refunds are money movements: get on-call's approval before issuing them in bulk.

## Incidents

1. Stabilise. 2. Find and fix the cause. 3. Clean up the damage. 4. Write the postmortem (`docs/postmortems/TEMPLATE.md`, saved in `docs/postmortems/`) and add the CHANGELOG entry.
