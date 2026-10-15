"""QA_REPORT.md and a single-file HTML summary."""

import argparse
import html
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Template

DESCRIPTIONS = {
    "knowability": "Every grader check declares where the agent can learn it; every quoted source exists verbatim.",
    "determinism": "The same submission graded N times gets identical procedural scores.",
    "sanity": "Unmodified repo near zero; partial fixes land in their bands; partial credit is monotonic.",
    "hacks": "Every reward-hack probe scores below 0.3.",
    "fairness": "Two different valid fixes both score at least 0.9.",
    "interpretation": "Reasonable alternative readings of the prompt keep their credit.",
    "rubric": "The LLM postmortem rubric is stable across repeated runs.",
}


def _cell(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "**no**"
    if isinstance(v, float):
        return f"{v:.3f}"
    text = str(v).replace("|", "\\|").replace("\n", " ")
    return text[:160]


def write_markdown(results: list[Any], path: Path, args: argparse.Namespace) -> None:
    lines = [
        "# QA report — Ledgerly incident grader",
        "",
        (
            f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `python -m taskqa run` "
            f"(replay runs per profile: {args.replay_runs}, determinism N={args.n}, rubric K={args.k})."
        ),
        "",
        "| Check | Result | Summary |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {'PASS' if r.passed else '**FAIL**'} | {_cell(r.summary)} |")
    for r in results:
        lines += [
            "",
            f"## {r.name} — {'PASS' if r.passed else 'FAIL'}",
            "",
            DESCRIPTIONS.get(r.name, ""),
            "",
        ]
        if r.rows:
            cols = list(r.rows[0].keys())
            lines.append("| " + " | ".join(cols) + " |")
            lines.append("|" + "---|" * len(cols))
            for row in r.rows:
                lines.append("| " + " | ".join(_cell(row.get(c, "")) for c in cols) + " |")
    lines += ["", "Raw results: `qa/results.json`; per-grading Inspect logs: `runs/logs/qa/`.", ""]
    path.write_text("\n".join(lines))


_HTML = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grader QA</title>
<style>
:root { --bg:#fbfbf8; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --ok:#1f7a4d; --bad:#b3261e; --bar:#3a6ea5; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#141413; --fg:#ecebe6; --muted:#9a9993; --line:#2c2c2a; --ok:#5fc08e; --bad:#ef7a70; --bar:#7aa7d6; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; margin:0 auto; max-width:1000px; padding:24px 16px; }
h1 { font-size:1.5rem; margin:0 0 4px } .muted { color:var(--muted) }
table { border-collapse:collapse; width:100%; margin:8px 0 24px; font-size:13px; }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
.pass { color:var(--ok); font-weight:600 } .fail { color:var(--bad); font-weight:600 }
.bar { height:8px; background:var(--bar); border-radius:4px; }
.wrap { overflow-x:auto }
</style></head><body>
<h1>Grader QA — Ledgerly incident</h1>
<p class="muted">Generated {{ when }}. {{ passed }}/{{ total }} checks pass.</p>
<div class="wrap"><table><tr><th>Check</th><th>Result</th><th>Summary</th></tr>
{% for r in results %}<tr><td><a href="#{{ r.name }}">{{ r.name }}</a></td><td class="{{ 'pass' if r.passed else 'fail' }}">{{ 'PASS' if r.passed else 'FAIL' }}</td><td>{{ r.summary }}</td></tr>{% endfor %}
</table></div>
{% for r in results %}
<h2 id="{{ r.name }}">{{ r.name }} <span class="{{ 'pass' if r.passed else 'fail' }}">{{ 'PASS' if r.passed else 'FAIL' }}</span></h2>
<p class="muted">{{ desc[r.name] }}</p>
{% if r.rows %}<div class="wrap"><table><tr>{% for c in r.rows[0].keys() %}<th>{{ c }}</th>{% endfor %}{% if 'score' in r.rows[0] %}<th></th>{% endif %}</tr>
{% for row in r.rows %}<tr>{% for c in r.rows[0].keys() %}<td>{{ fmt(row.get(c, '')) }}</td>{% endfor %}
{% if 'score' in r.rows[0] %}<td style="width:140px">{% if row.score is number %}<div class="bar" style="width:{{ (row.score * 100)|round(0) }}%"></div>{% endif %}</td>{% endif %}</tr>{% endfor %}
</table></div>{% endif %}
{% endfor %}
</body></html>"""
)


def write_html(results: list[Any], path: Path) -> None:
    def fmt(v: Any) -> str:
        if isinstance(v, bool):
            return "yes" if v else "NO"
        if isinstance(v, float):
            return f"{v:.3f}"
        return html.unescape(str(v))[:200]

    path.write_text(
        _HTML.render(
            results=results,
            when=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            passed=sum(r.passed for r in results),
            total=len(results),
            desc=DESCRIPTIONS,
            fmt=fmt,
        )
    )
