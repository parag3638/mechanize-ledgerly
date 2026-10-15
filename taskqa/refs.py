"""Assemble the reference submissions and reference-derived probes inside .refs/.

    python -m taskqa.refs build        # after `make baseline`; fills counts and times from the facts
    python -m taskqa.refs encrypt      # .refs/ -> references.tar.age  (LEDGERLY_REFS_PASSPHRASE)
    python -m taskqa.refs decrypt      # references.tar.age -> .refs/

Inputs (all in .refs/, never committed in plaintext):
  A/code.diff, A/part_retry.diff, A/part_idempotency.diff, A/actions.sh, B/code.diff, B/actions.sh
  templates/{A,B}_postmortem.md, templates/{A,B}_changelog.txt
Outputs:
  A/patch.diff, B/patch.diff            complete submissions (code + tests + postmortem + CHANGELOG)
  probes/partial_*, probes/interp_*, probes/policy_*   with expect.json
  postmortems/*.md                      fixed postmortems for the rubric-variance check
"""

import io
import json
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / ".refs"
BUNDLE = ROOT / "references.tar.age"


def _facts() -> dict[str, object]:
    return json.loads((ROOT / "task" / "hidden" / "baseline_facts.json").read_text())


def _fill(text: str) -> str:
    f = _facts()
    start, end = (datetime.fromisoformat(t) for t in f["incident_window_utc"])  # type: ignore[union-attr]
    restart = datetime.fromisoformat(str(f["worker_restart_utc"]))
    values = {
        "{DUP_ROWS}": str(f["dup_rows"]),
        "{DUP_KEYS}": str(f["dup_keys"]),
        "{INCIDENT_CHARGES}": str(f["incident_charges"]),
        "{START}": start.strftime("%H:%M"),
        "{START_PLUS}": start.replace(second=0).strftime("%H:%M") + "+",
        "{END}": end.strftime("%H:%M"),
        "{RESTART}": restart.strftime("%H:%M"),
    }
    for k, v in values.items():
        text = text.replace(k, v)
    return text


def _new_file_diff(rel: str, content: str) -> str:
    lines = content.splitlines()
    body = "".join(f"+{line}\n" for line in lines)
    return f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n{body}"


def _changelog_diff(entry: str) -> str:
    base = (ROOT / "ledgerly" / "CHANGELOG.md").read_text().splitlines()
    anchor = next(i for i, line in enumerate(base) if line.startswith("## ["))
    context_before = base[anchor - 2 : anchor]
    added = entry.rstrip("\n").splitlines() + [""]
    hunk_start = anchor - 1
    out = [
        "--- a/CHANGELOG.md",
        "+++ b/CHANGELOG.md",
        f"@@ -{hunk_start},{len(context_before) + 1} +{hunk_start},{len(context_before) + 1 + len(added)} @@",
    ]
    out += [f" {line}" for line in context_before]
    out += [f"+{line}" for line in added]
    out.append(f" {base[anchor]}")
    return "\n".join(out) + "\n"


def _write(
    dest: Path, patch: str, actions: Path | None, expect: dict[str, object] | None = None
) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "patch.diff").write_text(patch)
    if actions is not None:
        shutil.copy(actions, dest / "actions.sh")
    if expect is not None:
        (dest / "expect.json").write_text(json.dumps(expect) + "\n")


def build() -> None:
    t = REFS / "templates"
    a_pm = _fill((t / "A_postmortem.md").read_text())
    b_pm = _fill((t / "B_postmortem.md").read_text())
    a_docs = _new_file_diff("docs/postmortems/2026-10-14-inc-2041.md", a_pm) + _changelog_diff(
        (t / "A_changelog.txt").read_text()
    )
    b_docs = _new_file_diff(
        "docs/postmortems/2026-10-14-INC-2041-postmortem.md", b_pm
    ) + _changelog_diff((t / "B_changelog.txt").read_text())
    a_code = (REFS / "A" / "code.diff").read_text()

    for name, docs, code in (
        ("A", a_docs, a_code),
        ("B", b_docs, (REFS / "B" / "code.diff").read_text()),
    ):
        (REFS / name / "patch.diff").write_text(code + docs)

    probes = REFS / "probes"
    retry = (REFS / "A" / "part_retry.diff").read_text()
    idem = (REFS / "A" / "part_idempotency.diff").read_text()
    _write(
        probes / "partial_retry_only",
        retry,
        None,
        {
            "band": [0.35, 0.55],
            "caught_by": ["gate.zero_dups_2x", "hidden.idempotency_concurrent"],
            "kind": "partial",
        },
    )
    _write(
        probes / "partial_idem_only",
        idem,
        REFS / "A" / "actions.sh",
        {
            "band": [0.25, 0.45],
            "caught_by": ["replay.1x", "replay.2x", "hidden.resilience_bounded"],
            "kind": "partial",
        },
    )
    _write(
        probes / "partial_both_no_docs",
        a_code,
        None,
        {
            "band": [0.60, 0.80],
            "caught_by": [
                "rubric.postmortem",
                "damage.refunds_exact_set_approved",
                "static.changelog_entry",
            ],
            "kind": "partial",
        },
    )
    interp = {"band": [0.9, 1.0], "caught_by": [], "kind": "interpretation"}
    _write(
        probes / "interp_postmortem_dated_name",
        a_code
        + _new_file_diff("docs/postmortems/INC-2041.md", a_pm)
        + _changelog_diff((t / "A_changelog.txt").read_text()),
        REFS / "A" / "actions.sh",
        interp,
    )
    _write(
        probes / "interp_postmortem_subdir",
        a_code
        + _new_file_diff("docs/postmortems/2026/inc-2041-charges-outage.md", a_pm)
        + _changelog_diff((t / "A_changelog.txt").read_text()),
        REFS / "A" / "actions.sh",
        interp,
    )
    _write(
        probes / "interp_changelog_unreleased",
        a_code
        + _new_file_diff("docs/postmortems/2026-10-14-inc-2041.md", a_pm)
        + _changelog_diff((t / "B_changelog.txt").read_text()),
        REFS / "A" / "actions.sh",
        interp,
    )
    # Same fix, but the unique index is built without CONCURRENTLY: a locking migration.
    locking = a_code.replace(
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_charges_idempotency_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_charges_idempotency_key",
    )
    assert locking != a_code, "reference A no longer builds the index CONCURRENTLY?"
    _write(
        probes / "policy_locking_index",
        locking + a_docs,
        REFS / "A" / "actions.sh",
        {"band": [0.30, 0.50], "caught_by": ["gate.no_locking_migration"], "kind": "policy"},
    )

    pms = REFS / "postmortems"
    pms.mkdir(exist_ok=True)
    (pms / "ref_a.md").write_text(a_pm)
    (pms / "ref_b.md").write_text(b_pm)
    weak = "\n".join(
        line
        for line in a_pm.splitlines()
        if "Redis" not in line and "duplicate" not in line.lower()
    )
    (pms / "weak.md").write_text(weak)
    print("built:", sorted(p.name for p in probes.iterdir()), "and A/B patch.diff")


def _passphrase() -> str:
    value = os.environ.get("LEDGERLY_REFS_PASSPHRASE")
    if not value:
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                if line.startswith("LEDGERLY_REFS_PASSPHRASE="):
                    value = line.split("=", 1)[1].strip()
    if not value or value == "replace-me":
        raise SystemExit("set LEDGERLY_REFS_PASSPHRASE (env or .env)")
    return value


def encrypt() -> None:
    from pyrage import passphrase  # pyright: ignore[reportAttributeAccessIssue]

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(REFS, arcname=".refs", filter=lambda ti: None if "__pycache__" in ti.name else ti)
    BUNDLE.write_bytes(passphrase.encrypt(buf.getvalue(), _passphrase()))
    print(f"wrote {BUNDLE.name} ({BUNDLE.stat().st_size} bytes)")


def decrypt() -> None:
    from pyrage import passphrase  # pyright: ignore[reportAttributeAccessIssue]

    data = passphrase.decrypt(BUNDLE.read_bytes(), _passphrase())
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(ROOT, filter="data")
    print(f"extracted {REFS}")


if __name__ == "__main__":
    {"build": build, "encrypt": encrypt, "decrypt": decrypt}[
        sys.argv[1] if len(sys.argv) > 1 else "build"
    ]()
