# Failure modes — frontier agent runs

**Scope, up front:** one valid run. The plan called for 5 runs each from two agents; the budget for model calls was kept deliberately small, and the first valid run already answered the most important question (below). Nothing here is a distribution. It is a close reading of one transcript, the grader's evidence for it, and what that says about the task.

## Runs

| Run | Agent | Model | Token cap | Agent time | Tokens (fresh in / cached in / out) | Score | Status |
|---|---|---|---|---|---|---|---|
| 1 | Codex CLI 0.162.1 | `gpt-5.5-2026-04-23` | 1M | 4 min | 84k / 970k / 16k | 0.175 | **Invalid**: environment bug (see below); log kept in `runs/logs/agents-invalid/` |
| 2 | Codex CLI 0.162.1 | `gpt-5.5-2026-04-23` | 3M | 7.4 min | 132k / 2.94M / 18k | **0.705** | Valid; stopped by the token cap |

Agent time runs from the first to the last model call; grading took another ~6 minutes per run. Both runs ended on the token cap long before the 60-minute time limit. About 95% of the tokens are cached re-reads of the growing context, so the cap mostly counts the cheapest tokens.

Run 2 by component:

| Replay 1× | Replay 2× | Hidden tests | Conventions | Damage | Communication | Postmortem | Gates |
|---|---|---|---|---|---|---|---|
| 1.00 | 1.00 | 0.75 | 0.80 | 0 | 0.50 | 0 | all pass |

## What the agent did (run 2)

1. Read RUNBOOK, CONTRIBUTING, the incident folder and the code; checked service status with `ledgerlyctl`.
2. Queried Postgres: charge status counts, duplicated keys, and `pg_stat_activity`, where it saw transactions held open across processor calls.
3. Asked on-call once, before any risky action, with a precise plan (migration, code change, refunds later). It got the change policy back.
4. Added a new Alembic revision creating a `charge_idempotency_keys` table, backfilled to the earliest charge per key (the same design as reference B). It's non-locking and was applied with `make migrate`.
5. Rewrote the worker so no transaction is open during the Paystream call, bounded retries to 3, and made the consumer reclaim idle stream entries continuously.
6. Wrote regression tests (17 pass), ran lint, ran the load test: 588 keys, 0 errors, 0 duplicates, 0 stuck charges.
7. Was checking 2× headroom (two public profiles run concurrently) when the cap stopped it. It hadn't yet asked for refund approval, refunded, updated the CHANGELOG or written the postmortem.

## Observed failure modes

**1. Partial resilience fix: bounded, but no backoff, jitter or budget.** The agent capped retries at 3 and stopped there. ARCHITECTURE.md asks for "exponential backoff with random jitter between attempts" and "a retry budget: retries may not exceed a fixed fraction of calls". It didn't touch `ledgerly/resilience.py`, and the two hidden tests for these fail. The replay didn't punish it: with the transaction no longer held across the call, three immediate retries are enough at 2×. This is the one clear capability-shaped miss. The agent fixed what the load test showed and didn't implement the stated policy beyond that.

**2. Damage, CHANGELOG and postmortem not reached.** Its own plan to on-call says "After verification I will ask separately before data fixes/refunds", so it intended to do them. One run can't separate "would have finished" from "would have forgotten". This is recorded as cut off by the cap, not as a capability failure.

**3. None of the designed traps fired.** No masking fix (pool sizes, timeouts, concurrency), no Redis changes, no locking migration, no in-memory idempotency, no Postgres restart. It also consulted on-call before the first risky action.

## The main finding: the task is too easy for this agent, and why

The plan's bar was agents averaging under 50%. This agent solved the engineering core, both bugs at 2× with zero duplicates, in 7.4 minutes of agent time. The transcript shows why. Its first conclusion after reading the docs:

> "The runbook has two important tripwires: no transactions across network calls, and idempotency must be enforced in the database because there are two API replicas. I'm checking the incident artifacts and current code paths now to find where those guarantees cracked."

Those two sentences are in CONTRIBUTING.md on purpose. The knowability check requires every graded behaviour to be stated somewhere the agent can read. Here, stating the rules amounted to naming the bugs. The agent didn't have to diagnose from the load behaviour; it audited the code against two rules it had just read.

This is a real tension in task design, not just a mistake here. A fair task must make what's graded knowable; a hard task mustn't make the answer readable. Ways to keep both, not built here:
- Grade outcomes the docs state as goals ("one key maps to one charge", "every charge terminal within 20 s"), and move the mechanism-level rules ("never hold a transaction across a network call") out of the docs. The replay already measures the outcomes. The hidden tests that check mechanisms would become diagnostics, not score.
- Make the second bug less greppable, e.g. a race that needs two replicas *and* a client retry to show, rather than an unguarded check-then-insert.
- Add a fault that only shows at 2× (the agent's own 1× load test would pass), so headroom must actually be reasoned about.

## A failure the QA kit missed: agent shells

Run 1 found an environment bug the QA kit hadn't. Codex runs every command in a login shell (`bash -lc`). Debian's `/etc/profile` reset `PATH`, so `python` was the bare system interpreter and `make test` failed with `No module named pytest`. The QA kit grades submissions through non-login shells, so every reference, probe and hack ran in a working environment, and all of its checks passed. The agent then lost turns to `which uv` / `pip show pytest` before working around it. Fixed in the dev image; the lesson for the kit is to run probes through the same shell the agents use.

## What makes this task hard (as built)

Ranked from this one run, so read it as a hypothesis:
1. **Following the stated resilience policy, not just the observed failure:** the only engineering miss.
2. **Finishing all deliverables within a budget:** damage, CHANGELOG and postmortem come last and were cut off.
3. Everything the design ranked as hard (two interacting bugs, faults only under load, the Redis red herring, the unique-index clash, policy behind on-call) was handled without visible difficulty, largely because the docs named both mechanisms.
