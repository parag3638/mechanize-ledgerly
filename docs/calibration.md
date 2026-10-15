# Calibration log

Every number that sets a grader threshold or a task knob, with the run that produced it. Stack: Colima 4 CPU / 6 GiB (aarch64), per-service caps from `task/compose.yaml`. Newest first.

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
