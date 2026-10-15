"""Capture one charge with the processor and record the outcome.

The customer's in-flight amount is reserved for the duration of the capture so
the velocity check in the API sees money that is about to move.
"""

from typing import Any

from ledgerly.db import get_conn
from ledgerly.log import get_logger
from ledgerly.metrics import CHARGES_PROCESSED
from ledgerly.processor_client import (
    ProcessorClient,
    ProcessorDeclined,
    ProcessorError,
    ProcessorResult,
    ProcessorTimeout,
)
from ledgerly.resilience import retry

log = get_logger(__name__)


@retry(on=(ProcessorTimeout, ProcessorError))
def charge_processor(client: ProcessorClient, charge: dict[str, Any]) -> ProcessorResult:
    return client.charge(
        charge_id=str(charge["id"]),
        reference=charge["idempotency_key"],
        customer_id=charge["customer_id"],
        amount_cents=charge["amount_cents"],
        currency=charge["currency"].strip(),
    )


def process_charge(charge_id: str, client: ProcessorClient) -> str | None:
    """Capture a pending charge. Returns the final status, or None if there was nothing to do."""
    with get_conn() as conn, conn.transaction():
        charge = conn.execute(
            """
            SELECT id, idempotency_key, customer_id, amount_cents, currency, status
            FROM charges WHERE id = %s FOR UPDATE
            """,
            (charge_id,),
        ).fetchone()
        if charge is None or charge["status"] != "pending":
            log.info("charge skipped", charge_id=charge_id, status=charge and charge["status"])
            return None

        conn.execute(
            "UPDATE charges SET status = 'processing', updated_at = now() WHERE id = %s",
            (charge_id,),
        )
        conn.execute(
            "UPDATE customers SET in_flight_cents = in_flight_cents + %s WHERE id = %s",
            (charge["amount_cents"], charge["customer_id"]),
        )

        processor_ref: str | None = None
        failure_reason: str | None = None
        try:
            result = charge_processor(client, charge)
            status, processor_ref = "succeeded", result.processor_ref
        except ProcessorDeclined:
            status, failure_reason = "failed", "declined"
        except ProcessorError:
            status, failure_reason = "failed", "processor_unavailable"

        conn.execute(
            """
            UPDATE charges SET status = %s, processor_ref = %s, failure_reason = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (status, processor_ref, failure_reason, charge_id),
        )
        conn.execute(
            "UPDATE customers SET in_flight_cents = in_flight_cents - %s WHERE id = %s",
            (charge["amount_cents"], charge["customer_id"]),
        )

    CHARGES_PROCESSED.labels(status=status).inc()
    log.info(
        "charge processed",
        event="charge_processed",
        charge_id=charge_id,
        idempotency_key=charge["idempotency_key"],
        status=status,
        failure_reason=failure_reason,
    )
    return status
