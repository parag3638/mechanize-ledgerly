import pytest

from ledgerly import resilience
from ledgerly.resilience import retry


class Flaky(Exception):
    pass


class Fatal(Exception):
    pass


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(resilience, "sleep", slept.append)
    return slept


def make_call(failures: int, exc: type[Exception] = Flaky):
    calls = {"n": 0}

    def call() -> str:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc("boom")
        return "ok"

    return call, calls


def test_returns_result_after_transient_failures() -> None:
    call, calls = make_call(failures=2)
    assert retry(on=(Flaky,))(call)() == "ok"
    assert calls["n"] == 3


def test_does_not_retry_other_exceptions() -> None:
    call, calls = make_call(failures=1, exc=Fatal)
    with pytest.raises(Fatal):
        retry(on=(Flaky,))(call)()
    assert calls["n"] == 1


def test_gives_up_after_attempts() -> None:
    call, calls = make_call(failures=5)
    with pytest.raises(Flaky):
        retry(on=(Flaky,), attempts=3)(call)()
    assert calls["n"] == 3


def test_waits_between_attempts_when_delay_set(no_sleep: list[float]) -> None:
    call, _ = make_call(failures=2)
    retry(on=(Flaky,), delay=0.5)(call)()
    assert no_sleep == [0.5, 0.5]
