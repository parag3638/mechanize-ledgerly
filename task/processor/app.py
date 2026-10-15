"""Mock external payment processor ("Paystream").

- Deduplicates on the Idempotency-Key header (Ledgerly sends its charge id):
  once a charge is captured or declined, later requests return the stored result.
- Attempt n for a key behaves as `schedule.behaviour(seed, reference, n)`.
- Has a fixed number of work slots. A request holds its slot for its full
  service time even if the caller has already timed out, as a real upstream
  would. When retries pile up, everyone queues and latency rises.

Admin endpoints (grader only, token-protected): /_admin/reset, /_admin/ledger,
/_admin/recover. PROCESSOR_LEDGER_FILE preloads Paystream's state at the
incident handoff so refunds of handoff charges work.
"""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import schedule
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SEED = os.environ.get("PROCESSOR_SEED", "paystream-2026")
SLOTS = int(os.environ.get("PROCESSOR_SLOTS", "48"))
ADMIN_TOKEN = os.environ.get("PROCESSOR_ADMIN_TOKEN", "")
LEDGER_FILE = os.environ.get("PROCESSOR_LEDGER_FILE", "")

app = FastAPI(title="Paystream (mock)")


class _State:
    def __init__(self) -> None:
        self.slots = asyncio.Semaphore(SLOTS)
        self.attempts: dict[str, int] = {}
        # Requests per merchant reference, whatever Idempotency-Key the caller chose.
        self.ref_attempts: dict[str, int] = {}
        self.final: dict[str, tuple[int, dict[str, Any]]] = {}
        self.ledger: dict[str, dict[str, Any]] = {}
        self.refunds: dict[str, dict[str, Any]] = {}
        self.in_flight = 0
        self.queued = 0
        self.hang_enabled = True
        self.recovered = asyncio.Event()
        self._preload()

    def _preload(self) -> None:
        if not LEDGER_FILE or not os.path.exists(LEDGER_FILE):
            return
        with open(LEDGER_FILE) as fh:
            data = json.load(fh)
        for charge in data.get("charges", []):
            self.ledger[charge["id"]] = charge
            payload = {k: v for k, v in charge.items() if k != "idempotency_key"}
            self.final[charge["idempotency_key"]] = (201, payload)
        for key, refund in data.get("refund_keys", {}).items():
            self.refunds[key] = refund


state = _State()


class ChargeIn(BaseModel):
    reference: str
    customer: str
    amount_cents: int
    currency: str


class RefundIn(BaseModel):
    charge: str
    amount_cents: int


def _id(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.sha256(key.encode()).hexdigest()[:20]}"


@app.post("/v1/charges")
async def create_charge(
    body: ChargeIn, idempotency_key: str = Header(alias="Idempotency-Key")
) -> JSONResponse:
    state.ref_attempts[body.reference] = state.ref_attempts.get(body.reference, 0) + 1
    if idempotency_key in state.final:
        status, payload = state.final[idempotency_key]
        return JSONResponse(payload, status_code=status)

    attempt = state.attempts.get(idempotency_key, 0) + 1
    state.attempts[idempotency_key] = attempt
    plan = schedule.behaviour(SEED, body.reference, attempt, state.hang_enabled)

    state.queued += 1
    async with state.slots:
        state.queued -= 1
        state.in_flight += 1
        try:
            if plan.outcome == "ok":
                await asyncio.sleep(plan.delay_s)
            elif state.hang_enabled:
                # A stalled request; cut short if Paystream recovers meanwhile (capture only).
                try:
                    await asyncio.wait_for(state.recovered.wait(), timeout=plan.delay_s)
                except TimeoutError:
                    pass
            # else: Paystream has recovered; requests planned as stalls fail fast.
        finally:
            state.in_flight -= 1

    if idempotency_key in state.final:  # another attempt finished first
        status, payload = state.final[idempotency_key]
        return JSONResponse(payload, status_code=status)

    if plan.outcome == "ok":
        charge_id = _id("ch", idempotency_key)
        payload = {
            "id": charge_id,
            "status": "captured",
            "reference": body.reference,
            "amount_cents": body.amount_cents,
            "currency": body.currency,
        }
        state.ledger[charge_id] = {**payload, "idempotency_key": idempotency_key}
        state.final[idempotency_key] = (201, payload)
        return JSONResponse(payload, status_code=201)
    if plan.outcome == "declined":
        payload = {"error": {"code": "card_declined", "message": "The card was declined."}}
        state.final[idempotency_key] = (402, payload)
        return JSONResponse(payload, status_code=402)
    if plan.outcome == "unavailable":
        return JSONResponse({"error": {"code": "unavailable"}}, status_code=503)
    return JSONResponse({"error": {"code": "gateway_timeout"}}, status_code=504)


@app.post("/v1/refunds")
async def create_refund(
    body: RefundIn, idempotency_key: str = Header(alias="Idempotency-Key")
) -> JSONResponse:
    if idempotency_key in state.refunds:
        return JSONResponse(state.refunds[idempotency_key], status_code=201)
    charge = state.ledger.get(body.charge)
    if charge is None:
        return JSONResponse({"error": {"code": "no_such_charge"}}, status_code=404)
    if any(r["charge"] == body.charge for r in state.refunds.values()):
        return JSONResponse({"error": {"code": "already_refunded"}}, status_code=409)
    await asyncio.sleep(0.05)
    payload = {
        "id": _id("re", idempotency_key),
        "status": "refunded",
        "charge": body.charge,
        "amount_cents": body.amount_cents,
        "created_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    state.refunds[idempotency_key] = payload
    charge["status"] = "refunded"
    return JSONResponse(payload, status_code=201)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "in_flight": state.in_flight, "queued": state.queued}


def _check(token: str | None) -> None:
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=404)


@app.post("/_admin/reset")
async def reset(x_admin_token: str | None = Header(default=None)) -> dict[str, str]:
    _check(x_admin_token)
    global state
    state = _State()
    return {"status": "reset"}


@app.get("/_admin/ledger")
async def ledger(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    _check(x_admin_token)
    return {
        "charges": list(state.ledger.values()),
        "refunds": list(state.refunds.values()),
        "refund_keys": state.refunds,
        "attempts": state.attempts,
        "ref_attempts": state.ref_attempts,
    }


@app.post("/_admin/recover")
async def recover(x_admin_token: str | None = Header(default=None)) -> dict[str, str]:
    _check(x_admin_token)
    state.hang_enabled = False
    state.recovered.set()
    return {"status": "slow keys recovered"}
