"""Capture INC-2041 from the real, unfixed stack.

    python task/baseline/make_baseline.py            # ~15 minutes

1. Fresh stack without a baseline; seed 14 days of historical charges.
2. Replay the outage profile (2x traffic, 10 minutes) through the unfixed code
   while scraping metrics and Redis every 10 s.
3. "The on-call restarts the worker": Paystream's slow keys recover and the
   worker is restarted through its supervisor; the backlog drains.
4. Shift every timestamp onto the incident timeline (traffic starts at
   INCIDENT_START), then write:
   - task/baseline/ledgerly_baseline.sql.gz   handoff database (schema + data)
   - task/baseline/processor_ledger.json      Paystream's state at handoff
   - task/hidden/baseline_facts.json          ground truth for the grader
   - task/oncall/facts.json                   what on-call needs (dup count)
   - ledgerly/incident/INC-2041/...           logs, metrics, Redis samples
"""

import argparse
import gzip
import json
import random
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "task"
PROJECT = "ledgerly-baseline"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    PROJECT,
    "-f",
    str(TASK / "compose.yaml"),
    "-f",
    str(TASK / "compose.capture.yaml"),
]
INCIDENT_START = datetime(2026, 10, 14, 11, 21, 30, tzinfo=UTC)
OUTAGE_SEED = 9001
KEY_PREFIX = "ord-20261014"
PG_SUPER = ["psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "ledgerly", "-At"]
ADMIN_TOKEN = "grader-only-0b7d3a91c4"
SUPERVISOR_TOKEN = "grader-only-7c2e5d18f0"


def sh(args: list[str], *, input: str | None = None, check: bool = True) -> str:
    res = subprocess.run(args, input=input, capture_output=True, text=True, check=False)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:8])}... failed:\n{res.stderr[-2000:]}")
    return res.stdout


def dc(*args: str, input: str | None = None, check: bool = True) -> str:
    return sh([*COMPOSE, *args], input=input, check=check)


def dev(cmd: str, check: bool = True) -> str:
    return dc(
        "exec",
        "-T",
        "-u",
        "dev",
        "-w",
        "/workspace/ledgerly",
        "dev",
        "bash",
        "-c",
        cmd,
        check=check,
    )


def psql(sql: str) -> str:
    return dc("exec", "-T", "postgres", *PG_SUPER, input=sql)


def now() -> datetime:
    return datetime.now(UTC)


# --- history -----------------------------------------------------------------


def seed_history(n: int = 2400) -> None:
    rng = random.Random(20261001)
    start = INCIDENT_START - timedelta(days=14)
    rows: list[str] = []
    refunds: list[str] = []
    for i in range(n):
        created = start + timedelta(seconds=rng.uniform(0, 14 * 86400 - 3600))
        cid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        day = created.strftime("%Y%m%d")
        key = f"ord-{day}-{rng.randint(10000, 99999)}{i:04d}"
        customer = f"cust_{rng.randint(1, 60):03d}"
        amount = int(rng.lognormvariate(8.0, 0.9)) + 100
        roll = rng.random()
        status, ref, reason = (
            "succeeded",
            f"ch_{uuid.UUID(int=rng.getrandbits(128)).hex[:20]}",
            None,
        )
        if roll < 0.03:
            status, ref, reason = "failed", None, "declined"
        elif roll < 0.04:
            status = "refunded"
            rid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
            ts = (created + timedelta(days=1)).isoformat()
            refunds.append(
                f"('{rid}','{cid}',{amount},'customer request','succeeded',"
                f"'re_{rid.replace('-', '')[:20]}','{ts}','{ts}')"
            )
        updated = created + timedelta(seconds=rng.uniform(0.1, 0.4))
        ref_sql = f"'{ref}'" if ref else "NULL"
        reason_sql = f"'{reason}'" if reason else "NULL"
        rows.append(
            f"('{cid}','{key}','{customer}',{amount},'USD','{status}',{ref_sql},{reason_sql},"
            f"'{created.isoformat()}','{updated.isoformat()}')"
        )
    sql = "BEGIN;\n"
    for chunk in range(0, len(rows), 500):
        sql += (
            "INSERT INTO charges (id, idempotency_key, customer_id, amount_cents, currency, status,"
            " processor_ref, failure_reason, created_at, updated_at) VALUES\n"
            + ",\n".join(rows[chunk : chunk + 500])
            + ";\n"
        )
    if refunds:
        sql += (
            "INSERT INTO refunds (id, charge_id, amount_cents, reason, status, processor_ref,"
            " created_at, updated_at) VALUES\n" + ",\n".join(refunds) + ";\n"
        )
    sql += "COMMIT;\n"
    psql(sql)
    print(f"history: {len(rows)} charges, {len(refunds)} refunds")


# --- capture -----------------------------------------------------------------


class Scraper(threading.Thread):
    """Every 10 s: Prometheus text from api1, api2, worker; Redis memory and stream info."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.metrics: dict[str, list[tuple[datetime, str]]] = {"api1": [], "api2": [], "worker": []}
        self.redis: list[tuple[datetime, str]] = []

    def run(self) -> None:
        targets = {
            "api1": "http://api1:8000/metrics",
            "api2": "http://api2:8000/metrics",
            "worker": "http://worker:9101/metrics",
        }
        while not self.stop.is_set():
            at = now()
            for name, url in targets.items():
                text = dev(f"curl -s -m 5 {url}", check=False)
                if text:
                    self.metrics[name].append((at, text))
            info = dev(
                "redis-cli -h redis info memory | grep -E '^(used_memory|used_memory_human|"
                "used_memory_peak_human|used_memory_rss_human):'; "
                "redis-cli -h redis xlen charges.created; "
                "redis-cli -h redis xinfo groups charges.created | paste -sd' '",
                check=False,
            )
            self.redis.append((at, info))
            self.stop.wait(10.0)


def run_outage(duration: float, rate: float) -> None:
    profile = TASK / "baseline" / "outage_profile.json"
    sh(
        [
            sys.executable,
            str(TASK / "profiles" / "gen.py"),
            "--seed",
            str(OUTAGE_SEED),
            "--rate",
            str(rate),
            "--duration",
            str(duration),
            # The mobile SDK hedges more when latency is high.
            "--double-share",
            "0.2",
            "--out",
            str(profile),
        ]
    )
    dc("cp", str(profile), "dev:/tmp/outage_profile.json")
    out = dev(
        "python tools/replaylib.py --profile /tmp/outage_profile.json --base-url http://proxy:8080 "
        f'--dsn "$LEDGERLY_APP_DSN" --prefix {KEY_PREFIX} --drain 1 --quiet'
    )
    summary = json.loads(out)
    print(
        "outage replay:",
        {k: summary[k] for k in ("keys", "error_rate", "non_terminal", "dup_keys")},
    )


def recover_and_drain() -> None:
    dc(
        "exec",
        "-T",
        "dev",
        "curl",
        "-s",
        "-X",
        "POST",
        "-H",
        f"X-Admin-Token: {ADMIN_TOKEN}",
        "http://processor:8000/_admin/recover",
    )
    print("paystream recovered; restarting worker (the on-call's restart at 11:32)")
    dev("ledgerlyctl restart worker")
    # The worker reclaims unacknowledged entries only at start, and only those idle > 30 s.
    # Entries the old process read just before it died stay stuck until the next restart,
    # so if the drain stalls, restart once more, as the on-call would.
    deadline = time.monotonic() + 600
    last_left, stalled_since, restarts = -1, time.monotonic(), 1
    while time.monotonic() < deadline:
        left = int(
            psql("SELECT count(*) FROM charges WHERE status IN ('pending','processing');").strip()
        )
        if left == 0:
            return
        if left != last_left:
            last_left, stalled_since = left, time.monotonic()
        elif time.monotonic() - stalled_since > 45 and restarts < 3:
            print(f"  drain stalled at {left}; restarting the worker again")
            dev("ledgerlyctl restart worker")
            restarts += 1
            stalled_since = time.monotonic()
        print(f"  draining: {left} charges not terminal")
        time.sleep(10)
    raise RuntimeError("backlog did not drain")


# --- export ------------------------------------------------------------------


def shift_ts(value: str, offset: timedelta) -> str:
    ts = datetime.fromisoformat(value) + offset
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def export_logs(t0: datetime, offset: timedelta, dest: Path) -> None:
    for service_group, services in {"api": ["api1", "api2"], "worker": ["worker"]}.items():
        lines: list[tuple[str, str]] = []
        for svc in services:
            for raw in dc("logs", "--no-log-prefix", "--no-color", svc).splitlines():
                try:
                    rec: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "ts" not in rec:
                    continue
                if datetime.fromisoformat(rec["ts"]) < t0:
                    continue
                rec["ts"] = shift_ts(rec["ts"], offset)
                lines.append((rec["ts"], json.dumps(rec)))
        lines.sort()
        (dest / f"{service_group}.log.jsonl").write_text(
            "\n".join(line for _, line in lines) + "\n"
        )
        print(f"logs: {service_group}.log.jsonl {len(lines)} lines")


def export_metrics(scraper: Scraper, offset: timedelta, dest: Path) -> None:
    mdir = dest / "metrics"
    mdir.mkdir(exist_ok=True)
    for name, scrapes in scraper.metrics.items():
        with (mdir / f"{name}.prom").open("w") as fh:
            for at, text in scrapes:
                fh.write(f"# scrape {shift_ts(at.isoformat(), offset)}\n{text.rstrip()}\n\n")
    with (dest / "redis-info.txt").open("w") as fh:
        fh.write("# redis-cli info memory / xlen / xinfo groups, sampled every 10 s\n\n")
        for at, text in scraper.redis:
            fh.write(f"# sample {shift_ts(at.isoformat(), offset)}\n{text.rstrip()}\n\n")


def shift_db(t0: datetime, offset: timedelta) -> None:
    secs = offset.total_seconds()
    psql(
        f"""
        BEGIN;
        UPDATE charges SET created_at = created_at + interval '{secs} seconds',
                           updated_at = updated_at + interval '{secs} seconds'
        WHERE created_at >= '{t0.isoformat()}';
        UPDATE refunds SET created_at = created_at + interval '{secs} seconds',
                           updated_at = updated_at + interval '{secs} seconds'
        WHERE created_at >= '{t0.isoformat()}';
        UPDATE customers SET in_flight_cents = 0;
        COMMIT;
        """
    )


def facts() -> dict[str, Any]:
    rows = psql(
        """
        SELECT idempotency_key, id, status, created_at, amount_cents, customer_id FROM charges
        WHERE idempotency_key IN (
            SELECT idempotency_key FROM charges GROUP BY 1 HAVING count(*) > 1)
        ORDER BY idempotency_key, created_at, id;
        """
    ).splitlines()
    by_key: dict[str, list[tuple[str, str]]] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for line in rows:
        key, cid, status, _created, amount, customer = line.split("|")
        by_key.setdefault(key, []).append((cid, status))
        groups.setdefault(key, []).append(
            {"id": cid, "amount_cents": int(amount), "customer_id": customer}
        )
    canonical = [ids[0][0] for ids in by_key.values()]
    dups = [cid for ids in by_key.values() for cid, _ in ids[1:]]
    all_ids = psql("SELECT id FROM charges ORDER BY id;").split()
    counts = dict(
        line.split("|")
        for line in psql("SELECT status, count(*) FROM charges GROUP BY 1;").splitlines()
    )
    window = psql(
        f"SELECT count(*) FROM charges WHERE idempotency_key LIKE '{KEY_PREFIX}-%';"
    ).strip()
    return {
        "dup_keys": len(by_key),
        "dup_rows": len(dups),
        "dup_charge_ids": sorted(dups),
        "dup_groups": groups,
        "canonical_ids": sorted(canonical),
        "charge_ids_all": all_ids,
        "charges_by_status": {k: int(v) for k, v in counts.items()},
        "incident_charges": int(window),
        "incident_window_utc": [INCIDENT_START.isoformat(), None],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--rate", type=float, default=15)
    args = parser.parse_args()

    dc("down", "-v", "--remove-orphans", check=False)
    dc("up", "-d", "--build", "--wait", "--wait-timeout", "300")
    seed_history()

    scraper = Scraper()
    t0 = now()
    scraper.start()
    run_outage(args.duration, args.rate)
    traffic_end = now()
    time.sleep(30)
    restart_at = now()
    recover_and_drain()
    time.sleep(20)
    scraper.stop.set()
    scraper.join(timeout=30)

    offset = INCIDENT_START - t0
    print(
        f"t0={t0.isoformat()} traffic_end={(traffic_end + offset).isoformat()} "
        f"restart={(restart_at + offset).isoformat()}"
    )

    incident = ROOT / "ledgerly" / "incident" / "INC-2041"
    incident.mkdir(parents=True, exist_ok=True)
    export_logs(t0, offset, incident)
    export_metrics(scraper, offset, incident)
    shift_db(t0, offset)

    f = facts()
    f["incident_window_utc"] = [INCIDENT_START.isoformat(), (traffic_end + offset).isoformat()]
    f["worker_restart_utc"] = (restart_at + offset).isoformat()
    print(
        f"facts: dup_keys={f['dup_keys']} dup_rows={f['dup_rows']} by_status={f['charges_by_status']}"
    )

    dump = dc(
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        "ledgerly",
        "--no-owner",
        "--no-privileges",
    )
    with gzip.open(TASK / "baseline" / "ledgerly_baseline.sql.gz", "wt") as fh:
        fh.write(dump)
    ledger = dc(
        "exec",
        "-T",
        "dev",
        "curl",
        "-s",
        "-H",
        f"X-Admin-Token: {ADMIN_TOKEN}",
        "http://processor:8000/_admin/ledger",
    )
    (TASK / "baseline" / "processor_ledger.json").write_text(ledger)

    hidden = TASK / "hidden"
    hidden.mkdir(exist_ok=True)
    (hidden / "baseline_facts.json").write_text(json.dumps(f, indent=1) + "\n")
    (TASK / "oncall" / "facts.json").write_text(
        json.dumps({"dup_rows": f["dup_rows"], "dup_keys": f["dup_keys"]}, indent=1) + "\n"
    )
    print("baseline written")
    dc("down", "-v", "--remove-orphans", check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
