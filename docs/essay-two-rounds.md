# Two rounds of making an RL task harder, and why the agent still won

I built one realistic task for coding agents: a payments service falls over under load, some customers are charged twice, and the agent takes over the incident. It has to find the cause, fix it without breaking production rules, refund the damage and write the postmortem. I spent most of the effort where it matters for an RL environment: a grader that produces a number you can trust, and a QA kit that proves it.

Then I ran a frontier agent on it twice, once on each version. It scored 0.705, then 0.940. This is what the two rounds taught me.

## The setup

The system is a small but real stack:
- two FastAPI replicas behind a proxy;
- a worker on a Redis stream;
- Postgres;
- a mock payment processor with a seeded, deterministic failure schedule.

Two bugs interact. The worker retries processor timeouts forever while holding a database transaction and the customer's row lock. Under load, that lock-up starves the API, clients retry, and duplicate charges appear.

The grader replays hidden traffic at 1× and 2× load from the agent's final database state. It measures what the client was told and what the processor actually captured, not what the agent's code wrote down. It also runs hidden tests in a separate container, checks repo conventions and production-policy gates from server-side audit logs, and judges the postmortem with an LLM rubric.

A QA kit (`taskqa`) checks the grader itself:
- 5 gradings of the same fix are identical;
- two different correct fixes both score 1.0;
- 15 reward hacks all score under 0.3, including deleting tests, patching pytest, deleting the duplicate rows, and replying 201 without saving the charge;
- partial fixes land in ordered bands;
- every graded behaviour is quoted from somewhere the agent can read.

## Round 1: the docs gave it away

That last property, *knowability*, was my first mistake. To make the hidden tests fair, I wrote the rules into the repo's CONTRIBUTING file: "never hold a database transaction open across a network call" and "idempotency is a database guarantee". Both are true and both are graded.

The agent's first message after reading the docs:

> "The runbook has two important tripwires: no transactions across network calls, and idempotency must be enforced in the database because there are two API replicas."

It then audited the code against those two rules and fixed both bugs in 7.4 minutes. It lost points only because its token budget ran out before refunds and the postmortem.

Making the graded behaviour knowable had turned into naming the bugs.

## Round 2: hide the mechanisms, plant a latent bug

For v2 I changed three things.

- **The docs state outcomes, not mechanisms.** For example: "one key maps to one charge, whichever replica it lands on and however long the first request takes". A new audit fails the QA if any agent-visible file names a planted mechanism.
- **Bug 2 became subtler.** Idempotency now rests on a Redis lock with a 500 ms TTL, released with a plain `DEL`. A first request stuck behind a locked customer row outlives its lock. The client's retry takes the lock, can't see the uncommitted first charge, and inserts a second.
- **I built a trap around it.** Once bug 1 is fixed, requests are fast again, the load test shows zero duplicates, and "the duplicates were a symptom of the storm" becomes the natural wrong conclusion. Only a hidden test that deliberately holds the first request for 3 s catches the latent race.

The QA kit confirmed the trap: a submission that fixes only the retry storm replays perfectly at 1× and 2× and is still capped at 0.5 by that test.

The agent scored 0.940. It read the lock module early. Before changing any code, it planned:

> "bounded processor attempts, no external calls inside DB transactions, and a database-backed idempotency claim so a Redis TTL cannot decide money semantics."

Those are the two rules I had deleted from the docs, applied unprompted. It never looked at the lock-wait lines I'd planted in the incident logs as evidence. It didn't need to.

## The lesson

Removing hints was necessary but not enough. **A bug that violates a well-known best practice is visible to an agent that knows the practice.** Faults that only appear under load, latent races and clean-looking load tests are hard for *test-driven* debugging. This agent debugs by *review*: it reads the code, recognises the anti-pattern, and fixes it on principle.

So a task that is hard for this agent needs a fault that looks correct under standard practice, and that only measurement reveals. For example:
- **A configuration interplay:** pool sizes, timeouts and a proxy's retry policy that are each sensible and only combine badly under load.
- **A data-dependent fault** that only the incident's traffic triggers.
- **Infrastructure behaviour the code can't show,** like a proxy that silently retries POST requests.

Each still keeps the outcome knowable while making the cause something to measure, not recognise.

## The one consistent miss

Both runs skipped the same requirement. The architecture doc asks for exponential backoff with jitter and a retry budget. Both times the agent bounded retries to three and stopped, because nothing in its own testing exercised the policy. Written requirements that no test exercises were the only thing it reliably dropped. That's a real, if small, capability gap, and a useful design lever: grade policy that can't be inferred from symptoms.

## Every real run was also a QA run

The QA kit passed every check before each agent run. Each run still found a harness bug:
- Codex runs commands in a login shell, which reset `PATH`, so `make test` failed. My scripted probes ran in a non-login shell and never saw it.
- The rubric correctly judged "Two duplicate captures were refunded" as the right count, but an evidence check only accepted the digit 2.

Both are fixed. The lesson: scripted submissions only test what their author imagined. Run a real agent early and treat it as one more QA probe.

## What's not done

- The task doesn't meet its own target of frontier agents averaging below 50%.
- There are two valid runs from one agent, not a distribution.
- The incident contains only two duplicate charges. That turned out to be a property of the new bug: it only fires when a request waits between 0.5 and 2 seconds, which the collapse rarely allows.

All of it is written up with numbers in `FAILURE_MODES.md`, `docs/calibration.md` and `DECISIONS.md`, and a v3 built around measurement-only faults is the natural next step.
