"""Prometheus metrics shared by the API and the worker.

The API serves them on `/metrics`; the worker on `:9101/metrics`.
"""

from prometheus_client import Counter, Gauge, Histogram

from ledgerly.db import get_pool

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
PROCESSOR_CALLS = Counter(
    "processor_calls_total", "Calls to the payment processor", ["op", "outcome"]
)
PROCESSOR_LATENCY = Histogram(
    "processor_call_duration_seconds",
    "Payment processor call latency",
    ["op"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
RETRIES = Counter("retries_total", "Retries performed by ledgerly.resilience", ["fn"])
CHARGES_PROCESSED = Counter(
    "charges_processed_total", "Charges finalised by the worker", ["status"]
)
WORKER_INFLIGHT = Gauge("worker_inflight", "Charges currently being processed by the worker")
STREAM_BACKLOG = Gauge("stream_backlog", "Entries in the charges stream not yet delivered")

DB_POOL_SIZE = Gauge("db_pool_size", "Connections open in the pool")
DB_POOL_AVAILABLE = Gauge("db_pool_available", "Idle connections in the pool")
DB_POOL_WAITING = Gauge("db_pool_waiting", "Requests waiting for a pooled connection")


def _pool_stat(key: str) -> float:
    try:
        return float(get_pool().get_stats().get(key, 0))
    except RuntimeError:
        return 0.0


def register_pool_gauges() -> None:
    DB_POOL_SIZE.set_function(lambda: _pool_stat("pool_size"))
    DB_POOL_AVAILABLE.set_function(lambda: _pool_stat("pool_available"))
    DB_POOL_WAITING.set_function(lambda: _pool_stat("requests_waiting"))
