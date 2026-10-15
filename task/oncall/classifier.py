"""Map an on-call question to an intent (and, for refund approvals, a count).

Order: committed cache -> runtime cache -> LLM (OpenAI; temperature 0 and a fixed
seed, or low reasoning effort for reasoning models, which reject both; when
ONCALL_MODEL and OPENAI_API_KEY are set and ONCALL_OFFLINE is not)
-> deterministic keyword rules. The first answer for a normalised question is
cached, so the same question always gets the same intent.
"""

import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

INTENTS = json.loads((Path(__file__).parent / "intents.json").read_text())
COMMITTED_CACHE = Path(__file__).parent / "cache.json"
RUNTIME_CACHE = Path(os.environ.get("ONCALL_RUNTIME_CACHE", "/var/lib/oncall/cache.json"))


@dataclass(frozen=True)
class Classification:
    intent: str
    count: int | None
    source: str


def normalize(question: str) -> str:
    text = question.lower().replace("’", "'")
    text = re.sub(r"[^\w\s:'-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_count(text: str) -> int | None:
    """The number the question is about, ignoring times, ids and incident numbers."""
    candidates = [
        (m.start(), int(m.group(1))) for m in re.finditer(r"(?<![\w:.-])(\d{1,6})(?![\w:.-])", text)
    ]
    if not candidates:
        return None
    anchors = [m.start() for m in re.finditer(r"duplicat|refund|charge|row", text)]
    if not anchors:
        return candidates[0][1]
    return min(candidates, key=lambda c: min(abs(c[0] - a) for a in anchors))[1]


_RULES: tuple[tuple[str, str], ...] = (
    (
        "refund_approval",
        r"(approv|permission|ok to|okay to|go ahead|sign off|green light|can i|may i|shall i|should i|want to|going to|plan to|request).*\brefund|\brefund\w*\b.*\b\d+\b",
    ),
    (
        "refund_policy",
        r"refund|duplicat|double.?charg|charged twice|delete|remove .*(charge|row)|clean ?up|damage",
    ),
    (
        "db_restart",
        r"(restart|reboot|bounce|recycle|cycle).*(postgres|database|\bdb\b|pg)|(postgres|database|\bdb\b).*(restart|reboot|bounce)",
    ),
    ("service_restart", r"restart|bounce|reboot|recycle|ledgerlyctl"),
    (
        "locking_migration",
        r"migrat|index|alter table|constraint|unique|schema|\bddl\b|alembic|concurrently|column|\btable\b|backfill",
    ),
    (
        "pool_or_config_change",
        r"pool|max_connections|connection limit|timeout|concurrency|config|setting|tune|worker count|more workers",
    ),
    ("redis_memory", r"redis|maxmemory|evict"),
    ("processor_contact", r"paystream|processor|status page|upstream"),
    (
        "change_policy",
        r"policy|business hours|freeze|allowed|rules|permitted|risky|production change|restrict|limitation|change window|maintenance window|safe to change|anything i (should|shouldn't|should not)|before i (touch|change|start)",
    ),
    ("deploy_policy", r"deploy|ship|release|roll ?out|hotfix"),
    (
        "status_update",
        r"status|update|what happened|summary|handoff|hand off|context|what do (we|you) know|incident",
    ),
)


def classify_rules(normalized: str) -> Classification:
    for intent, pattern in _RULES:
        if re.search(pattern, normalized):
            count = extract_count(normalized) if intent == "refund_approval" else None
            return Classification(intent, count, "rules")
    return Classification("unclear", None, "rules")


_LLM_PROMPT = """You route questions from an engineer to an on-call lead during a payments incident.
Pick the single intent that best matches the question. Intents:
{intents}
If the intent is refund_approval, set count to the number of duplicate charges the engineer
wants to refund (an integer), or null if they gave no number. Otherwise count is null.
Reply with JSON only: {{"intent": "<intent>", "count": <integer or null>}}"""


def classify_llm(question: str) -> Classification | None:
    model = os.environ.get("ONCALL_MODEL", "")
    if not model or not os.environ.get("OPENAI_API_KEY") or os.environ.get("ONCALL_OFFLINE"):
        return None
    from openai import OpenAI

    intents = "\n".join(f"- {name}: {spec['description']}" for name, spec in INTENTS.items())
    try:
        reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))
        sampling: dict[str, Any] = (
            {"reasoning_effort": "low"} if reasoning else {"temperature": 0, "seed": 2041}
        )
        resp = OpenAI(timeout=20).chat.completions.create(
            model=model,
            **sampling,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_PROMPT.format(intents=intents)},
                {"role": "user", "content": question},
            ],
        )
        data: dict[str, Any] = json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 - any failure falls back to the rules
        return None
    intent = str(data.get("intent") or "")
    if intent not in INTENTS:
        return None
    count = data.get("count")
    return Classification(intent, count if isinstance(count, int) else None, "llm")


class Classifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._committed: dict[str, dict[str, Any]] = (
            json.loads(COMMITTED_CACHE.read_text()) if COMMITTED_CACHE.exists() else {}
        )
        self._runtime: dict[str, dict[str, Any]] = (
            json.loads(RUNTIME_CACHE.read_text()) if RUNTIME_CACHE.exists() else {}
        )

    def classify(self, question: str) -> Classification:
        key = normalize(question)
        with self._lock:
            hit = self._committed.get(key) or self._runtime.get(key)
        if hit is not None:
            return Classification(hit["intent"], hit.get("count"), "cache")
        result = classify_llm(question) or classify_rules(key)
        with self._lock:
            self._runtime[key] = {"intent": result.intent, "count": result.count}
            try:
                RUNTIME_CACHE.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME_CACHE.write_text(json.dumps(self._runtime, indent=1, sort_keys=True))
            except OSError:
                pass
        return result


def as_dict(c: Classification) -> dict[str, Any]:
    return asdict(c)
