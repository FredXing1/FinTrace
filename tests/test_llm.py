from __future__ import annotations

from typing import Any

import pytest

from fintrace.core.llm import LLMResponse, MockLLM, OpenAICompatLLM, ToolCall, extract_tool_calls


def test_mock_llm_pops_queue_and_records_prompts() -> None:
    llm = MockLLM(
        [
            LLMResponse(content="a", tool_calls=[]),
            LLMResponse(content="b", tool_calls=[]),
        ]
    )
    assert llm.complete([{"role": "user", "content": "q"}]).content == "a"
    assert llm.complete([{"role": "user", "content": "q2"}]).content == "b"
    assert len(llm.prompts) == 2
    with pytest.raises(RuntimeError, match="exhausted"):
        llm.complete([{"role": "user", "content": "q3"}])


def test_extract_tool_calls_parses_string_arguments() -> None:
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "query_fact",
                                "arguments": '{"tag": "Revenues", "period_end": "2022-09-24"}',
                            },
                        }
                    ]
                }
            }
        ]
    }
    calls = extract_tool_calls(raw)
    assert calls == [
        ToolCall(
            id="call_1",
            name="query_fact",
            arguments={"tag": "Revenues", "period_end": "2022-09-24"},
        )
    ]


def test_extract_tool_calls_empty() -> None:
    assert extract_tool_calls({"choices": [{"message": {"content": "hi"}}]}) == []


def test_openai_compat_requires_config(monkeypatch) -> None:
    for var in ("FINTRACE_LLM_BASE_URL", "FINTRACE_LLM_MODEL", "FINTRACE_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError, match="FINTRACE_LLM_BASE_URL"):
        OpenAICompatLLM()


def test_response_dict_roundtrip() -> None:
    resp = LLMResponse(
        content="done",
        tool_calls=[ToolCall(id="c1", name="t", arguments={"a": 1})],
        model="m",
        prompt_tokens=10,
        completion_tokens=5,
    )
    restored = LLMResponse.from_dict(resp.to_dict())
    assert restored.content == "done"
    assert restored.tool_calls == resp.tool_calls
    assert (restored.prompt_tokens, restored.completion_tokens) == (10, 5)


def test_tools_passed_verbatim(monkeypatch) -> None:
    """Regression: complete() once double-wrapped tool dicts, and DeepSeek
    rejected the request with 'missing field name' (422)."""
    import httpx

    client = OpenAICompatLLM(base_url="https://example.test", model="m", api_key="k")
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any] | None = None) -> httpx.Response:
        captured["payload"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    monkeypatch.setattr(client._client, "post", fake_post)
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    client.complete([{"role": "user", "content": "hi"}], tools=tools)
    assert captured["payload"]["tools"] == tools
    client.close()
