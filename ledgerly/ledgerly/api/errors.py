"""One error shape for every failure: {"error": {"code", "message", "requestId"}}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from ledgerly.log import get_logger, request_id_var

log = get_logger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "requestId": request_id_var.get()}
    error.update(extra)
    return {"error": error}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(PoolTimeout)
    async def _pool_timeout(_: Request, exc: PoolTimeout) -> JSONResponse:
        log.error("db pool exhausted", event="pool_timeout", error=str(exc))
        return JSONResponse(
            _body("unavailable", "The service is busy. Retry with the same Idempotency-Key."),
            status_code=503,
        )

    @app.exception_handler(OperationalError)
    async def _db_down(_: Request, exc: OperationalError) -> JSONResponse:
        log.error("database error", event="db_error", error=str(exc))
        return JSONResponse(
            _body("unavailable", "The database is unavailable. Retry shortly."), status_code=503
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
        return JSONResponse(
            _body("invalid_request", "Check the highlighted fields.", fields=fields),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code)
