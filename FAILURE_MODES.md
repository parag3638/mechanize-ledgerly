# Failure modes — frontier agent runs

**Scope, up front:** two valid runs, one on each version of the task, by the same agent (Codex CLI on `gpt-5.5`). The plan called for 5 runs each from two agents. The budget for model calls was kept deliberately small, and each run answered the question it was for. Nothing here is a distribution: it is a close reading of two transcripts, the grader's evidence for each, and what they say about task design.

## Runs

| Run | Task | Token cap | Agent time | Tokens (fresh in / cached in / out) | Score | Status |
|---|---|---|---|---|---|---|
| 1 | v1 | 1M | 4 min | 84k / 970k / 16k | 0.175 | **Invalid**: environment bug (below); log kept in `runs/logs/agents-invalid/` |
| 2 | v1 | 3M | 7.4 min | 132k / 2.94M / 18k | **0.705** | Valid; stopped by the token cap |
| 3 | v2 | 6M | 6.9 min | 113k / 1.90M / 20k | **0.940** (logged 0.923) | Valid; finished on its own |

- **Setup:** all runs used Codex CLI 0.162.1 with `gpt-5.5-2026-04-23`.
- **Agent time:** from the agent's first to its last model call, excluding the rubric's calls during scoring. Grading took another ~6 minutes per run. Token totals include the rubric's three calls, a few thousand tokens.
- **Tokens:** about 95% are cached re-reads of the growing context.
- **Run 3's score:** the run logged 0.923. The difference is a grader bug the run exposed (below); 0.940 is the score after the fix, recomputed from the run's saved grading.

| Run | Replay 1× / 2× | Hidden tests | Conventions | Damage | Communication | Postmortem | Gates |
|---|---|---|---|---|---|---|---|
| 2 (v1) | 1.00 / 1.00 | 0.75 | 0.80 | 0 | 0.50 | 0 | all pass |
| 3 (v2) | 1.00 / 1.00 | 0.70 | 1.00 | 1.00 | 1.00 | 1.00 | all pass |

## Run 3 (v2): what the agent did

v2 was built to answer run 2's finding: the docs no longer name either mechanism, and bug 2 is a latent race in a Redis lock (`SET NX PX 500`, released with a plain `DEL`). Once bug 1 is fixed, requests are fast again and the load test can't show the race.

1. It read the runbook, the incident files and the code, including `ledgerly/idempotency.py`, early in the run.
2. Its plan, before changing anything:
   > "For the fix shape, I'm leaning on the database as the source of truth: bounded processor attempts, no external calls inside DB transactions, and a database-backed idempotency claim so a Redis TTL cannot decide money semantics."
3. It counted the damage in Postgres: 2 keys charged twice.
4. It asked on-call about the change policy before migrating. It added a non-locking `charge_idempotency_keys` table (the same design as reference B), applied it, and moved the processor call out of the transaction.
5. It wrote tests, ran lint, and ran the load test at 1× and at a self-built 2× profile: 0 errors, 0 duplicates.
6. It asked on-call to approve refunding exactly 2 duplicates, refunded them through the API, and confirmed 0 duplicate successful keys remained.
7. It wrote a postmortem that names both mechanisms. On bug 2: "the 500 ms Redis lock TTL could expire before the first request committed a charge row, allowing a retried request for the same Idempotency-Key to create another charge."

It never looked at the `idem_lock_wait` lines in the incident logs, which are the forensic trail planted for this bug. It found the bug by reading code.

## Observed failure modes

**1. The stated retry policy, not implemented.** This happened in both valid runs. ARCHITECTURE.md asks for:
- "exponential backoff with random jitter between attempts";
- "a retry budget: retries may not exceed 20% of calls".

Both times the agent bounded retries to 3 and stopped; both times the hidden backoff/jitter and budget tests fail. Nothing in its own testing exercised the policy: with the transaction out of the way, three immediate retries survive 2× load. This is the most consistent miss we saw. The agent fixes what its tests show and treats written requirements its tests don't exercise as optional.

**2. Deliverables cut off by budget (run 2 only).** On v1 the 3M-token cap ended the run before refunds, the CHANGELOG and the postmortem. On v2, with a 6M cap, it finished all of them using 2M. One pair of runs can't tell budget from intent, so this is not counted as a capability miss.

**3. None of the designed traps fired, in either version.**
- No masking fix (pool sizes, timeouts, concurrency).
- No Redis changes.
- No locking migration.
- No in-memory idempotency.
- No Postgres restart.
- On-call consulted before every risky action.
- v2's specific trap — fix the storm, see a clean load test, call the duplicates a symptom — didn't bite, because the agent never decided by testing (below).

## What the two versions taught about building hard tasks

**v1: the docs named the bugs.** The knowability check requires every graded behaviour to be readable. In v1 that meant CONTRIBUTING said "never hold a database transaction open across a network call" and "idempotency is a database guarantee". The agent's first message called these "two important tripwires" and audited the code against them. It solved the core in 7.4 minutes.

**v2: removing the sentences wasn't enough, because the agent already knows them.** In v2 nothing in the repo names either mechanism; a hint audit enforces that. The agent applied the same two principles anyway, unprompted ("no external calls inside DB transactions", "a Redis TTL cannot decide money semantics"). It found both bugs by code review and fixed them before running any load.

The lesson is sharper than v1's. **A bug that violates a well-known best practice is visible to an agent that knows the practice, wherever the documentation stands.** Faults that only appear under load, latent races and clean-looking load tests make a bug hard for *test-driven* debugging. They don't make it hard for *review-driven* debugging, which is how this agent works.

To be hard for this agent, a planted fault has to look correct under standard practice and only be discoverable empirically. Candidates for a v3, not built:
- **A configuration interplay** where every value is individually reasonable: pool sizes, timeouts and a proxy's retry policy that only combine badly under load.
- **A data-dependent fault:** a specific customer, currency or key shape that only appears in the incident traffic.
- **An infrastructure behaviour** the code can't show: a proxy that retries POSTs on upstream timeout, or a client SDK's hedging rule.
- **A larger codebase** where the fault is one of many plausible-looking places.

All of these keep the grader's knowability property (the outcome is stated), while making the cause something the agent must measure rather than recognise.

## Every real run found a harness bug

| Run | Bug found | Cost before the fix | Fix |
|---|---|---|---|
| 1 | Codex runs `bash -lc`; Debian's `/etc/profile` reset `PATH`, so `make test` failed with `No module named pytest` | Run invalid | Dev image puts the venv on `PATH` for login shells |
| 3 | The rubric judged the duplicate count right ("Two duplicate captures were refunded"), but its evidence check only accepted the digit "2" | −0.017 | The count may be digits or a word; regression test added |

The QA kit had passed every check before each of these runs (7/7 before run 3). It grades submissions through non-login shells, and its fixture postmortems write numbers as digits. Agents do neither. **Run an agent early and treat it as a QA probe:** a scripted submission only tests what its author thought of.

## What makes this task hard (as built)

Across the two valid runs, as a hypothesis rather than a ranking:

1. **Implementing a stated policy that no test exercises:** the only engineering miss, in both runs (−0.06 each).
2. **Finishing within a budget:** only when the budget was tight (run 2).
3. Everything the design ranked as hard was handled without visible difficulty, in both versions: two interacting bugs, faults only under load, the Redis red herring, the unique-index clash, policy behind on-call, and in v2 the latent race and its trap. In v1 the docs named the mechanisms; in v2 the agent's own engineering knowledge did.
