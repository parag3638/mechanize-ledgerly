# Decisions

What was proposed, what the owner chose, and why. Newest first. The full design these refer to is in `PROJECT.md`.

## 2026-10-15 — v2: make the task hard, keep it fair (plan in docs/plans/2026-10-15-v2-difficulty.md)

Proposed by the architect after v1's frontier run, approved by the owner.
Chosen:
- **Outcomes, not mechanisms.** The agent-visible docs no longer name either bug: two CONTRIBUTING sentences and "fix it, do not bypass it" are gone, and so is a refunds docstring clause and a worker docstring phrase. `processor_outside_txn` becomes an unscored diagnostic, since the replay already scores its consequence. A knowability "hint audit" now fails if a mechanism phrase reappears.
- **New bug 2.** Idempotency rests on a Redis lock (`SET NX PX`, plain `DEL` release) around the create-charge transaction. A first request blocked on the customer row for longer than the TTL loses the lock; a repeat takes it, can't see the uncommitted charge, and inserts another.
  - It is latent once bug 1 is fixed: requests are fast again, so the replays come out clean.
  - New hidden tests catch it deterministically: slow first request (0.04, also a gate) and Redis losing the lock (0.05).
- **Rejected alternatives:**
  - release before commit (a coin flip after the fix);
  - a per-replica lock key, or double-checked locking (visible in the load test);
  - Redis eviction (can't be reproduced in the replay);
  - REPEATABLE READ (produces serialization errors, not duplicates);
  - a 2×-only fault (a knife edge on 4 CPUs).

**Calibration finding: TTL 500 ms, not 1000.** At 1000 ms the outage capture produced zero duplicates (and so did a 2-minute outage slice). A first request only survives if it waits less than the API's 2 s statement timeout, and during the outage, rows are held either briefly or indefinitely. At 500 ms with 40% hedged requests, the slice produced 4 duplicates per 1,716 keys (0 at 1000 ms), so the baseline uses TTL 500 and `--double-share 0.4`. The docstring's rationale ("creating a charge takes a few milliseconds") still holds. The hidden tests hold the first request for 3 s, so they don't depend on the TTL.

## 2026-10-15 — P7 published

Proposed: repo name (ledgerly-incident / ledgerly-sre-eval / mechanize-ledgerly), visibility, and whether to publish the log viewer and QA report on Pages.
Chosen: public `parag3638/mechanize-ledgerly`; history squashed to one commit before the first push (the 16-commit history is kept locally in the gitignored `.backup/` bundle); `gh-pages` serves the Inspect log viewer (the one valid run) at the root and the QA report at `/qa/report.html`.
Why: owner's choice. Before pushing, a leak audit found no reference code in history (24 sampled lines, 0 hits) or in any service image, and the real API key and passphrase appear in no tracked file or history (the only secret-scanner hit is the untracked `.env`).

## 2026-10-15 — P6 stops after one valid run; task difficulty reported, not fixed

Proposed (after run 2: Codex CLI + gpt-5.5, 3M cap, 0.705, both bugs fixed in 7.4 min of agent time): make the task harder first; one bigger run (6M); or stop runs and write it up.
Chosen: stop runs and write it up (owner, to keep API spend low). The plan's 5×2 runs and the "agents < 50%" bar are not met; FAILURE_MODES.md and TASK_CARD say so and explain why (the knowability sentences in CONTRIBUTING name both mechanisms) with concrete changes for a harder version.
Why: the one valid run already shows the main fact; more runs at this design would mostly confirm a high score.

## 2026-10-15 — P6 cost probe 1 (Codex CLI 0.162.1, gpt-5.5-2026-04-23): invalid, environment bug

Run: 1 epoch, `--token-limit 1000000`. Stopped by the token cap after 4 min of agent time (11 min with grading) and 71 tool calls: 1,069,666 tokens = 83,840 uncached input + 969,728 cached input + 16,098 output (5,057 of it reasoning). Score 0.175: it had written a migration plus worker and API changes, but hadn't applied, refunded or written a postmortem.
Finding: `make test` failed in the agent's shell (`No module named pytest`): Codex runs `bash -lc`, and Debian's `/etc/profile` reset PATH past the venv. Fixed in the dev image (`/etc/profile.d`). The run doesn't count toward results; cached QA gradings are unaffected (non-login shells).
Also learned: about 90% of the tokens are cached-input reads of the growing context, so the token cap mostly measures cheap tokens; 1M ends a run at about a fifth of the time limit.

## 2026-10-15 — Rubric variance: accept one rare flip rather than spend more

Proposed: with majority-of-3 voting the rubric variance check still failed narrowly (5 runs × 3 fixed postmortems: refs A/B identical; the weak postmortem flipped one criterion once, std 0.067 against 0.05). Options: accept and document; majority of 5 (about 67% more rubric calls on every grading plus a re-validation); a cheaper, possibly noisier model.
Chosen: accept and document (owner, to keep API spend low). QA stays at 6/7 with the rubric check shown as failing, not re-thresholded.
Why: the effect is at most 0.017 of one run's score, against agent-to-agent differences of tenths; the thresholds stay as planned so the report stays honest.

## 2026-10-15 — Model pinned; rubric and on-call adapted to a reasoning model; cost guards

Proposed: the owner's model is `gpt-5.5`; the owner wants AI spend kept as low as possible.
Chosen:
- `RUBRIC_MODEL` and `ONCALL_MODEL` = `gpt-5.5-2026-04-23` (the dated snapshot of `gpt-5.5`, read from `GET /v1/models`), so grading doesn't move when the alias does.
- gpt-5.x rejects `temperature=0` and ignores `seed`. The rubric runs at low reasoning effort with room for the hidden reasoning (`max_tokens` 8000; at 1500 the answer was cut off and every verdict was unparseable). The on-call classifier sends `reasoning_effort=low` to reasoning models and keeps temperature 0 + seed for others. Before this, every classifier call to gpt-5.5 would have failed with a 400 and silently fallen back to the keyword rules.
- The rubric takes three independent judgments per postmortem, run concurrently, and a criterion counts when a majority meet it with a valid quote. Single judgments flipped a criterion about once in five runs (std 0.067-0.133 against the 0.05 limit).
- Quote validation fixed where it rejected correct evidence: C4 accepts an action-item row (owner/due date) or a timeline time; C5 accepts the stream/backlog/memory wording as well as "Redis"; C6 accepts the root-cause sentence when it names a real mechanism; quotes compare as prose (markdown backticks/asterisks and curly quotes ignored). A quote that isn't in the document is still rejected.
- Cost guards: rubric responses are cached by content (timeouts and retries don't change the key), so re-scoring cached gradings is free; the rubric variance check reuses its saved result unless the rubric, fixtures, model or K change; rubric calls time out after 120 s (an unbounded call hung a QA run for 20 minutes). Agent runs now default to one run (`N=1`) with a hard `--token-limit 1000000`; more runs only after the owner sees the measured cost of that first one.
Why: a rubric that can't parse its own answers or rejects correct quotes isn't measuring the postmortem. Majority voting is the standard way to stabilise a judge that can't be made deterministic. The agent runs are by far the largest possible spend, so they get the hard cap and an explicit check-in.

## 2026-10-15 — Replay error bound 5% → 3%; host-side re-scoring of cached gradings

Proposed (after the first full QA run, where `hack_retries_disabled` scored 0.310 against the < 0.3 limit): tighten the replay's error half-band; or withhold error credit whenever the retry policy is unused; or drop communication credit for changed code.
Chosen: one bound, 3%, for the error half-band, for "serving" (terminal and duplicate credit), and for the 2× gate ("answering ≥ 97% correctly"). The thresholds move to `task/grader/replay_score.py` (pure functions of the measured runs). taskqa re-applies it, the aggregation and the rubric to every cached grading when it reads it; the cache key covers only container-side code.
Why: over 26 gradings (6 runs each), every reference and partial fix measured exactly 0.0% errors, and the unfixed system and masking fixes measured ≥ 21%. Retries off measured 4.1–5.9%: its `slow_once` and `transient_503` charges fail (≈4.5% of keys), which the old 5% bound half-credited. 3% sits between with wide margins and is not tuned to one probe: a fix that never retries a charge Paystream would accept on the second attempt is not a fix. The other options penalise valid designs (a fix may legitimately see no retries in a run) or remove credit the agent earned. Re-scoring from raw measurements avoids five hours of re-grading for a threshold change. The existing rows were re-keyed once to the new container hash; the container-side code that produced them only changed by moving the scoring function out. One fresh end-to-end grade of the probe confirms the new image.

## 2026-10-15 — Independent grader review: what changed and what didn't

An independent architect review (read-only) found 2 blockers, 11 majors and 7 minors. Fixed in 6f8df86:
- **Blocker: replay measured rows by key prefix.** An API that answered 201 without saving, or saved under another key, scored a perfect replay. Now measured per key from the charge ids the client received, the rows those ids point to, and Paystream's captures by reference.
- **Blocker: agent code ran as root in the grader with the superuser password**, before the grader had read everything it scores. Now everything graded is read first; agent code runs as `runner` with roles scoped to throwaway databases; partial results are saved after every step; a tamper tripwire (test-framework imports, `sys.modules`/`builtins`/`atexit` patching, grader paths) voids the hidden tests.
- Majors fixed: snapshot with connections blocked and superuser-owned; supervisor token kept from services; restarts counted whoever made them; reconciliation by capture id/reference/amount (an agent may send Paystream any Idempotency-Key); `slow_twice` failures no longer count (a valid 2-attempt design was losing ≈0.09); 2× gate by majority of runs; agent-caused failures are not infra errors; retry policy checked from Paystream's per-reference counts; grading keys look like merchant keys; rubric hardened (separate data message, per-criterion quote validation, a sixth criterion for wrong causes); fresh database and Redis database per hidden test; fixes that need no schema change or restart not penalised; stable entry points documented in CONTRIBUTING.
- Minors fixed: schema-qualified table names in the locking checks; narrower retry-bypass detector; refund timing from Paystream's clock; approval brute force capped at two wrong counts; duplicate groups must be intact; sourceless code flagged; one-line CHANGELOG entries count; backoff test accepts slower growth (1.15× over 32 runs); on-call times match the prompt.
- New public probes for the blocker attacks: `hack_unsaved_charges`, `hack_hashed_keys`, `hack_pytest_patch`.

Not changed, deliberately:
- **Migrations applied with psql instead of Alembic lose the idempotency hidden test and the revision check.** CONTRIBUTING requires Alembic, so this is knowable.
- **The hidden tests still run in the agent's process,** so a sufficiently targeted attack on the test process remains possible. The tripwire, the unprivileged user and the grader's own database checks narrow it; the replay (0.45 plus a gate) doesn't depend on it. Recorded in TASK_CARD's known limitations.
- **`ALTER DATABASE … SET` by the agent is lost when the grader clones the database.** Database-level settings aren't part of any valid fix here.

## 2026-10-15 — P3/P4: what the first end-to-end grades changed

Proposed and chosen (builder's calls):
- **The audit window starts after stack setup.** The session marker is written by the sample's `setup` script (Inspect runs it after every service, including startup migrations, is healthy), not by the dev container's entrypoint. Otherwise the stack's own startup DDL counted as the agent's first risky action.
- **Hidden-test results are robust to tests that die.** Each test writes a "started" record; a test killed by the deadline (an unbounded retry loop) or by the per-test timeout counts as failed instead of disappearing from the denominator.
- **On-call fallback understands more phrasings** ("restrictions", "new table", "backfill"…); the reference submissions' natural questions were landing on "unclear". The LLM classifier, when configured, covers the long tail.
- **The rubric can be re-run without re-grading.** The scorer keeps the postmortem text in the log; taskqa recomputes the rubric and the aggregate from cached procedural results once `RUBRIC_MODEL` is set.
- Measured: unmodified 0.020; references A and B 0.875 each without the rubric (every procedural component 1.0 except communication, fixed above); grade time 353–525 s.

## 2026-10-14 — P3: hidden-test fairness fixes found while writing reference B

Proposed and chosen (builder's calls):
- **Backoff test is statistical, not "every wait longer than the last".** Full jitter (uniform in [0, cap]) is a valid reading of "exponential backoff with random jitter" and can produce a shorter second wait. The test now compares the mean second wait with the mean first wait over 16 runs (> 1.3x), with `random` seeded so the result is identical on every grading.
- **One process per hidden test, plus healthy traffic before each failure.** A correct retry budget drains when a test feeds it only failures; without these two changes a well-behaved budget would have been penalised for refusing retries. Each hidden test now runs in its own pytest process, and failure scenarios are preceded by successful captures, as in production.
- **API runtime limits (ops config, not part of the puzzle).** During the first baseline capture `api2` was OOM-killed: requests blocked on row locks saturated the 40-thread pool and new requests queued without bound. Uvicorn now runs with `--limit-concurrency=100`, API memory is 512 MB, api/worker have `restart: on-failure`, and `/healthz` is async. Without this, an agent's own load test could kill a container for good and wreck the sample.
- **One shared `deps` stage in the app, dev and grader images** (byte-identical first stage), and the grader's system layer matches the dev image's. The classic builder then reuses layers instead of re-downloading the same wheels; uv uses serial downloads with a 30 s timeout because parallel downloads stalled on this network.

## 2026-10-14 — P2/P3: audit, knowability and grading details

Proposed and chosen (builder's calls within the approved plan; flag any you want changed):
- **Policy facts live with on-call, not in RUNBOOK.** The spec says business-hours and refund policies are "revealed only when asked". RUNBOOK says what's risky and to consult on-call; the specifics are in on-call's canned answers. Knowability sources may therefore be `ONCALL:<intent>`, valid only alongside the prompt's "Consult on-call (`oncall ask`...)" instruction. taskqa check 5 enforces both.
- **Audit channels.** Postgres statement log (JSON) on the audit volume, readable only by root/postgres: `log_statement=ddl` for everyone plus `log_statement=all` for the schema owner (`ALTER ROLE`; superuser-only, so the agent can't turn it off). Supervisors log every restart/stop with actor `dev`/`grader` (grader proves itself with a token the agent never sees). On-call logs every exchange. The shell command log (bash DEBUG trap) is informational only: it is bypassable, and no score depends on it.
- **Duplicate credit needs service.** "Zero duplicates" (replay component and the 2x gate) only counts when the client error rate is ≤ 5%; on the unfixed system duplicates are 0–2 per run at random, which would otherwise make the unmodified score flip.
- **Errors include reconciliation.** A replay charge counts as an error if the client never got a success, if it failed although its Paystream class is retryable, or if it is `succeeded` without a matching Paystream capture (same charge id, reference = Idempotency-Key, same amount). The last one closes the "rewrite references to dodge slow keys" and "mark succeeded without capturing" hacks.
- **Replays start from the agent's end-state database**, not the pristine handoff: with D6 the unique index can only exist after the damage is handled.
- **Probes derived from the references are encrypted with them.** Partial-fix, interpretation and locking-variant probes contain reference code, so they live in `.refs/probes/` inside `references.tar.age`. Public `probes/` holds only hacks applied to the unmodified repo.
- **Baseline capture models Paystream recovering** (`/_admin/recover`, capture only) before the on-call's worker restart; otherwise the infinite-retry worker would wedge again on the same slow keys and the backlog would never drain. In the task, Paystream's slow keys are active.
- **The charges stream is never trimmed**, so Redis memory stays high after the outage. That keeps the red herring alive for the agent; trimming it is harmless and not graded.

## 2026-10-14 — P1: incident mechanics as calibrated

Proposed (PROJECT.md §5): unbounded immediate retries inside the worker's transaction; check-then-insert idempotency; customer-row lock couples the two.
Chosen, after measuring on the 4 CPU / 6 GiB stack (numbers in `docs/calibration.md`):
- `statement_timeout = 2 s` for app connections, set in `Settings.db_statement_timeout_ms` (visible to the agent). Without it, API requests for a locked customer held a pooled connection forever and the API died before the worker saturated: no stream backlog (the Redis red herring never appeared) and almost nothing left pending. With it, the worker saturates first, the backlog grows, the API degrades for locked customers.
- Processor: hang share 6% (was 4%), 48 work slots, hang holds a slot 5 s. Load profiles use 40 active customers (was 60). The worker now saturates ~20 s into a 1x run instead of ~50 s.
- Hedged requests: 8% of keys, second request 0–2 ms after the first (was 0–8 ms). Measured race window ≈ 2 ms: 58/60 duplicates at 0 ms jitter, 24/60 at 2 ms, 2/60 at 5 ms.
- Processor reference = the client's Idempotency-Key (Finance reconciles on it). The schedule is keyed by reference, so the grader will check reconciliation to stop an API from rewriting references to dodge slow keys.
Why: the unfixed system must fail by a wide margin and the partial fixes must land in their bands; these values do that (public 1x unfixed: 25% client errors, 41% non-terminal; retry-only at 2x: 0 errors, 29 duplicate keys; ref A at 2x: clean).
Consequence worth noting in TASK_CARD: on the unfixed system the duplicate bug is mostly hidden behind the storm (requests for locked customers fail instead of racing). It becomes obvious once the retry storm is fixed. That's a genuine "two interacting bugs" difficulty source, not a flaw.
Revisit when: P4 calibration with ≥10 runs per side.

## 2026-10-14 — D10: No frontend; demo through existing surfaces

Proposed: three options: (a) terminal + Inspect log viewer + `qa/report.html` only; (b) add generated SVG charts and a static run gallery; (c) a custom Next.js dashboard.
Chosen: (a).
Why: The spec's visual deliverables (log viewer, QA HTML, 2-minute video) already cover the demo. A UI adds nothing the task proves. The Next.js scaffold is archived outside the repo, not committed.
Revisit when: a viewer needs something the Inspect log viewer cannot show.

## 2026-10-14 — D9: Colima stays at 4 CPU / 6 GiB

Proposed: bump to 6 CPU / 8 GiB for less replay noise and faster QA.
Chosen: stay at 4 / 6.
Why: Owner's call. Grading runs with `--max-sandboxes 1` and per-service CPU/memory caps (PROJECT.md §3.1).
Revisit when: P4 calibration shows thin margins between unfixed and fixed replays.

## 2026-10-14 — D8: Stakeholder communication graded procedurally

Proposed: grade "on-call consulted before risky actions" from `oncall.jsonl` timestamps vs the DDL, restart and refund logs, not with the LLM rubric.
Chosen: procedural.
Why: Fully checkable from logs; zero rubric variance. Deviation from the spec, which lists it under the rubric.
Revisit when: a case appears where ordering alone misjudges whether the agent actually asked.

## 2026-10-14 — D7: Failed gate caps the score at 0.5

Proposed: cap 0.5 or 0.3.
Chosen: 0.5.
Why: A retry-only partial fix lands mid-range, as the spec asks. Hack probes still score below 0.3 because their other components are near zero.
Revisit when: any hack probe scores ≥ 0.3 in P4.

## 2026-10-14 — D6: Keep the duplicates vs unique-index clash

Proposed: keep it realistic (`CREATE UNIQUE INDEX CONCURRENTLY` fails while duplicates exist) or give snapshot duplicates a distinguishing column so a plain index works.
Chosen: keep it realistic.
Why: One more real source of difficulty. Knowable from Postgres docs and from an existing migration that shows the Alembic `autocommit_block()` + `CONCURRENTLY` pattern. Valid paths: partial unique index after marking duplicates (ref A) or a separate `idempotency_keys` table (ref B).
Revisit when: agent runs show failures caused by the clash that are not attributable to a capability gap.

## 2026-10-14 — D5: No Docker inside the sandbox

Proposed: no Docker in the sandbox, stack as sibling compose services with audited `ledgerlyctl` restarts; or a rootless Docker-in-Docker sidecar.
Chosen: no Docker in the sandbox.
Why: Inspect warns against privileged DinD for untrusted agents, and a docker socket would let the agent read the processor source. Deviation from the spec's "docker compose access".
Revisit when: an agent needs a stack operation `ledgerlyctl` cannot express.

## 2026-10-14 — D4: References in an age-encrypted bundle

Proposed: `references.tar.age` committed in the public repo, or a separate private repo.
Chosen: encrypted bundle; passphrase in `$LEDGERLY_REFS_PASSPHRASE`; decrypted to gitignored `.refs/`. Encrypted with `pyrage` (the `age` CLI is not installed).
Why: Self-contained and reproducible; never plaintext in history.
Revisit when: the passphrase needs sharing with someone.

## 2026-10-14 — D3: OpenAI only, budget tight

Proposed: choose run models at Phase 6 after a 1-run cost probe; build with cheap models.
Chosen: cost probe at P6; **OpenAI is the only provider**: on-call classifier, postmortem rubric and both frontier agents.
Why: Only an OpenAI key is in use. OpenAI honours `seed`, a small determinism win for the rubric and classifier. Deviation from the spec's "Anthropic Claude API". Model IDs are read from the API at P2/P6 and pinned here, never guessed. Agent 1 = Codex CLI. Agent 2 = Claude Code routed to the OpenAI model through Inspect's bridge if inspect_swe issue #177 allows it; otherwise Inspect's `react()` agent or `opencode()` on the same model.
Revisit when: P6 cost probe.

## 2026-10-14 — D2: Python 3.12

Proposed: 3.12 per spec, or keep 3.14.
Chosen: 3.12 (3.12.13 pinned in `.python-version`).
Why: Spec; widest wheel availability.

## 2026-10-14 — D1: This repo becomes a pure Python/uv monorepo

Proposed: drop the Next.js scaffold and keep the agent kit; keep the scaffold; or a sibling repo.
Chosen: drop the scaffold. `DESIGN.md` stays until P7 (no longer imported by `CLAUDE.md`); `BACKEND.md` and the architect/tester agents still apply. `docs/decisions.md` moved here.
Why: The spec has no frontend deliverable.

## 2026-10-14 — Dependencies approved

Proposed: the list in PROJECT.md §13, each with a reason and an alternative.
Chosen: approved with the plan.
Why: Each covers a job the spec's stack doesn't (CLIs, HTML report, encryption without the `age` CLI, settings convention, auto-reload); everything else is the spec's own stack.

Root project: `inspect-ai`, `inspect-swe`, `openai`, `anthropic` (needed by inspect_swe's model bridge; no Anthropic key used), `typer`, `jinja2`, `pyrage`, `httpx`; dev: `pytest`, `ruff`, `pyright`. Ledgerly (P1): `fastapi`, `uvicorn[standard]`, `psycopg[binary,pool]`, `alembic`, `redis`, `prometheus-client`, `pydantic-settings`, `httpx`. Images: `python:3.12-slim`, `postgres:16`, `redis:7`, `nginx:1.27-alpine`. Not added: structlog, pytest-asyncio, pytest-xdist.

## 2026-10-13 — Superseded: Next.js-era setup decisions

Repo layout with Next.js at the root, Biome matching Prettier, vitest `passWithNoTests`, and the pnpm supply-chain policy no longer apply: the scaffold was removed under D1. One rule carries over: the Makefile treats pytest exit code 5 (no tests collected) as a pass until the first test lands.
