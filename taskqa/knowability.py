"""taskqa check 5: every grader check declares a source, and every quoted source exists.

A quote must appear verbatim (whitespace-normalised) in its file. ONCALL:<intent>
sources must also be paired with a PROMPT source that tells the agent to consult
on-call, since those facts are revealed only when asked. Diagnostics are unscored
and need no source.

The other direction is audited too: knowable must not mean told. The agent's repo
may state goals and policy, but no sentence may name a planted mechanism
(HINT_PATTERNS); v1 lost most of its difficulty to two such sentences.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Phrases that would name a planted bug or its fix in the agent-visible repo.
HINT_PATTERNS: dict[str, str] = {
    "transaction across a network call": r"(across|spans?) (a|the) network call|transaction open across",
    "idempotency enforced by the database": r"database guarantee|process-local",
    "lock expiry": r"ttl is (too )?short|lock (can|may|will|might) expire|expires? before (the )?commit",
    "lock ownership": r"another (request|replica)'?s? lock|owner(ship)? check",
}
HINT_SUFFIXES = (".md", ".py", ".ini", ".toml")


@dataclass(frozen=True)
class Finding:
    check: str
    source: str
    quote: str
    ok: bool
    reason: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _text_for(path: str) -> str | None:
    if path == "PROMPT":
        return (ROOT / "task" / "prompt.md").read_text()
    if path.startswith("ONCALL:"):
        intents = json.loads((ROOT / "task" / "oncall" / "intents.json").read_text())
        spec = intents.get(path.split(":", 1)[1])
        if spec is None:
            return None
        return " ".join(v for k, v in spec.items() if k.startswith("answer"))
    file = ROOT / "ledgerly" / path
    return file.read_text() if file.exists() else None


def audit() -> list[Finding]:
    import sys

    sys.path.insert(0, str(ROOT / "task"))
    from grader.checks import CHECKS

    findings: list[Finding] = []
    for check in CHECKS:
        if check.kind == "diagnostic":
            findings.append(Finding(check.id, "-", "-", True, "unscored diagnostic"))
            continue
        if not check.sources:
            findings.append(Finding(check.id, "-", "-", False, "no source declared"))
            continue
        has_consult = any(s.path == "PROMPT" and "oncall ask" in s.quote for s in check.sources)
        for src in check.sources:
            text = _text_for(src.path)
            if text is None:
                findings.append(
                    Finding(check.id, src.path, src.quote, False, "source file not found")
                )
                continue
            if _norm(src.quote) not in _norm(text):
                findings.append(Finding(check.id, src.path, src.quote, False, "quote not found"))
                continue
            if src.path.startswith("ONCALL:") and not has_consult:
                findings.append(
                    Finding(
                        check.id,
                        src.path,
                        src.quote,
                        False,
                        "on-call source without a PROMPT consult source",
                    )
                )
                continue
            findings.append(Finding(check.id, src.path, src.quote, True, ""))
    return findings + hint_audit()


def hint_audit() -> list[Finding]:
    """No agent-visible file names a planted mechanism (incident evidence is exempt)."""
    repo = ROOT / "ledgerly"
    findings: list[Finding] = []
    for file in sorted(repo.rglob("*")):
        rel = file.relative_to(repo)
        if (
            not file.is_file()
            or file.suffix not in HINT_SUFFIXES
            or rel.parts[0]
            in (
                "incident",
                ".venv",
            )
        ):
            continue
        text = file.read_text(errors="ignore").lower()
        for name, pattern in HINT_PATTERNS.items():
            m = re.search(pattern, text)
            if m:
                findings.append(
                    Finding("hint_audit", str(rel), m.group(0), False, f"names a mechanism: {name}")
                )
    if not findings:
        findings.append(Finding("hint_audit", "ledgerly/", "-", True, "no mechanism named"))
    return findings


if __name__ == "__main__":
    results = audit()
    for f in results:
        mark = "ok  " if f.ok else "FAIL"
        print(f"{mark} {f.check:38s} {f.source:32s} {f.reason or f.quote[:60]}")
    failed = [f for f in results if not f.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} sources verified")
    raise SystemExit(1 if failed else 0)
