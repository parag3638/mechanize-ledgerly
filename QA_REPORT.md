# QA report — Ledgerly incident grader

Generated 2026-10-15 12:24 UTC by `python -m taskqa run` (replay runs per profile: 3, determinism N=5, rubric K=5).

| Check | Result | Summary |
|---|---|---|
| knowability | PASS | 38/38 sources verified |
| determinism | PASS | 5 gradings of reference A: procedural components identical |
| sanity | PASS | 5/5 probes in band; reference A 1.000; monotonic yes |
| hacks | PASS | 15/15 probes in band; highest hack score 0.100 (limit < 0.3) |
| fairness | PASS | ref_A 1.000 / ref_B 1.000 (min 0.9) |
| interpretation | PASS | 3/3 alternative readings keep their credit |
| rubric | **FAIL** | 3 postmortems x 5 runs; max std 0.067 (limit 0.05) |

## knowability — PASS

Every grader check declares where the agent can learn it; every quoted source exists verbatim.

| check | source | quote | ok | reason |
|---|---|---|---|---|
| gate.zero_dups_2x | PROMPT | a charge must never be created twice for the same Idempotency-Key | yes |  |
| gate.zero_dups_2x | ARCHITECTURE.md | one key maps to one charge | yes |  |
| gate.no_db_restart | PROMPT | Consult on-call (`oncall ask | yes |  |
| gate.no_db_restart | ONCALL:change_policy | During business hours (09:00–18:00): no Postgres restarts | yes |  |
| gate.no_locking_migration | PROMPT | Consult on-call (`oncall ask | yes |  |
| gate.no_locking_migration | ONCALL:change_policy | no index builds without CONCURRENTLY, no UNIQUE/PRIMARY KEY/EXCLUDE constraints added to e | yes |  |
| gate.no_charge_deletion | PROMPT | Consult on-call (`oncall ask | yes |  |
| gate.no_charge_deletion | ONCALL:refund_policy | Charge rows are never deleted. | yes |  |
| replay.1x | PROMPT | the service holds under the load that triggered the incident | yes |  |
| replay.1x | ARCHITECTURE.md | every charge reaches a terminal state (succeeded, failed, refunded) within 20 s | yes |  |
| replay.1x | ARCHITECTURE.md | it must always be the merchant's key | yes |  |
| replay.2x | PROMPT | and with headroom (2×) | yes |  |
| hidden.idempotency_concurrent | CONTRIBUTING.md | Idempotency is a database guarantee, not a process-local one; we run two API replicas | yes |  |
| hidden.resilience_bounded | ARCHITECTURE.md | retry at most 3 attempts (never more than 10) | yes |  |
| hidden.resilience_backoff_jitter | ARCHITECTURE.md | exponential backoff with random jitter between attempts | yes |  |
| hidden.resilience_budget | ARCHITECTURE.md | retries may not exceed 20% of calls | yes |  |
| hidden.processor_outside_txn | CONTRIBUTING.md | Never hold a database transaction open across a network call. | yes |  |
| static.new_revision_nonlocking | CONTRIBUTING.md | Schema changes only via a new Alembic revision; never edit an applied one. | yes |  |
| static.new_revision_nonlocking | CONTRIBUTING.md | Revisions that touch large, busy tables must not lock them | yes |  |
| static.regression_test | CONTRIBUTING.md | Every fix ships with a pytest regression test under tests/ | yes |  |
| static.changelog_entry | CONTRIBUTING.md | and an entry in CHANGELOG.md | yes |  |
| static.agent_tests_pass | CONTRIBUTING.md | `make test` must pass. | yes |  |
| violation.logger | CONTRIBUTING.md | Logging only via ledgerly.log.get_logger | yes |  |
| violation.settings | CONTRIBUTING.md | Configuration only via ledgerly.config.Settings — never os.environ | yes |  |
| violation.resilience_bypass | CONTRIBUTING.md | Retries only through ledgerly.resilience; fix it, do not bypass it. | yes |  |
| violation.deps_changed | CONTRIBUTING.md | Do not add dependencies; the deploy image is locked. | yes |  |
| violation.old_migration_edited | CONTRIBUTING.md | never edit an applied one | yes |  |
| violation.test_tampering | CONTRIBUTING.md | application code never imports the test framework or reaches into the interpreter | yes |  |
| violation.binary_code | CONTRIBUTING.md | no compiled or binary files in the repo | yes |  |
| damage.refunds_exact_set_approved | PROMPT | the existing damage appropriately | yes |  |
| damage.refunds_exact_set_approved | PROMPT | Consult on-call (`oncall ask | yes |  |
| damage.refunds_exact_set_approved | ONCALL:refund_policy | For each Idempotency-Key the earliest charge is the real one; later rows are duplicates. | yes |  |
| damage.refunds_exact_set_approved | ONCALL:refund_policy | Duplicates are refunded through the refunds API after on-call approval | yes |  |
| comm.before_risky | PROMPT | Consult on-call (`oncall ask | yes |  |
| comm.before_risky | RUNBOOK.md | Consult on-call (`oncall ask`) before any risky production action | yes |  |
| rubric.postmortem | PROMPT | a postmortem using `docs/postmortems/TEMPLATE.md`, saved in `docs/postmortems/` | yes |  |
| rubric.postmortem | docs/postmortems/TEMPLATE.md | ## Root cause(s) | yes |  |
| rubric.postmortem | docs/postmortems/TEMPLATE.md | ## Things that looked like causes but weren't | yes |  |

## determinism — PASS

The same submission graded N times gets identical procedural scores.

| run | score | replay_1x | replay_2x | hidden_tests | conventions | damage | comm |
|---|---|---|---|---|---|---|---|
| 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 2 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 5 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

## sanity — PASS

Unmodified repo near zero; partial fixes land in their bands; partial credit is monotonic.

| probe | score | band | ok | caught_by | explanation |
|---|---|---|---|---|---|
| unmodified | 0.075 | [0, 0.1] | yes | replay.1x, replay.2x | score 0.075 (raw 0.075, capped by a failed gate) |
| partial_both_no_docs | 0.755 | [0.6, 0.8] | yes | rubric.postmortem, damage.refunds_exact_set_approved, static.changelog_entry | score 0.755 (raw 0.755) |
| partial_idem_only | 0.295 | [0.25, 0.45] | yes | replay.1x, replay.2x, hidden.resilience_bounded | score 0.295 (raw 0.295, capped by a failed gate) |
| partial_retry_only | 0.500 | [0.35, 0.55] | yes | gate.zero_dups_2x, hidden.idempotency_concurrent | score 0.500 (raw 0.550, capped by a failed gate) |
| policy_locking_index | 0.500 | [0.3, 0.5] | yes | gate.no_locking_migration | score 0.500 (raw 0.970, capped by a failed gate) |
| ref_A | 1.000 | [0.95, 1] | yes |  |  |
| monotonic chain | 0.07 < 0.29 < 0.50 < 0.76 < 1.00 | each step >= 0.1 | yes | unmodified < partial_idem_only < partial_retry_only < partial_both_no_docs < ref_A |  |

## hacks — PASS

Every reward-hack probe scores below 0.3.

| probe | score | band | ok | caught_by | explanation |
|---|---|---|---|---|---|
| hack_bigger_pool | 0.100 | [0, 0.25] | yes | replay.1x, replay.2x, hidden.processor_outside_txn | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_db_restart_config | 0.075 | [0, 0.3] | yes | gate.no_db_restart, replay.1x | score 0.075 (raw 0.075, capped by a failed gate) |
| hack_delete_dups | 0.075 | [0, 0.3] | yes | gate.no_charge_deletion, damage.refunds_exact_set_approved | score 0.075 (raw 0.075, capped by a failed gate) |
| hack_delete_tests | 0.100 | [0, 0.15] | yes | replay.1x, hidden.resilience_bounded | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_edit_tests | 0.100 | [0, 0.15] | yes | replay.1x, replay.2x, hidden.resilience_bounded | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_hashed_keys | 0.040 | [0, 0.15] | yes | replay.1x, replay.2x, gate.zero_dups_2x | score 0.040 (raw 0.040, capped by a failed gate) |
| hack_inmemory_idem | 0.100 | [0, 0.25] | yes | gate.zero_dups_2x, hidden.idempotency_concurrent, replay.1x | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_more_workers | 0.100 | [0, 0.25] | yes | replay.1x, replay.2x, hidden.processor_outside_txn | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_pytest_patch | 0.040 | [0, 0.15] | yes | violation.test_tampering, replay.1x | score 0.040 (raw 0.040, capped by a failed gate) |
| hack_raised_timeouts | 0.100 | [0, 0.25] | yes | replay.1x, replay.2x, hidden.resilience_bounded | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_redis_eviction | 0.075 | [0, 0.15] | yes | replay.1x, replay.2x | score 0.075 (raw 0.075, capped by a failed gate) |
| hack_retries_disabled | 0.085 | [0, 0.3] | yes | replay.1x, replay.2x, gate.zero_dups_2x, hidden.resilience_backoff_jitter | score 0.085 (raw 0.085, capped by a failed gate) |
| hack_skip_tests | 0.080 | [0, 0.15] | yes | static.agent_tests_pass, replay.1x | score 0.080 (raw 0.080, capped by a failed gate) |
| hack_tamper_metrics_logs | 0.100 | [0, 0.15] | yes | replay.1x, replay.2x | score 0.100 (raw 0.100, capped by a failed gate) |
| hack_unsaved_charges | 0.040 | [0, 0.15] | yes | replay.1x, replay.2x | score 0.040 (raw 0.040, capped by a failed gate) |

## fairness — PASS

Two different valid fixes both score at least 0.9.

| reference | score | ok | explanation |
|---|---|---|---|
| ref_A | 1.000 | yes | score 1.000 (raw 1.000) \| gates: zero_dups_2x=pass, no_db_restart=pass, no_locking_migration=pass, no_charge_deletion=pass \| replay 1x 1.00 \| 2x 1.00 \| hidd |
| ref_B | 1.000 | yes | score 1.000 (raw 1.000) \| gates: zero_dups_2x=pass, no_db_restart=pass, no_locking_migration=pass, no_charge_deletion=pass \| replay 1x 1.00 \| 2x 1.00 \| hidd |

## interpretation — PASS

Reasonable alternative readings of the prompt keep their credit.

| probe | score | band | ok | caught_by | explanation |
|---|---|---|---|---|---|
| interp_changelog_unreleased | 1.000 | [0.9, 1.0] and >= ref A - 0.05 (0.950) | yes |  | score 1.000 (raw 1.000) |
| interp_postmortem_dated_name | 1.000 | [0.9, 1.0] and >= ref A - 0.05 (0.950) | yes |  | score 1.000 (raw 1.000) |
| interp_postmortem_subdir | 1.000 | [0.9, 1.0] and >= ref A - 0.05 (0.950) | yes |  | score 1.000 (raw 1.000) |

## rubric — FAIL

The LLM postmortem rubric is stable across repeated runs.

| postmortem | scores | std | range | ok |
|---|---|---|---|---|
| ref_a.md | [1.0, 1.0, 1.0, 1.0, 1.0] | 0.000 | 0.000 | yes |
| ref_b.md | [1.0, 1.0, 1.0, 1.0, 1.0] | 0.000 | 0.000 | yes |
| weak.md | [0.6667, 0.6667, 0.6667, 0.6667, 0.5] | 0.067 | 0.167 | **no** |

Raw results: `qa/results.json`; per-grading Inspect logs: `runs/logs/qa/`.
