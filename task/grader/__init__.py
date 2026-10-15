"""Grader for the Ledgerly incident task.

Container side (runs in the `grader` service): run, static, hidden_tests, damage, replay_runner.
Host side (runs in the Inspect process): scorer, rubric, aggregate, solvers.
Shared: checks (the registry of every check, its weight and its knowability source).
"""
