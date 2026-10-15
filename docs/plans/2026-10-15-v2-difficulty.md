# v2 — make the task hard, keep it fair

Approved 2026-10-15. Target: frontier agents average below 50% while QA stays green (determinism, sanity bands with monotonic credit, every hack below 0.3, references at or above 0.9, knowability at 100%, interpretation). The rubric-variance limitation stays as documented.

## Why

In v1, one Codex + gpt-5.5 run fixed both bugs in 7.4 min (0.705). CONTRIBUTING named both mechanisms: "never hold a transaction across a network call" and "idempotency is a database guarantee". On top of that, the race was a greppable SELECT-then-INSERT.

## Changes

1. **Grade outcomes, not mechanisms.**
   - Remove both mechanism sentences from CONTRIBUTING, and "fix it, do not bypass it" from the retries line.
   - `hidden.processor_outside_txn` becomes the unscored diagnostic `diag.processor_outside_txn` (new kind `diagnostic`, weight 0). The replay already punishes the behaviour.
   - Keep the resilience policy in ARCHITECTURE and the production policy in RUNBOOK.
2. **New bug 2: a Redis idempotency lock whose TTL is shorter than a slow request.**
   - `ledgerly/idempotency.guard`: `SET idem:{key} NX PX 1000`, poll every 20 ms for up to 3000 ms, then 409.
   - The lock is released with a plain `DEL` in `finally`, so there is no owner check.
   - It wraps the whole create-charge transaction and logs `event=idem_lock_wait` with `waited_ms`.
   - **How it breaks:** a first request blocked on the customer row for more than 1 s loses the lock. The retry or hedged copy takes it, can't see the uncommitted row, and inserts again. The first request's `DEL` frees the second's lock, which allows triples.
   - **Why it's a trap:** it's latent once bug 1 is fixed. The public 1× load test shows zero duplicates.
3. **New hidden tests** (two replicas, statement timeout raised to 10 s for these processes only; sequencing driven by `pg_stat_activity`).
   - **S1 `hidden.idempotency_slow_first`** (0.04): the customer row is held, A blocks, 3 s later B arrives on the other replica with the same key, and there must be one row. It also feeds the new **gate `gate.slow_request_one_charge`**.
   - **S2 `hidden.idempotency_redis_loss`** (0.05): the same, with `FLUSHDB` after A blocks. Weighted, not gated. If the pilot scores ≥ 0.5, gating it is a one-line change, re-scored host-side.
   - **Weights:** `hidden.idempotency_concurrent` drops from 0.08 to 0.02 and `hidden.resilience_budget` rises from 0.02 to 0.03. Hidden tests still total 0.20.
4. **Rejected options and reasons:**
   - *Release before commit:* a coin flip after the fix, so scores flap.
   - *Per-replica lock key:* a naming bug that's visible in the load test.
   - *Double-checked locking:* textbook and visible.
   - *Removing only the doc sentence:* the race stays greppable.
   - *Redis eviction of lock keys:* can't be reproduced in the replay and breaks the red herring.
   - *REPEATABLE READ:* produces serialization errors, not duplicates.
   - *Finance-job lock injector:* adds a new process.
   - *A 2×-only fault:* on a 4 CPU VM that's a knife edge.

## Steps (each is builder, then tester, then an acceptance check)

0. Tag `v1-published`.
1. Docs and registry, plus a knowability "hint audit" (phrases that must not appear in `ledgerly/`).
2. SUT bug, config and visible test (it passes on the buggy code).
   - **Manual check:** a stalled duplicate gives 2 rows; without the stall, 1 row.
   - **Load test:** unmodified, 3 runs, each with ≥ 10% errors and ≥ 25% non-terminal.
3. Regenerate the baseline (`make baseline`).
   - `dup_rows` in [10, 60], and every duplicate is refundable.
   - `idem_lock_wait` evidence appears in the logs.
   - Update the timeline, the on-call intents and questions.
4. References A/B rebased and probes rebuilt. New partials:
   - `partial_retry_lock_ttl`, band [0.85, 0.97];
   - `partial_retry_no_lock`, band [0.30, 0.50].

   Postmortem fixtures rewritten.
5. Hidden S1/S2, the gate, `hidden_tests.py`, `aggregate.py`. Hidden step run 5× per submission with identical results.
6. Rubric ground truth: mechanism 2, C2 anchor and regex. K=5 variance at or below v1's.
7. Calibration grades (unmodified, three partials, ref A, ref B). Bands met, `grade_seconds` < 900, and `partial_retry_only`'s 2× replay is clean (the trap holds).
8. Full `make qa`.
9. Encrypt the references, update the docs, run the leak audit.
10. Pilot: one capped agent run, approved by the owner before it runs.

## Cost

- **Local:** about 6 h of compute (the full QA is about 3 h).
- **API during the build:** about 60 rubric calls and under 10 on-call calls.
- **Pilot:** the only significant spend.
