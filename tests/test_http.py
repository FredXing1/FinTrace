from __future__ import annotations

import pytest

from fintrace.data.http import RateLimiter


def test_bursts_then_throttles() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    rl = RateLimiter(2.0, burst=1, clock=lambda: now[0], sleep=fake_sleep)
    rl.acquire()  # burst token, no wait
    rl.acquire()  # must wait 0.5s at 2 req/s
    rl.acquire()
    assert sleeps == [pytest.approx(0.5), pytest.approx(0.5)]


def test_rejects_nonpositive_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        RateLimiter(0)
    with pytest.raises(ValueError, match="burst"):
        RateLimiter(1.0, burst=0)


def test_send_retries_transport_errors(monkeypatch) -> None:
    from typing import Any

    import httpx

    from fintrace.data.http import SecHttpClient

    client = SecHttpClient(max_retries=2)
    calls = {"n": 0}

    def flaky_get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("handshake timed out")
        return httpx.Response(200, request=httpx.Request("GET", url), json={"ok": True})

    monkeypatch.setattr(client._client, "get", flaky_get)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert client.get_json("https://www.sec.gov/x") == {"ok": True}
    assert calls["n"] == 2
    client.close()
