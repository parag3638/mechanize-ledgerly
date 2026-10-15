"""Step 1: freeze the stack, snapshot the agent's end state, copy the tree and the audit logs."""

import filecmp
import json
import os
import shutil
from pathlib import Path
from typing import Any

from grader import env

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".claude",
    ".codex",
    ".mypy_cache",
}
EXCLUDE_FILES = {"AGENTS.md", "CLAUDE.md"}


def freeze() -> dict[str, Any]:
    stopped = {}
    for svc in env.APP_SERVICES:
        try:
            stopped[svc] = env.supervisor(svc, "stop").get("running") is False
        except Exception as exc:  # noqa: BLE001
            stopped[svc] = f"error: {exc}"
    with env.connect() as conn:
        # No new sessions while the snapshot is taken; then drop everyone still connected.
        conn.execute("ALTER DATABASE ledgerly ALLOW_CONNECTIONS false")
        try:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                WHERE datname = 'ledgerly' AND pid <> pg_backend_pid()
                """
            )
            conn.execute("DROP DATABASE IF EXISTS ledgerly_agent_end WITH (FORCE)")
            # Owned by the superuser and closed to everyone else: nothing can change what we grade.
            conn.execute("CREATE DATABASE ledgerly_agent_end TEMPLATE ledgerly OWNER postgres")
            conn.execute("REVOKE CONNECT ON DATABASE ledgerly_agent_end FROM PUBLIC")
        finally:
            conn.execute("ALTER DATABASE ledgerly ALLOW_CONNECTIONS true")
    ledger = env.processor_admin("ledger")
    (env.WORK / "processor_ledger.json").write_text(json.dumps(ledger))
    return {"stopped": stopped, "processor_charges": len(ledger.get("charges", []))}


def binary_code() -> list[str]:
    """Code that static checks can't read: sourceless .pyc, extension modules, .pth files."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(env.REPO_MOUNT):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".venv")]
        for name in filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(env.REPO_MOUNT))
            if name.endswith((".so", ".pth", ".pyd")):
                found.append(rel)
            elif name.endswith(".pyc"):
                module = name.split(".")[0]
                parent = path.parent.parent if path.parent.name == "__pycache__" else path.parent
                if not (parent / f"{module}.py").exists():
                    found.append(rel)
    return sorted(found)


def copy_tree() -> None:
    if env.TREE.exists():
        shutil.rmtree(env.TREE)

    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in EXCLUDE_DIRS or n in EXCLUDE_FILES}

    shutil.copytree(env.REPO_MOUNT, env.TREE, ignore=ignore, symlinks=True)


def _files(root: Path) -> set[str]:
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if name in EXCLUDE_FILES:
                continue
            out.add(str((Path(dirpath) / name).relative_to(root)))
    return out


def diff_tree() -> dict[str, list[str]]:
    base, tree = _files(env.BASE_TREE), _files(env.TREE)
    changed = sorted(
        p for p in base & tree if not filecmp.cmp(env.BASE_TREE / p, env.TREE / p, shallow=False)
    )
    result = {"added": sorted(tree - base), "removed": sorted(base - tree), "changed": changed}
    patch = env.run(
        ["git", "diff", "--no-index", "--no-color", str(env.BASE_TREE), str(env.TREE)], timeout=60
    )
    (env.WORK / "patch.diff").write_text(patch.stdout)
    return result


def read_audit() -> dict[str, Any]:
    """Raw audit records: on-call, supervisors, Postgres statements."""
    audit: dict[str, Any] = {"oncall": [], "supervisor": [], "postgres": []}
    oncall = env.AUDIT / "oncall.jsonl"
    if oncall.exists():
        audit["oncall"] = [
            json.loads(line) for line in oncall.read_text().splitlines() if line.strip()
        ]
    for path in sorted(env.AUDIT.glob("supervisor-*.jsonl")):
        audit["supervisor"] += [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]
    for path in sorted((env.AUDIT / "postgres").glob("*.json")):
        for line in path.read_text(errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message", "")
            if rec.get("user") in ("ledgerly_migrator", "ledgerly_app") and (
                msg.startswith(("statement:", "execute "))
            ):
                audit["postgres"].append(
                    {
                        "ts": rec.get("timestamp"),
                        "user": rec.get("user"),
                        "db": rec.get("dbname"),
                        "sql": msg.split(":", 1)[1].strip() if ":" in msg else msg,
                    }
                )
    return audit
