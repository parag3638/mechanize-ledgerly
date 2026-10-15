# BACKEND.md — Backend rules

> Read this before any backend change. Works for any language.
> Pairs with DESIGN.md: the API returns exactly what the UI needs, in the shapes in §3.
> If a request conflicts with this file, follow the request and flag the conflict in one line.

**Goal:** boring, safe, fast code. Easy to read, hard to misuse.
**Default stack:** Postgres + Python (FastAPI) or TypeScript (Node). Any other language: fill the §2 toolkit row first.

---

## 0. Prerequisites

Agent: run every check, install what's missing, then report a one-line status per row before writing code.

| # | Item | Check | Install |
|---|------|-------|---------|
| 1 | Pinned runtime + lockfile | `.python-version` or `.nvmrc`, plus `uv.lock` or `pnpm-lock.yaml` | Create and commit them |
| 2 | Docker (local + test Postgres) | `docker compose version` | Docker Desktop / Engine |
| 3 | Context7 MCP (current library docs) | `/mcp` shows `context7` | `claude mcp add --transport http context7 https://mcp.context7.com/mcp` |
| 4 | security-guidance plugin | `/plugin` → Installed | `/plugin marketplace add anthropics/claude-plugins-official` → `/plugin install security-guidance@claude-plugins-official` → `/reload-plugins` |
| 5 | Plugin reads this file | `test -f .claude/claude-security-guidance.md` | Create it containing: `Enforce BACKEND.md §4 on every change.` |
| 6 | code-review plugin (optional) | `/plugin` → Installed | `/plugin install code-review@claude-plugins-official` |
| 7 | Language server plugin | `/plugin` → Installed | `/plugin` → Discover → your language |
| 8 | Scanners | `semgrep --version && trivy --version` | `pipx install semgrep`; Trivy from its official installer or `brew install trivy` |
| 9 | One check command | `make check` runs | Agent creates it from §10 |

Precedence: this file > plugins > framework defaults.

---

## 1. Principles

1. **Simple first.** The plainest code that works. No abstraction until the second real use.
2. **One home per job.** Config, DB access, auth, errors, logging and IDs each live in exactly one place.
3. **Distrust input.** Requests, files, webhooks, other services and AI model output are all validated at the edge.
4. **Deny by default.** Every route needs sign-in and an ownership check unless it's marked public on purpose.
5. **Fast by design.** Paginate, index, set timeouts. Slow work goes to the background.
6. **Fail clearly.** Specific errors, logged once, shown to users in plain words.
7. **The database guards the truth.** Rules that must always hold live in the schema, not only in code.

---

## 2. Structure

```
src/
  main.*                 # start app, middleware, mount features
  config.*               # read + validate env once, at startup
  lib/                   # errors, logger, db, http client, ids, money, time — one of each
  features/<name>/
    routes.*             # parse input → call service → shape output. No rules here.
    service.*            # business rules + permission checks. No HTTP, no SQL.
    repo.*               # DB queries. The only place SQL lives.
    schemas.*            # input/output shapes: one source for validation, docs and frontend types
    *.test.*
  jobs/                  # background work
migrations/
```

- Flow is always route → service → repo. No skipping, no calling upward.
- Features talk to each other only through services.
- Helper used by two features → move to `lib/`.

### Toolkit (pick once, never mix)

| Job | Python | TypeScript |
|-----|--------|-----------|
| Framework | FastAPI | Fastify |
| Config | pydantic-settings | Zod-parsed env |
| Validation / schemas | Pydantic | Zod |
| DB access | SQLAlchemy 2 (async) | Drizzle |
| Migrations | Alembic | drizzle-kit |
| Lint + format | ruff | Biome |
| Types | pyright (strict) | `tsc --strict` |
| Tests | pytest | Vitest |
| Logs | structlog (JSON) | pino |
| HTTP client | httpx | `fetch` + `AbortSignal.timeout` |
| Jobs | procrastinate (Postgres) | pg-boss (Postgres) |
| Password hashing | argon2-cffi | @node-rs/argon2 |
| Packages | uv | pnpm |

Jobs use Postgres as the queue until load proves otherwise. One less service to run.

---

## 3. API contract (shared with DESIGN.md)

**Shape**
- JSON over HTTPS. Plural nouns: `/v1/orders`, `/v1/orders/{id}`. GET reads, POST creates or runs an action, PATCH updates part, DELETE removes.
- Keys in `camelCase`. IDs are strings (UUIDv7: time-ordered, index-friendly).
- Times: ISO 8601 UTC, e.g. `2026-10-03T09:30:00Z`.
- Money and prices: decimal strings with currency, e.g. `{"amount": "1234.50", "currency": "USD"}`. Never floats.
- Percentages: decimal strings (`"0.0123"` = 1.23%).
- Backend sends raw values. Formatting happens only in the frontend's `lib/format.ts`.
- Status values: lowercase strings from a fixed list (`active`, `paused`, `filled`). They map 1:1 to UI badge variants.

**Envelopes**
- One item: `{ "data": { ... } }`
- List: `{ "data": [ ... ], "nextCursor": "..." | null }`. Cursor pagination, default 25, max 100.
- Error (always this shape):

```json
{
  "error": {
    "code": "insufficient_funds",
    "message": "Not enough buying power. Lower the quantity or add funds.",
    "fields": { "quantity": "Must be 1 or more." },
    "requestId": "req_01J9..."
  }
}
```

- `message` follows DESIGN.md §9: what happened and how to fix it, no apology. Safe to show in a toast as-is.
- `fields` feeds form field errors directly.
- Never return stack traces, SQL, file paths or internal names.

**Status codes**

| Code | Meaning |
|------|---------|
| 200 / 201 / 204 | OK / created / done, nothing to return |
| 202 | Accepted, running in background; body has a status URL |
| 400 | Malformed request |
| 401 | Not signed in |
| 403 | Signed in, not allowed (admin-only actions) |
| 404 | Not found, or not yours |
| 409 | Conflict or duplicate |
| 422 | Valid shape, breaks a rule or validation |
| 429 | Too many requests; includes `Retry-After` |
| 500 | Our bug |
| 503 | A dependency is down |

**Other rules**
- Actions with side effects (orders, payments, bot starts) accept an `Idempotency-Key` header. Same key = same result, never a duplicate.
- Frontend types are generated, never hand-written: OpenAPI → `openapi-typescript` (Python backends), or shared Zod schemas (TS backends).
- Changes are additive. Never rename or remove a field in place; add the new one, migrate callers, then remove under a new version.

---

## 4. Security

Every change that touches input, auth, data or outbound calls is checked against this list.

**Input**
- Validate every input with the feature's schema: types, lengths, ranges, allowed values. Reject unknown fields.
- Cap request body size (1 MB default; uploads set their own).
- Queries always use parameters. Never build SQL, shell commands or file paths from user input.

**Sign-in and access**
- Use a proven auth provider or library. Never write your own crypto, tokens or password hashing.
- Passwords: argon2id. Access tokens short-lived; refresh tokens rotate on use.
- Browser sessions: cookies with `HttpOnly`, `Secure`, `SameSite=Lax`.
- Every read and write checks the record belongs to the caller (`where owner_id = :user_id`). Missing and not-yours both return 404.
- Permission checks live in services, so every route and job gets them.
- Admin routes sit on a separate router with their own check.

**Secrets**
- Secrets come only from env or a secret manager (e.g. Azure Key Vault). Never in code, logs, error messages or AI prompts.
- `.env` is gitignored; `.env.example` is committed with fake values.
- The app's DB user has only the rights it needs: no superuser, no schema changes. Migrations run as a separate user.

**Edges**
- CORS: exact list of allowed origins. Never `*` with credentials.
- Rate limit sign-in, sign-up, password reset and expensive routes, per IP and per user.
- Webhooks: verify signature and timestamp before trusting the body.
- Fetching a user-supplied URL: allowlist hosts, block private and internal IPs, don't follow redirects into them.
- Uploads: size cap, check the real file type, random stored name, object storage, never executed.
- Any HTML or docs routes send security headers (HSTS, `nosniff`, frame deny, CSP).

**AI features**
- Treat model output as untrusted input: validate it with a schema; never run it as code, SQL or shell.
- Tool calls requested by a model pass the same permission checks as user requests.
- Citations must point to IDs from the retrieved set; drop any that don't.
- Never put secrets or another user's data into a prompt.
- Cap tokens, time and cost per request.

**Dependencies and logs**
- Lockfile committed, versions pinned. `semgrep` and `trivy` clean before a change is done.
- Logs never contain passwords, tokens, account numbers or personal data beyond IDs.

---

## 5. Data (Postgres)

- Schema changes only through migration files. One per change. Never edit one that's already applied.
- Constraints in the DB: `not null`, `unique`, foreign keys, `check`. Code validation is extra, not a replacement.
- Every table has `id` (UUIDv7), `created_at`, `updated_at` (`timestamptz`, UTC).
- Money, prices and quantities use `numeric`. Never `float`/`real`.
- Index every foreign key and every column a list filters or sorts by. Run `EXPLAIN` on each new list query.
- Multi-step writes go in one transaction. Keep it short; no network calls inside.
- No queries inside loops: load related rows in one query (join or `IN (...)`).
- Select only the columns you return. No `SELECT *` in app code.
- Delete for real unless users need restore; then add `deleted_at` and filter it everywhere via the repo.

---

## 6. Speed

**Budgets** (95% of requests faster than): reads 200 ms, list pages 300 ms, writes 500 ms. Work over ~1 s goes to a background job and returns 202.

- Paginate every list. No unbounded arrays.
- One DB connection pool per process, sized to the DB's limit. Reuse one HTTP client.
- No blocking calls on the request path (sync DB drivers, `sleep`, heavy CPU). Heavy CPU → job.
- Every outbound call has a timeout: 3 s connect, 10 s total by default.
- Independent calls run in parallel (`gather` / `Promise.all`), not one after another.
- Cache only slow, read-heavy data. Always set an expiry, include the user/tenant in the key, clear on write. Cache is never the source of truth.
- Compress responses over 1 KB.
- Measure first: add timing to logs or traces, then optimise what's actually slow.

---

## 7. Reliability

- `GET /healthz`: process is alive. `GET /readyz`: DB and critical dependencies reachable. No auth, no secrets in the output.
- Retry only safe or idempotent operations: max 3, growing wait with a random offset. Never retry 4xx.
- When a dependency keeps failing, return 503 fast and pause calls to it briefly instead of piling up requests.
- Jobs are safe to run twice, retry with growing waits, and land in a failed-jobs table after the last try.
- Graceful shutdown: stop new requests, finish in-flight ones (up to 30 s), close pools.
- Invalid or missing config = refuse to start, with a clear message naming the variable.
- Scheduled tasks take a lock so two instances never run the same one.

---

## 8. Observability

- Logs: JSON, one line per event, with `requestId`, `userId` (ID only), route, status, duration.
- Levels: `error` needs action, `warn` unexpected but handled, `info` key business events, `debug` off in production.
- Log an error once, where it's handled, not at every layer.
- Every request gets a `requestId` (from the incoming header or generated), returned in responses and errors.
- Per route: request count, error rate, duration (p50/p95/p99).
- Traces with OpenTelemetry, exported to your monitoring tool (e.g. Azure Monitor). Include DB and outbound calls.
- Alerts on error rate, p95 over budget, failed jobs, `/readyz` failing.

---

## 9. Code style

- Plain names that say what things are: `cancel_order`, not `process_order_state_transition`.
- Same word as the UI: if the button says "Bot", the code says `bot`.
- Functions do one thing, ideally under 40 lines. Early returns over nested ifs.
- **Rule of two:** a second copy of logic gets extracted. Not before.
- Services raise typed app errors (`NotFound`, `Forbidden`, `Conflict`, `RuleBroken`) from `lib/errors`. One handler turns them into the §3 shape.
- Strict types. No `any` or untyped dicts crossing layers.
- Comments explain why, not what. No dead code, no commented-out code.
- Don't rebuild what the framework already gives you (validation, docs, dependency wiring).
- New dependency only with a reason in `DECISIONS.md`. Prefer the standard library.

---

## 10. Checks and definition of done

One command. You run it before handing to `tester`; the tester runs it again:

```make
# Python
check:
	ruff format . && ruff check . && pyright && pytest -q
	semgrep scan --config auto --error && trivy fs --scanners vuln,secret,misconfig --exit-code 1 .

# TypeScript
check:
	biome check --write . && tsc --noEmit && vitest run
	semgrep scan --config auto --error && trivy fs --scanners vuln,secret,misconfig --exit-code 1 .
```

**Done means:** `make check` passes and `tester` reports PASS.

Writing tests is the tester's job; its rules live in `.claude/agents/tester.md`. You don't edit tests. If one looks wrong, say why in your handover.

---

## 11. Don'ts

- Floats for money. String-built SQL. Unbounded lists. Outbound calls without timeouts.
- Secrets in code, logs, error messages or prompts.
- Rules in routes, SQL outside repo files, HTTP objects inside services.
- Catch-all `except` / `catch` that hides errors.
- Hand-written frontend types that copy the API schema.
- Stack traces or internal names in responses.
- A second library for something the toolkit already covers.
- Renaming a public field in place.
- `SELECT *`, queries in loops.

---

## 12. Workflow for every backend task

Roles: `architect` plans, you build, `tester` verifies (`.claude/agents/`).

1. Read this file (and DESIGN.md §9 when writing user-facing messages). Confirm §0 is green.
2. Bigger than one small edit (new route, table, dependency, or a change across features)? Get a plan from `architect` and follow its steps in order.
3. State the single change and the feature folder it touches.
4. Search the codebase for something to reuse. Check current library docs via Context7 before using an API.
5. Implement that one change. Run `make check`.
6. Hand to `tester`: what changed, routes touched, and the step's acceptance criteria. Fix what it reports until PASS.
7. Stop for review with the tester's report plus one real request and response per changed route.
8. Deviated from this file? Add one line to `DECISIONS.md` (the architect owns that log).
