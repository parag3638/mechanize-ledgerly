"""Client for the external payment processor (Paystream).

The processor deduplicates on the `Idempotency-Key` header, which we set to our
charge (or refund) id. `reference` must be the client's Idempotency-Key: Finance
reconciles our ledger against the processor's by that field.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ledgerly.config import get_settings
from ledgerly.metrics import PROCESSOR_CALLS, PROCESSOR_LATENCY


class ProcessorError(Exception):
    """The processor failed in a way that may succeed on a later attempt (5xx, network)."""


class ProcessorTimeout(ProcessorError):
    """No response within `processor_timeout_s`."""


class ProcessorDeclined(Exception):
    """The processor refused the payment. Final; never retried."""


@dataclass(frozen=True)
class ProcessorResult:
    processor_ref: str
    status: str


class ProcessorClient:
    def __init__(self, base_url: str | None = None, timeout_s: float | None = None) -> None:
        settings = get_settings()
        self._http = httpx.Client(
            base_url=base_url or settings.processor_url,
            timeout=timeout_s if timeout_s is not None else settings.processor_timeout_s,
        )

    def charge(
        self, *, charge_id: str, reference: str, customer_id: str, amount_cents: int, currency: str
    ) -> ProcessorResult:
        body = {
            "reference": reference,
            "customer": customer_id,
            "amount_cents": amount_cents,
            "currency": currency,
        }
        data = self._post("charge", "/v1/charges", charge_id, body)
        return ProcessorResult(processor_ref=data["id"], status=data["status"])

    def refund(self, *, refund_id: str, processor_ref: str, amount_cents: int) -> ProcessorResult:
        body = {"charge": processor_ref, "amount_cents": amount_cents}
        data = self._post("refund", "/v1/refunds", refund_id, body)
        return ProcessorResult(processor_ref=data["id"], status=data["status"])

    def _post(self, op: str, path: str, idempotency_key: str, body: dict[str, Any]) -> Any:
        started = time.perf_counter()
        try:
            resp = self._http.post(path, json=body, headers={"Idempotency-Key": idempotency_key})
        except httpx.TimeoutException as exc:
            PROCESSOR_CALLS.labels(op=op, outcome="timeout").inc()
            raise ProcessorTimeout(f"{op} timed out") from exc
        except httpx.TransportError as exc:
            PROCESSOR_CALLS.labels(op=op, outcome="network_error").inc()
            raise ProcessorError(f"{op} failed: {exc}") from exc
        finally:
            PROCESSOR_LATENCY.labels(op=op).observe(time.perf_counter() - started)

        if resp.status_code == 402:
            PROCESSOR_CALLS.labels(op=op, outcome="declined").inc()
            raise ProcessorDeclined(resp.text)
        if resp.status_code >= 500:
            PROCESSOR_CALLS.labels(op=op, outcome=f"http_{resp.status_code}").inc()
            raise ProcessorError(f"{op} returned {resp.status_code}")
        resp.raise_for_status()
        PROCESSOR_CALLS.labels(op=op, outcome="ok").inc()
        return resp.json()

    def close(self) -> None:
        self._http.close()
