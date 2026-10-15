"""POST /charges and GET /charges/{id}.

A charge is created `pending` and handed to the worker through the charges
stream; the worker captures it with the processor. Clients retry with the same
Idempotency-Key, and get the original charge back.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, Field

from ledgerly import ids, queue
from ledgerly.api.errors import ApiError
from ledgerly.db import get_conn
from ledgerly.log import get_logger

log = get_logger(__name__)
router = APIRouter()

CHARGE_COLUMNS = (
    "id, idempotency_key, customer_id, amount_cents, currency, status, processor_ref, "
    "failure_reason, created_at, updated_at"
)


class ChargeIn(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(gt=0, le=10_000_000)
    currency: str = Field(pattern="^[A-Z]{3}$")


class ChargeOut(BaseModel):
    id: str
    idempotency_key: str
    customer_id: str
    amount_cents: int
    currency: str
    status: str
    processor_ref: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


def to_out(row: dict[str, Any]) -> ChargeOut:
    return ChargeOut(**{**row, "id": str(row["id"]), "currency": row["currency"].strip()})


@router.post("/charges", status_code=201)
def create_charge(
    body: ChargeIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> ChargeOut:
    with get_conn() as conn, conn.transaction():
        existing = conn.execute(
            f"SELECT {CHARGE_COLUMNS} FROM charges WHERE idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            response.status_code = 200
            return to_out(existing)

        # Velocity check: lock the customer row so concurrent charges can't both pass the cap.
        customer = conn.execute(
            """
            SELECT id, daily_cap_cents, charged_today_cents FROM customers
            WHERE id = %s FOR UPDATE
            """,
            (body.customer_id,),
        ).fetchone()
        if customer is None:
            raise ApiError(404, "customer_not_found", "No customer with that id.")
        if customer["charged_today_cents"] + body.amount_cents > customer["daily_cap_cents"]:
            raise ApiError(422, "velocity_limit", "This charge exceeds the customer's daily limit.")

        row = conn.execute(
            f"""
            INSERT INTO charges (id, idempotency_key, customer_id, amount_cents, currency, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            RETURNING {CHARGE_COLUMNS}
            """,
            (ids.new_id(), idempotency_key, body.customer_id, body.amount_cents, body.currency),
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE customers SET charged_today_cents = charged_today_cents + %s WHERE id = %s",
            (body.amount_cents, body.customer_id),
        )

    charge = to_out(row)
    queue.publish_charge_created(request.app.state.redis, charge.id)
    log.info(
        "charge created",
        event="charge_created",
        charge_id=charge.id,
        idempotency_key=idempotency_key,
        customer_id=charge.customer_id,
        amount_cents=charge.amount_cents,
    )
    return charge


@router.get("/charges/{charge_id}")
def get_charge(charge_id: str) -> ChargeOut:
    try:
        ids.parse(charge_id)
    except ValueError as exc:
        raise ApiError(404, "charge_not_found", "No charge with that id.") from exc
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {CHARGE_COLUMNS} FROM charges WHERE id = %s", (charge_id,)
        ).fetchone()
    if row is None:
        raise ApiError(404, "charge_not_found", "No charge with that id.")
    return to_out(row)
