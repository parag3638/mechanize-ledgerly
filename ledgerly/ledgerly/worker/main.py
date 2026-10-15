"""The charge worker. Run with `python -m ledgerly.worker.main`.

Reads new charge ids from the charges stream and captures them on a thread
pool of `worker_concurrency` threads. It only reads as many entries as it has
free threads, so unprocessed charges wait in Redis, not in memory.
"""

import os
import signal
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import FrameType

from prometheus_client import start_http_server

from ledgerly import queue
from ledgerly.config import get_settings
from ledgerly.db import init_pool
from ledgerly.log import get_logger
from ledgerly.metrics import STREAM_BACKLOG, WORKER_INFLIGHT, register_pool_gauges
from ledgerly.processor_client import ProcessorClient
from ledgerly.worker.processing import process_charge

log = get_logger(__name__)

RECLAIM_IDLE_MS = 30_000


def main() -> None:
    settings = get_settings()
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    init_pool(settings.app_dsn, settings.worker_pool_max, "worker")
    register_pool_gauges()
    start_http_server(settings.worker_metrics_port)

    redis_client = queue.connect()
    queue.ensure_group(redis_client)
    STREAM_BACKLOG.set_function(lambda: queue.backlog(redis_client))
    processor = ProcessorClient()

    slots = threading.BoundedSemaphore(settings.worker_concurrency)
    pool = ThreadPoolExecutor(settings.worker_concurrency, thread_name_prefix="charge")

    def handle(msg_id: str, charge_id: str) -> None:
        WORKER_INFLIGHT.inc()
        try:
            process_charge(charge_id, processor)
            queue.ack(redis_client, msg_id)
        except Exception:
            log.exception("charge processing crashed", charge_id=charge_id, msg_id=msg_id)
        finally:
            WORKER_INFLIGHT.dec()
            slots.release()

    def submit(entries: list[queue.Entry]) -> None:
        for msg_id, fields in entries:
            slots.acquire()
            pool.submit(handle, msg_id, fields["charge_id"])

    def stop(signum: int, _frame: FrameType | None) -> None:
        log.info("worker stopping", signal=signum)
        # Unacknowledged charges stay pending in the stream and are reclaimed on restart.
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    reclaimed = queue.reclaim(redis_client, consumer, RECLAIM_IDLE_MS)
    log.info(
        "worker started",
        event="startup",
        consumer=consumer,
        concurrency=settings.worker_concurrency,
        reclaimed=len(reclaimed),
    )
    submit(reclaimed)

    while True:
        slots.acquire()
        entries = queue.read(redis_client, consumer, count=1, block_ms=1000)
        if not entries:
            slots.release()
            continue
        msg_id, fields = entries[0]
        pool.submit(handle, msg_id, fields["charge_id"])


if __name__ == "__main__":
    main()
