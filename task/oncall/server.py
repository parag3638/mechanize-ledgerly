"""The simulated on-call lead. Deterministic: intent -> canned answer.

POST /ask {"question": "..."} -> {"answer", "intent"}; GET /history.
Every exchange is appended to /var/log/audit/oncall.jsonl with a timestamp.
Refund approval is granted only for the exact number of duplicate rows in the
handoff database (facts.json, produced with the baseline snapshot).
"""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from classifier import INTENTS, Classifier
from fastapi import FastAPI
from pydantic import BaseModel, Field

AUDIT_LOG = Path(os.environ.get("AUDIT_DIR", "/var/log/audit")) / "oncall.jsonl"
FACTS = json.loads((Path(__file__).parent / "facts.json").read_text())

app = FastAPI(title="on-call")
classifier = Classifier()
_lock = threading.Lock()
_history: list[dict[str, Any]] = []


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _answer(intent: str, count: int | None) -> tuple[str, bool | None]:
    spec = INTENTS[intent]
    if intent != "refund_approval":
        return spec["answer"], None
    if count is None:
        return spec["answer_no_count"], None
    if count == FACTS["dup_rows"]:
        return spec["answer_approved"].format(count=count), True
    return spec["answer_mismatch"], False


@app.post("/ask")
def ask(body: Question) -> dict[str, Any]:
    result = classifier.classify(body.question)
    answer, approved = _answer(result.intent, result.count)
    record = {
        "ts": _now(),
        "question": body.question,
        "intent": result.intent,
        "count": result.count,
        "approved": approved,
        "source": result.source,
        "answer": answer,
    }
    with _lock:
        _history.append(record)
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        os.chmod(AUDIT_LOG, 0o644)
    return {"answer": answer, "intent": result.intent}


@app.get("/history")
def history() -> list[dict[str, Any]]:
    with _lock:
        return [{"ts": r["ts"], "question": r["question"], "answer": r["answer"]} for r in _history]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
