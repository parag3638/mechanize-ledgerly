"""Process supervisor with an audited HTTP control API.

Runs one service's process as a child, restarts it if it exits, and exposes
`GET /status`, `POST /restart|/stop|/start` on :9900 so the agent (through
`ledgerlyctl`) and the grader can control services without a Docker socket.

Every control action and every automatic restart is appended to
/var/log/audit/supervisor-<service>.jsonl. A request carrying the grader's
token (`SUPERVISOR_TOKEN`) is recorded as actor "grader"; anything else is "dev".

Standard library only, so it runs in every image (python3 is all it needs).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", "/var/log/audit"))
PORT = 9900
STOP_GRACE_S = 10.0


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Supervisor:
    def __init__(
        self, service: str, cmd: list[str], user: str | None, stop_signal: int, token: str
    ) -> None:
        self.service = service
        self.cmd = cmd
        self.user = user
        self.stop_signal = stop_signal
        self.token = token
        self.proc: subprocess.Popen[bytes] | None = None
        self.started_at: str | None = None
        self.restarts = 0
        self.want_running = True
        self.lock = threading.RLock()
        self.audit_path = AUDIT_DIR / f"supervisor-{service}.jsonl"

    def audit(self, action: str, actor: str, **extra: Any) -> None:
        record = {"ts": now(), "service": self.service, "action": action, "actor": actor, **extra}
        try:
            AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
            os.chmod(self.audit_path, 0o644)
        except OSError as exc:
            print(f"supervisor: cannot write audit log: {exc}", file=sys.stderr, flush=True)

    def start(self) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            # The services never see the grader's token (it would let agent code act as the grader).
            child_env = {k: v for k, v in os.environ.items() if k != "SUPERVISOR_TOKEN"}
            self.proc = subprocess.Popen(
                self.cmd, user=self.user, start_new_session=True, env=child_env
            )
            self.started_at = now()
            self.want_running = True

    def stop(self) -> None:
        with self.lock:
            self.want_running = False
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return
            try:
                os.killpg(proc.pid, self.stop_signal)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()

    def restart(self) -> None:
        with self.lock:
            self.stop()
            self.restarts += 1
            self.start()

    def status(self) -> dict[str, Any]:
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            return {
                "service": self.service,
                "running": running,
                "pid": self.proc.pid if running and self.proc else None,
                "started_at": self.started_at,
                "restarts": self.restarts,
            }

    def watch(self) -> None:
        """Bring the process back if it exits while it should be running."""
        while True:
            time.sleep(1.0)
            with self.lock:
                proc = self.proc
                if self.want_running and proc is not None and proc.poll() is not None:
                    code = proc.returncode
                    self.audit("auto_restart", "supervisor", exit_code=code)
                    self.restarts += 1
                    self.start()


def make_handler(sup: Supervisor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _actor(self) -> str:
            token = self.headers.get("X-Audit-Token", "")
            return "grader" if sup.token and token == sup.token else "dev"

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/status":
                self._send(200, sup.status())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            action = self.path.strip("/")
            handlers = {"restart": sup.restart, "stop": sup.stop, "start": sup.start}
            if action not in handlers:
                self._send(404, {"error": "unknown action; use restart, stop or start"})
                return
            actor = self._actor()
            sup.audit(action, actor, requested_by=self.headers.get("X-Requested-By", ""))
            handlers[action]()
            self._send(200, {"action": action, **sup.status()})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--user", default=None, help="run the child as this user")
    parser.add_argument("--stop-signal", default="SIGTERM")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        parser.error("missing command")

    sup = Supervisor(
        args.service,
        cmd,
        args.user,
        getattr(signal, args.stop_signal),
        os.environ.get("SUPERVISOR_TOKEN", ""),
    )

    def shutdown(_signum: int, _frame: object) -> None:
        sup.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    sup.start()
    sup.audit("boot", "supervisor")
    threading.Thread(target=sup.watch, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(sup))
    server.serve_forever()


if __name__ == "__main__":
    main()
