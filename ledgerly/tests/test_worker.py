from typing import Any

import pytest

from ledgerly import resilience
from ledgerly.processor_client import ProcessorDeclined, ProcessorResult, ProcessorTimeout
from ledgerly.worker.processing import process_charge
from tests.factories import fetch_charge, make_charge


class FakeProcessor:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def charge(self, **kwargs: Any) -> ProcessorResult:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resilience, "sleep", lambda _s: None)


def test_captured_charge_succeeds(pool: None, customer: str) -> None:
    charge = make_charge(customer)
    processor = FakeProcessor(ProcessorResult("ch_123", "captured"))
    assert process_charge(charge["id"], processor) == "succeeded"  # type: ignore[arg-type]
    row = fetch_charge(charge["id"])
    assert row["status"] == "succeeded"
    assert row["processor_ref"] == "ch_123"
    assert processor.calls[0]["reference"] == charge["idempotency_key"]


def test_declined_charge_fails(pool: None, customer: str) -> None:
    charge = make_charge(customer)
    processor = FakeProcessor(ProcessorDeclined("card_declined"))
    assert process_charge(charge["id"], processor) == "failed"  # type: ignore[arg-type]
    assert fetch_charge(charge["id"])["failure_reason"] == "declined"


def test_timeout_is_retried(pool: None, customer: str) -> None:
    charge = make_charge(customer)
    processor = FakeProcessor(ProcessorTimeout("slow"), ProcessorResult("ch_9", "captured"))
    assert process_charge(charge["id"], processor) == "succeeded"  # type: ignore[arg-type]
    assert len(processor.calls) == 2


def test_already_processed_charge_is_skipped(pool: None, customer: str) -> None:
    charge = make_charge(customer, status="succeeded")
    processor = FakeProcessor()
    assert process_charge(charge["id"], processor) is None  # type: ignore[arg-type]
    assert processor.calls == []
