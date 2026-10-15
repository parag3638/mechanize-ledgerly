"""POST /refunds and GET /refunds?charge_id=.

Full refunds only, one per charge. The refund row is recorded as pending,
sent to Paystream, then finalised with Paystream's answer.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ledgerly import ids
from ledgerly.api.errors import ApiError
from ledgerly.db import get_conn
from ledgerly.log import get_logger
from ledgerly.processor_client import ProcessorClient, ProcessorDeclined, ProcessorError

log = get_logger(__name__)
router = APIRouter()

REFUND_COLUMNS = (
    "id, charge_id, amount_cents, reason, status, processor_ref, created_at, updated_at"
)


class RefundIn(BaseModel):
    charge_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=200)


class RefundOut(BaseModel):
    id: str
    charge_id: str
    amount_cents: int
    reason: str
    status: str
    processor_ref: str | None
    created_at: datetime
    updated_at: datetime


def to_out(row: dict[str, Any]) -> RefundOut:
    return RefundOut(**{**row, "id": str(row["id"]), "charge_id": str(row["charge_id"])})


@router.post("/refunds", status_code=201)
def create_refund(body: RefundIn, request: Request) -> RefundOut:
    try:
        ids.parse(body.charge_id)
    except ValueError as exc:
        raise ApiError(404, "charge_not_found", "No charge with that id.") from exc

    with get_conn() as conn, conn.transaction():
        charge = conn.execute(
            "SELECT id, amount_cents, status, processor_ref FROM charges WHERE id = %s FOR UPDATE",
            (body.charge_id,),
        ).fetchone()
        if charge is None:
            raise ApiError(404, "charge_not_found", "No charge with that id.")
        if charge["status"] != "succeeded" or charge["processor_ref"] is None:
            raise ApiError(
                409,
                "not_refundable",
                f"Only succeeded charges can be refunded ({charge['status']}).",
            )
        open_refund = conn.execute(
            "SELECT id FROM refunds WHERE charge_id = %s AND status IN ('pending', 'succeeded')",
            (body.charge_id,),
        ).fetchone()
        if open_refund is not None:
            raise ApiError(409, "already_refunded", "This charge already has a refund.")
        refund = conn.execute(
            f"""
            INSERT INTO refunds (id, charge_id, amount_cents, reason, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING {REFUND_COLUMNS}
            """,
            (ids.new_id(), body.charge_id, charge["amount_cents"], body.reason),
        ).fetchone()
        assert refund is not None

    processor: ProcessorClient = request.app.state.processor
    try:
        result = processor.refund(
            refund_id=str(refund["id"]),
            processor_ref=charge["processor_ref"],
            amount_cents=charge["amount_cents"],
        )
    except (ProcessorError, ProcessorDeclined) as exc:
        with get_conn() as conn, conn.transaction():
            conn.execute(
                "UPDATE refunds SET status = 'failed', updated_at = now() WHERE id = %s",
                (refund["id"],),
            )
        log.error("refund failed at processor", refund_id=str(refund["id"]), error=str(exc))
        raise ApiError(502, "processor_error", "The processor did not accept the refund.") from exc

    with get_conn() as conn, conn.transaction():
        row = conn.execute(
            f"""
            UPDATE refunds SET status = 'succeeded', processor_ref = %s, updated_at = now()
            WHERE id = %s RETURNING {REFUND_COLUMNS}
            """,
            (result.processor_ref, refund["id"]),
        ).fetchone()
        conn.execute(
            "UPDATE charges SET status = 'refunded', updated_at = now() WHERE id = %s",
            (body.charge_id,),
        )
    assert row is not None
    log.info(
        "refund succeeded",
        event="refund_succeeded",
        refund_id=str(row["id"]),
        charge_id=body.charge_id,
        reason=body.reason,
    )
    return to_out(row)


@router.get("/refunds")
def list_refunds(charge_id: str) -> list[RefundOut]:
    try:
        ids.parse(charge_id)
    except ValueError:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {REFUND_COLUMNS} FROM refunds WHERE charge_id = %s ORDER BY created_at",
            (charge_id,),
        ).fetchall()
    return [to_out(r) for r in rows]
