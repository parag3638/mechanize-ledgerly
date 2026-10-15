"""taskqa check 5: every grader check declares a source, and every quoted source exists.

A quote must appear verbatim (whitespace-normalised) in its file. ONCALL:<intent>
sources must also be paired with a PROMPT source that tells the agent to consult
on-call, since those facts are revealed only when asked.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    return findings


if __name__ == "__main__":
    results = audit()
    for f in results:
        mark = "ok  " if f.ok else "FAIL"
        print(f"{mark} {f.check:38s} {f.source:32s} {f.reason or f.quote[:60]}")
    failed = [f for f in results if not f.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} sources verified")
    raise SystemExit(1 if failed else 0)
