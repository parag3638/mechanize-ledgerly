"""Step 3: hidden tests, then the agent's own test suite.

Everything that imports the agent's code runs as the unprivileged `runner`
user, with database roles scoped to throwaway databases, never as root and
never with the superuser password. /grader (facts, profiles, results) is not
readable by `runner`.

Hidden tests: one pytest process per test, each against a fresh copy of a
migrated template database and its own Redis database; every `runner` process
is killed after each test. Results come from the grader-owned reporting hook;
a test that started but never reported counts as failed. For the idempotency
tests the grader also checks the database itself afterwards, outside the
agent's process.
"""

import json
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from psycopg import sql

from grader import env
from grader.checks import CHECKS

HIDDEN_DB = "ledgerly_hidden"
HIDDEN_TEMPLATE = "ledgerly_hidden_tpl"
HIDDEN_REDIS = "redis://redis:6379/3"
HIDDEN_CHECKS = [c.id for c in CHECKS if c.kind == "hidden_test"]
RUN_ROOT = Path("/tmp/grading")
RUN_TREE = RUN_ROOT / "tree"
RUN_TESTS = RUN_ROOT / "hidden"
RUN_RESULTS = RUN_ROOT / "results"
PER_TEST_TIMEOUT_S = 60


def _as_runner_tree() -> None:
    """A read-only copy of the agent's tree and the hidden tests that `runner` can import."""
    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT)
    RUN_ROOT.mkdir(parents=True)
    shutil.copytree(env.TREE, RUN_TREE, symlinks=True)
    shutil.copytree(env.HIDDEN, RUN_TESTS)
    RUN_RESULTS.mkdir()
    env.run(["chmod", "-R", "a+rX,go-w", str(RUN_ROOT)], timeout=60)
    env.run(["chown", "runner:runner", str(RUN_RESULTS)], timeout=10)


def _kill_runner() -> None:
    env.run(["pkill", "-9", "-u", "runner"], timeout=10)


def _create_db(name: str, template: str | None = None) -> None:
    with env.connect() as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        if template:
            conn.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {} OWNER ledgerly_migrator").format(
                    sql.Identifier(name), sql.Identifier(template)
                )
            )
            return
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER ledgerly_migrator").format(sql.Identifier(name))
        )
    with env.connect(name) as conn:
        conn.execute("GRANT USAGE ON SCHEMA public TO ledgerly_app")
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE ON TABLES TO ledgerly_app"
        )
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE ledgerly_migrator IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO ledgerly_app"
        )


def migrate(db: str, timeout: float = 120) -> dict[str, Any]:
    """Apply the agent's Alembic migrations to `db`, as `runner`, with the migrator role."""
    if not RUN_TREE.exists():
        _as_runner_tree()
    migrator = env.dsn(db, "ledgerly_migrator")
    res = env.run(
        [env.VENV_PY, "-m", "alembic", "-x", f"dsn={migrator}", "upgrade", "head"],
        cwd=RUN_TREE,
        env=env.base_env(PYTHONPATH=str(RUN_TREE), LEDGERLY_MIGRATOR_DSN=migrator),
        timeout=timeout,
        user="runner",
    )
    _kill_runner()
    return {"ok": res.returncode == 0, "output": (res.stdout + res.stderr)[-3000:]}


def _duplicates_in_hidden_db() -> int:
    with env.connect(HIDDEN_DB) as conn:
        row = conn.execute(
            """
            SELECT count(*) AS n FROM (
                SELECT idempotency_key FROM charges WHERE idempotency_key LIKE 'hidem-%%'
                GROUP BY 1 HAVING count(*) > 1) d
            """
        ).fetchone()
    return int(row["n"]) if row else 0


def run_hidden() -> dict[str, Any]:
    _as_runner_tree()
    with env.connect() as conn:
        conn.execute(
            "GRANT pg_read_all_stats TO ledgerly_migrator"
        )  # lock/txn probes read pg_stat_activity
    _create_db(HIDDEN_TEMPLATE)
    migration = migrate(HIDDEN_TEMPLATE)
    results_path = RUN_RESULTS / f"hidden-{uuid.uuid4().hex}.jsonl"
    app = env.dsn(HIDDEN_DB, "ledgerly_app")
    test_env = env.base_env(
        PYTHONPATH=str(RUN_TREE),
        PYTHONSAFEPATH="1",
        LEDGERLY_TREE=str(RUN_TREE),
        LEDGERLY_APP_DSN=app,
        LEDGERLY_MIGRATOR_DSN=env.dsn(HIDDEN_DB, "ledgerly_migrator"),
        LEDGERLY_REDIS_URL=HIDDEN_REDIS,
        LEDGERLY_STREAM_NAME="charges.created.hidden",
        LEDGERLY_PROCESSOR_URL="http://127.0.0.1:9",
        HIDDEN_APP_DSN=app,
        HIDDEN_ADMIN_DSN=env.dsn(HIDDEN_DB, "ledgerly_migrator"),
        HIDDEN_RESULTS=str(results_path),
    )
    pytest = [
        env.VENV_PY,
        "-m",
        "pytest",
        "-c",
        str(RUN_TESTS / "pytest.ini"),
        "--rootdir",
        str(RUN_TESTS),
    ]
    _create_db(HIDDEN_DB, HIDDEN_TEMPLATE)
    collected = env.run(
        [*pytest, "--collect-only", "-q", "--no-header", str(RUN_TESTS / "tests")],
        cwd=RUN_TESTS,
        env=test_env,
        timeout=120,
        user="runner",
    )
    _kill_runner()
    nodes = [
        line.strip()
        for line in collected.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    tails: list[str] = []
    exit_codes: list[int] = []
    db_verdicts: dict[str, int] = {}
    for node in nodes:
        _create_db(HIDDEN_DB, HIDDEN_TEMPLATE)
        env.run(["redis-cli", "-u", HIDDEN_REDIS, "FLUSHDB"], timeout=20)
        res = env.run(
            [*pytest, node], cwd=RUN_TESTS, env=test_env, timeout=PER_TEST_TIMEOUT_S, user="runner"
        )
        _kill_runner()
        exit_codes.append(res.returncode)
        tails.append((res.stdout + res.stderr)[-400:])
        if "test_idempotency_hidden" in node:
            db_verdicts[node] = _duplicates_in_hidden_db()
    if not nodes:
        tails.append((collected.stdout + collected.stderr)[-3000:])

    records: list[dict[str, Any]] = []
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # One final record per test: its outcome, or failed if it started and never reported.
    final: dict[str, dict[str, Any]] = {}
    for r in records:
        if r.get("outcome") == "started":
            final.setdefault(
                r["test"], {**r, "outcome": "failed", "detail": "no result: deadline or timeout"}
            )
        else:
            final[r["test"]] = r
    for node, dups in db_verdicts.items():
        if dups:
            final[node] = {
                **final.get(node, {"test": node, "check": "hidden.idempotency_concurrent"}),
                "outcome": "failed",
                "detail": f"grader found {dups} duplicated keys in the database",
            }
    records = [
        final.get(n, {"test": n, "check": None, "outcome": "failed", "detail": "never ran"})
        for n in nodes
    ]
    scores: dict[str, float] = {}
    for check in HIDDEN_CHECKS:
        mine = [r for r in records if r.get("check") == check]
        scores[check] = sum(r["outcome"] == "passed" for r in mine) / len(mine) if mine else 0.0
    return {
        "checks": scores,
        "migration": migration,
        "tests": [{k: r.get(k) for k in ("test", "check", "outcome", "detail")} for r in records],
        "nodes": len(nodes),
        "pytest_exits": exit_codes,
        "pytest_tail": "\n".join(tails)[-3000:],
    }


def run_agent_suite() -> dict[str, Any]:
    """The repo's own tests (`make test`), as `runner`, against the staging test database."""
    workdir = RUN_ROOT / "agent_suite"
    if workdir.exists():
        shutil.rmtree(workdir)
    shutil.copytree(env.TREE, workdir, symlinks=True)
    env.run(["chown", "-R", "runner:runner", str(workdir)], timeout=60)
    junit = workdir / "junit.xml"
    res = env.run(
        [env.VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
        cwd=workdir,
        env=env.base_env(
            LEDGERLY_REDIS_URL="redis://redis:6379/4",
            LEDGERLY_STREAM_NAME="charges.created.agent-tests",
        ),
        timeout=180,
        user="runner",
    )
    _kill_runner()
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if junit.exists():
        try:
            root = ET.parse(junit).getroot()
            suites = [root] if root.tag == "testsuite" else list(root)
            for suite in suites:
                for key in counts:
                    counts[key] += int(suite.get(key, 0))
        except ET.ParseError:
            pass
    passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    ok = res.returncode == 0 and counts["tests"] > 0 and passed == counts["tests"]
    return {
        "checks": {"static.agent_tests_pass": 1.0 if ok else 0.0},
        "counts": counts,
        "exit": res.returncode,
        "tail": (res.stdout + res.stderr)[-2000:],
    }
