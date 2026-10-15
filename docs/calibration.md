# Calibration log

Every number that sets a grader threshold or a task knob, with the run that produced it. Stack: Colima 4 CPU / 6 GiB (aarch64), per-service caps from `task/compose.yaml`. Newest first.

## 2026-10-16 — v2: the Redis idempotency lock

**Unfixed load test (public 1×, 3 fresh stacks, TTL 1000 ms):** errors 28.9% / 23.5% / 24.5%; non-terminal 50.2% / 40.0% / 48.6%; 0 duplicates. Bug 1's collapse is intact with the lock added.

**Stalled-request check** (dev stack; an admin session holds the customer row, the repeat goes to the other replica after the TTL):

| Case | Result |
|---|---|
| Row held | 2 rows, 2 of 2 times |
| No stall (fresh customers) | 1 row, 6 of 6 times, all requests under 70 ms |

**Duplicates during the outage, by lock TTL and hedge share:**

| Run | Keys | Errors | Duplicate keys |
|---|---|---|---|
| Public 1×, TTL 500 / 250 | 588 | 19% / 25% | 1 / 0 |
| Outage slice 15/s, 2 min, hedge 0.4, TTL 1000 / 500 | 1,716 | 87% / 84% | 0 / 4 |
| Full outage 15/s, 10 min, hedge 0.4, TTL 500 | 8,989 | 97% | 1 |
| Slice 10/s, 2 min, hedge 0.4 / 0.6, TTL 500 | 1,170 | 31% / 72% | 1 / 4 |
| **Full outage 10/s (1×), 10 min, hedge 0.6, TTL 500 (kept)** | 5,905 | 92% | **2** |

**Why so few.** A duplicate needs a first request that waits longer than the TTL yet finishes inside the 2 s statement timeout. Once all 12 worker threads are stuck, customer rows are held indefinitely, and those requests fail instead.

**Kept baseline:** 2 duplicate keys, 2 rows, both captured at Paystream (at 11:21:57 and 11:28:01). Each shows `idem_lock_wait` with `waited_ms` 505 and 499.

**Calibration grades** (through taskqa, 3 replays per profile, gradings take about 380 s):

| Submission | Score | Band | Notes |
|---|---|---|---|
| unmodified | 0.055 | [0, 0.10] | Both new hidden tests fail; the grader also finds the duplicate in the database |
| partial_idem_only | 0.325 | [0.25, 0.45] | |
| partial_retry_only | 0.50 (raw 0.635) | [0.35, 0.55] | **All 6 replays clean** (0 errors, 0 duplicates). Only the slow-first test and its gate catch it: the trap holds |
| partial_retry_no_lock | 0.49 | [0.30, 0.50] | 7–36 duplicate keys per replay; both duplicate gates fail |
| partial_both_no_docs | 0.755 | [0.60, 0.80] | |
| partial_retry_lock_ttl | 0.95 | [0.85, 0.97] | Fails only the Redis-loss test |
| policy_locking_index | 0.50 (raw 0.97) | ≤ 0.5 | |
| ref A / ref B | 1.000 / 1.000 | ≥ 0.9 | Every replay clean; all hidden tests pass; the rubric is unanimous on all six criteria |

## 2026-10-15 — P3: first end-to-end grade (unmodified repo, through Inspect)

Score 0.020 (expected band [0, 0.10]); grader time 525 s (budget 900 s), of which the six replays took 517 s.

| Replay | Error rate | Non-terminal | Duplicate keys |
|---|---|---|---|
| 1x run 1 / 2 / 3 | 20.7% / 22.0% / 25.3% | 44.7% / 29.2% / 42.0% | 1 / 1 / 5 |
| 2x run 1 / 2 / 3 | 77.6% / 74.7% / 77.4% | 39.4% / 38.3% / 42.1% | 8 / 5 / 3 |

No unexpected processor failures and no unreconciled captures. The hidden tests didn't run in this grade (a collection bug, fixed in cdece1b); with the fix the unmodified repo passes 2 of 8 hidden tests (a sequential retry with the same key; one timeout retried), worth ≈ 0.055, so its expected score is ≈ 0.075.

Baseline capture (outage profile seed 9001, 15/s, 20% hedged, 10 min): 8,989 keys, 95% client errors, 4,683 charges left pending until the restart, 11 duplicate keys (11 duplicate rows). The plan's 30–60 duplicate target was not reached: the collapse is so complete that few hedged pairs get to race. 11 is enough for the damage-handling step; the count is what matters, not its size.

## 2026-10-14 — P1 exit: unfixed public 1x on 5 fresh stacks

| Run | Client error rate | Non-terminal | Duplicate keys |
|---|---|---|---|
| 1 | 20.2% | 240 (40.8%) | 1 |
| 2 | 27.4% | 193 (32.8%) | 0 |
| 3 | 19.7% | 276 (46.9%) | 2 |
| 4 | 29.6% | 269 (45.8%) | 2 |
| 5 | 33.7% | 274 (46.6%) | 1 |

5/5 reproduce: errors 4–7x the 5% threshold, non-terminal 16–23x the 2% threshold. Duplicate keys on the unfixed system are 0–2 per run, so a "zero duplicates" credit must only count when the system served traffic (error rate ≤ 5%); otherwise the unmodified score would flip between runs.

Schedule change after this run: slow-once 4% → 3%, transient-503 2% → 1.5%. Correct-client retry demand drops from 20% to 18.5% of first attempts, below a 20% budget even when the budget counts first attempts only. Re-verified in P4.

## 2026-10-14 — P1 first calibration

Processor: seed `paystream-2026`, 48 slots, hang 6% (5 s per attempt), slow-once 4%, slow-twice 1%, transient-503 2%, declined 0.5%. Profiles: 40 customers, 8% hedged pairs with 0–2 ms jitter.

| Run | Profile | Client error rate | Non-terminal | Duplicate keys | Notes |
|---|---|---|---|---|---|
| unfixed | public 1x (seed 4242, 60 s) | 25.3% | 243 (41.3%) | 1 | worker saturated ~20 s; processor 48 in flight + queue |
| retry-only partial | hidden-candidate 2x (seed 7102, 50 s, 1019 keys) | 0% | 0 | 29 | healthy; hedged pairs race the check-then-insert |
| ref A | same 2x | 0% | 0 | 0 | failed 73 (hang + declined classes) |
| ref A | hidden-candidate 1x (seed 7101, 50 s, 541 keys) | 0% | 0 | 0 | failed 34 |

Hedged-pair race window, measured on an idle stack (60 pairs each): jitter 0 ms → 58 duplicates, 2 ms → 24, 5 ms → 2.

Earlier settings that failed, kept for the record:
- No `statement_timeout`: the API's pool drained on row locks within ~15 s while only 8 worker threads were stuck; stream lag 0, Redis memory flat, 8 charges pending, 1 duplicate. The red herring never appeared.
- Hang share 4% with 60 customers: worker saturated only ~50 s in; 13.8% errors, 13.5% non-terminal. Too close to the thresholds.
