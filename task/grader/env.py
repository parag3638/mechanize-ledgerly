"""Grader-side connections and controls. Runs inside the `grader` service only."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

SUPER_HOST = "postgres"
SUPER_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
PROCESSOR_TOKEN = os.environ.get("PROCESSOR_ADMIN_TOKEN", "")
PROCESSOR_SEED = os.environ.get("PROCESSOR_SEED", "paystream-2026")
PROCESSOR_URL = "http://processor:8000"
PUBLIC_URL = "http://proxy:8080"

GRADER = Path("/grader")
BASE_TREE = GRADER / "base_tree"
HIDDEN = GRADER / "hidden"
WORK = GRADER / "work"
TREE = WORK / "tree"
AUDIT = Path("/var/log/audit")
REPO_MOUNT = Path("/mnt/repo")
VENV_PY = "/opt/venv/bin/python"

APP_SERVICES = ("api1", "api2", "worker")


def dsn(db: str, user: str = "postgres") -> str:
    if user == "postgres":
        return f"postgresql://postgres:{SUPER_PASSWORD}@{SUPER_HOST}:5432/{db}"
    return f"postgresql://{user}:{user}@{SUPER_HOST}:5432/{db}"


def connect(db: str = "postgres") -> psycopg.Connection[dict[str, Any]]:
    return psycopg.Connection.connect(  # pyright: ignore[reportReturnType]
        dsn(db),
        autocommit=True,
        row_factory=dict_row,  # pyright: ignore[reportArgumentType]
        connect_timeout=10,
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" UTC", "+00:00"))


def http(method: str, url: str, headers: dict[str, str] | None = None, timeout: float = 30) -> Any:
    req = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def supervisor(service: str, action: str) -> dict[str, Any]:
    return http(
        "POST" if action != "status" else "GET",
        f"http://{service}:9900/{action}",
        {"X-Audit-Token": SUPERVISOR_TOKEN, "X-Requested-By": "grader"},
    )


def processor_admin(action: str) -> Any:
    method = "GET" if action == "ledger" else "POST"
    return http(method, f"{PROCESSOR_URL}/_admin/{action}", {"X-Admin-Token": PROCESSOR_TOKEN})


def wait_healthy(timeout_s: float = 45) -> bool:
    urls = [
        "http://api1:8000/healthz",
        "http://api2:8000/healthz",
        "http://worker:9101/metrics",
        f"{PUBLIC_URL}/healthz",
    ]
    deadline = time.monotonic() + timeout_s
    pending = list(urls)
    while pending and time.monotonic() < deadline:
        for url in list(pending):
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        pending.remove(url)
            except (urllib.error.URLError, OSError):
                pass
        if pending:
            time.sleep(0.5)
    return not pending


def run(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
    user: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
            user=user,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timeout after {timeout}s")


def base_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": "/opt/venv/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(extra)
    return env
