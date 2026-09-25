"""Shared HTTP layer for SEC EDGAR access.

SEC fair-access policy requires every request to carry a declared User-Agent
with contact information; requests without one receive HTTP 403. Set
``FINTRACE_SEC_UA`` (e.g. ``"Jane Doe jane@example.com"``) before crawling.
Rate limiting defaults well below EDGAR's <= 10 req/s ceiling.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx

DEFAULT_UA = "FinTrace/0.0.1 (research crawler; UA not configured - set FINTRACE_SEC_UA)"

_RETRYABLE = {429, 500, 502, 503}


class RateLimiter:
    """Token-bucket rate limiter with injectable clock/sleep for tests."""

    def __init__(
        self,
        rate_per_sec: float,
        burst: int = 1,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate = rate_per_sec
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()

    def acquire(self) -> None:
        while True:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            self._sleep((1.0 - self._tokens) / self.rate)


def sec_user_agent() -> str:
    ua = os.environ.get("FINTRACE_SEC_UA", DEFAULT_UA)
    if "not configured" in ua:
        print(
            "[fintrace] WARNING: SEC requires a declared User-Agent with contact info; "
            "export FINTRACE_SEC_UA='Your Name you@example.com'",
            file=sys.stderr,
        )
    return ua


class SecHttpClient:
    """HTTP client for sec.gov hosts: UA policy, rate limiting, retry with backoff,
    and resumable downloads (``.part`` file + ``Range`` header)."""

    def __init__(
        self,
        base_url: str = "",
        rate_per_sec: float = 5.0,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": sec_user_agent()},
            timeout=timeout,
            follow_redirects=True,
        )
        self._limiter = RateLimiter(rate_per_sec, burst=2)
        self._max_retries = max_retries

    def _send(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                # ConnectTimeout / ReadTimeout / RemoteProtocolError etc.
                resp = None
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(2.0**attempt)
                continue
            if resp.status_code not in _RETRYABLE:
                break
            if attempt < self._max_retries:
                time.sleep(2.0**attempt)
        if resp is not None:
            resp.raise_for_status()
            return resp
        assert last_exc is not None
        raise last_exc

    def get(self, url: str) -> httpx.Response:
        return self._send(url)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return cast("dict[str, Any]", self._send(url, params).json())

    def download(self, url: str, dest: Path) -> Path:
        """Resumable download to ``dest`` (writes ``dest.part``, renames on completion)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        headers: dict[str, str] = {}
        if part.exists() and part.stat().st_size > 0:
            headers["Range"] = f"bytes={part.stat().st_size}-"
        self._limiter.acquire()
        with self._client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 416 and part.exists():
                # Range already satisfied: previous run finished writing the part file.
                part.rename(dest)
                return dest
            mode = "ab" if resp.status_code == 206 else "wb"
            resp.raise_for_status()
            with part.open(mode) as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
        part.rename(dest)
        return dest

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SecHttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
