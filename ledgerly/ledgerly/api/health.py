"""GET /healthz (process alive) and GET /readyz (database and Redis reachable)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ledgerly.db import get_conn

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports any failure
        checks["postgres"] = type(exc).__name__
    try:
        request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = type(exc).__name__
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503
    )
