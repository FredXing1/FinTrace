"""Pluggable LLM providers.

Any OpenAI-compatible endpoint works out of the box — DeepSeek, Qwen (DashScope
compatibility mode), GLM, Kimi, Doubao, vLLM, Ollama (``/v1``) — because they all
speak the chat-completions protocol. No vendor SDK: one httpx call. Configure via
environment variables::

    FINTRACE_LLM_BASE_URL  e.g. https://api.deepseek.com  (or http://localhost:11434/v1)
    FINTRACE_LLM_API_KEY   (omit for local endpoints that need no auth)
    FINTRACE_LLM_MODEL     e.g. deepseek-chat

MockLLM drives the loop deterministically for tests and offline demos.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from fintrace.data.http import RateLimiter

_RETRYABLE = {408, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    model: str = "mock"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ],
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LLMResponse:
        return cls(
            content=d.get("content"),
            tool_calls=[
                ToolCall(id=tc.get("id", ""), name=tc["name"], arguments=tc.get("arguments") or {})
                for tc in d.get("tool_calls") or []
            ],
            model=d.get("model", ""),
            prompt_tokens=int(d.get("prompt_tokens") or 0),
            completion_tokens=int(d.get("completion_tokens") or 0),
            finish_reason=d.get("finish_reason"),
        )


class LLM(Protocol):
    """Minimal provider surface the agent runtime depends on."""

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...


def extract_tool_calls(raw: dict[str, Any]) -> list[ToolCall]:
    """Parse OpenAI-style tool_calls out of a chat-completions response body."""
    calls: list[ToolCall] = []
    message = (raw.get("choices") or [{}])[0].get("message") or {}
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                parsed: dict[str, Any] = json.loads(args) if args else {}
            except json.JSONDecodeError:
                parsed = {"_raw": args}
        else:
            parsed = dict(args or {})
        calls.append(
            ToolCall(id=str(tc.get("id", "")), name=str(fn.get("name", "")), arguments=parsed)
        )
    return calls


class OpenAICompatLLM:
    """Chat-completions client for any OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
        temperature: float | None = 0.0,
        max_retries: int = 3,
        rate_per_sec: float = 5.0,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("FINTRACE_LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("FINTRACE_LLM_API_KEY", "")
        self.model = model or os.environ.get("FINTRACE_LLM_MODEL", "")
        if not self.base_url or not self.model:
            raise ValueError(
                "LLM endpoint not configured: set FINTRACE_LLM_BASE_URL and "
                "FINTRACE_LLM_MODEL (and FINTRACE_LLM_API_KEY if the endpoint requires auth)"
            )
        # None -> omit from payload entirely (some models, e.g. kimi-k2.6, lock
        # sampling params and reject temperature outright)
        self.temperature = temperature
        self._max_retries = max_retries
        # vendor-specific body extensions, e.g. Zhipu {"thinking": {"type": "disabled"}}
        self.extra_payload = extra_payload or {}
        self._limiter = RateLimiter(rate_per_sec, burst=2)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            timeout=timeout,
        )

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self.extra_payload)
        if tools:
            # Callers pass OpenAI-format tool dicts ({"type": "function", ...});
            # send them verbatim — wrapping again loses the inner "name" field.
            payload["tools"] = tools
        raw = self._send(payload)
        choice = (raw.get("choices") or [{}])[0]
        usage = raw.get("usage") or {}
        return LLMResponse(
            content=choice.get("message", {}).get("content"),
            tool_calls=extract_tool_calls(raw),
            model=str(raw.get("model", self.model)),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=choice.get("finish_reason"),
        )

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = self._client.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:
                resp = None
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(2.0**attempt)
                continue
            if resp.status_code not in _RETRYABLE:
                resp.raise_for_status()
                return dict(resp.json())
            last_exc = None
            if attempt < self._max_retries:
                time.sleep(2.0**attempt)
        if resp is not None:
            # final attempt still returned a retryable status: surface it properly
            print(
                f"[llm] giving up after {self._max_retries + 1} attempts: "
                f"{resp.status_code} {resp.text[:200]}",
                file=sys.stderr,
            )
            resp.raise_for_status()
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()


class MockLLM:
    """Scripted provider: pops queued responses in order and records every prompt.

    Lets tests and `--mock` demos drive the full agent loop with zero network.
    """

    def __init__(self, responses: Sequence[LLMResponse], *, model: str = "mock") -> None:
        self._queue: list[LLMResponse] = list(responses)
        self.model = model
        self.prompts: list[list[dict[str, Any]]] = []

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.prompts.append([dict(m) for m in messages])
        if not self._queue:
            raise RuntimeError("MockLLM queue exhausted: add responses for every loop step")
        return self._queue.pop(0)
