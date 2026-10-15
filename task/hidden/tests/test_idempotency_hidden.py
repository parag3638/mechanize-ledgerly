"""Hidden test: one Idempotency-Key, one charge, across two API processes (grader-owned).

Starts two uvicorn processes of the agent's app (two replicas, as in production)
and sends concurrent requests with the same key to both. Expectation from
ARCHITECTURE.md ("one key maps to one charge"; "Two replicas behind a round-robin
proxy; any request can land on either.").
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator

import httpx
import pytest
from conftest import make_customer

TREE = os.environ["LEDGERLY_TREE"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def replicas() -> Iterator[list[str]]:
    procs: list[subprocess.Popen[bytes]] = []
    urls: list[str] = []
    for _ in range(2):
        port = _free_port()
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "ledgerly.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=TREE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        urls.append(f"http://127.0.0.1:{port}")
    deadline = time.monotonic() + 30
    for url in urls:
        while True:
            try:
                if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("agent API did not start")
            time.sleep(0.2)
    yield urls
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


async def _burst(urls: list[str], key: str, customer: str, copies: int) -> list[httpx.Response]:
    body = {"customer_id": customer, "amount_cents": 990, "currency": "USD"}
    async with httpx.AsyncClient(timeout=15) as client:
        return await asyncio.gather(
            *(
                client.post(f"{urls[i % 2]}/charges", json=body, headers={"Idempotency-Key": key})
                for i in range(copies)
            )
        )


@pytest.mark.check("hidden.idempotency_concurrent")
def test_concurrent_requests_with_one_key_create_one_charge(replicas: list[str], admin) -> None:
    customer = make_customer(admin)
    run = uuid.uuid4().hex[:8]
    keys = [f"hidem-{run}-{n:04d}" for n in range(40)]

    async def run_all() -> list[list[httpx.Response]]:
        return [await _burst(replicas, key, customer, copies=4) for key in keys]

    results = asyncio.run(run_all())
    for key, responses in zip(keys, results, strict=True):
        ok = [r for r in responses if r.status_code in (200, 201)]
        assert ok, f"{key}: no successful response ({[r.status_code for r in responses]})"
        assert len({r.json()["id"] for r in ok}) == 1, f"{key}: different charges returned"
    rows = admin.execute(
        """
        SELECT idempotency_key, count(*) AS n FROM charges
        WHERE idempotency_key LIKE %s GROUP BY 1 HAVING count(*) > 1
        """,
        (f"hidem-{run}-%",),
    ).fetchall()
    assert rows == [], f"duplicate charges: {rows}"


@pytest.mark.check("hidden.idempotency_concurrent")
def test_retry_after_success_returns_the_original_charge(replicas: list[str], admin) -> None:
    customer = make_customer(admin)
    key = f"hidem-r-{uuid.uuid4().hex[:8]}"
    body = {"customer_id": customer, "amount_cents": 1990, "currency": "USD"}
    first = httpx.post(f"{replicas[0]}/charges", json=body, headers={"Idempotency-Key": key})
    again = httpx.post(f"{replicas[1]}/charges", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
