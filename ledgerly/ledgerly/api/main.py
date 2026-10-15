"""The Ledgerly API. Run with `uvicorn ledgerly.api.main:app`."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import make_asgi_app

from ledgerly import ids, queue
from ledgerly.api import charges, errors, health, refunds
from ledgerly.config import get_settings
from ledgerly.db import close_pool, init_pool
from ledgerly.log import get_logger, request_id_var
from ledgerly.metrics import HTTP_LATENCY, HTTP_REQUESTS, register_pool_gauges
from ledgerly.processor_client import ProcessorClient

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_pool(settings.app_dsn, settings.api_pool_max, name=f"{settings.service_name}-api")
    register_pool_gauges()
    app.state.redis = queue.connect()
    app.state.processor = ProcessorClient()
    log.info("api started", event="startup", pool_max=settings.api_pool_max)
    yield
    app.state.processor.close()
    close_pool()


app = FastAPI(title="Ledgerly", lifespan=lifespan)
errors.install(app)
app.include_router(charges.router)
app.include_router(refunds.router)
app.include_router(health.router)
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-Id") or ids.new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        path = getattr(request.scope.get("route"), "path", None) or "unmatched"
        if not request.url.path.startswith("/metrics"):
            elapsed = time.perf_counter() - started
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(elapsed)
            if status >= 500:
                log.warning(
                    "request failed",
                    event="http_5xx",
                    method=request.method,
                    path=path,
                    status=status,
                    duration_ms=round(elapsed * 1000, 1),
                )
        request_id_var.reset(token)
