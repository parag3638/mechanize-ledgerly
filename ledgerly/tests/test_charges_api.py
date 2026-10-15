from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ledgerly.api.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def charge_body(customer: str, amount: int = 1250) -> dict[str, object]:
    return {"customer_id": customer, "amount_cents": amount, "currency": "USD"}


def test_create_charge_returns_pending_charge(client: TestClient, customer: str) -> None:
    resp = client.post("/charges", json=charge_body(customer), headers={"Idempotency-Key": "k-1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["idempotency_key"] == "k-1"
    assert resp.headers["X-Request-Id"]


def test_retry_with_same_key_returns_original_charge(client: TestClient, customer: str) -> None:
    first = client.post("/charges", json=charge_body(customer), headers={"Idempotency-Key": "k-2"})
    again = client.post("/charges", json=charge_body(customer), headers={"Idempotency-Key": "k-2"})
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]


def test_same_key_concurrently_creates_one_charge(client: TestClient, customer: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def post() -> dict[str, object]:
        resp = client.post(
            "/charges", json=charge_body(customer), headers={"Idempotency-Key": "k-burst"}
        )
        assert resp.status_code in (200, 201)
        return resp.json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        bodies = list(pool.map(lambda _: post(), range(4)))
    assert len({b["id"] for b in bodies}) == 1


def test_get_charge(client: TestClient, customer: str) -> None:
    created = client.post(
        "/charges", json=charge_body(customer), headers={"Idempotency-Key": "k-3"}
    ).json()
    resp = client.get(f"/charges/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["amount_cents"] == 1250


def test_unknown_charge_is_404(client: TestClient) -> None:
    resp = client.get("/charges/8a3c5a52-58f6-4a43-9f5c-6d0e2f1a9b77")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "charge_not_found"


def test_missing_idempotency_key_is_rejected(client: TestClient, customer: str) -> None:
    resp = client.post("/charges", json=charge_body(customer))
    assert resp.status_code == 422


def test_velocity_limit(client: TestClient) -> None:
    from tests.factories import make_customer

    capped = make_customer(daily_cap_cents=2000)
    ok = client.post("/charges", json=charge_body(capped, 1500), headers={"Idempotency-Key": "v-1"})
    over = client.post(
        "/charges", json=charge_body(capped, 1500), headers={"Idempotency-Key": "v-2"}
    )
    assert ok.status_code == 201
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "velocity_limit"
