"""The agent loop: plan -> tool calls -> observe -> answer, fully traced.

Design contracts:
- PIT discipline is structural: every tool is gated at ``as_of``, and the system
  prompt restates the cutoff. The loop itself never sees data beyond ``as_of``.
- Every LLM call is authorized by the BudgetGovernor *before* it is sent, and
  its actual usage is recorded after.
- Every step lands in the RunTrace; cached responses are marked as such.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fintrace.core.budget import BudgetGovernor, rough_token_estimate
from fintrace.core.cache import ResponseCache, cache_key
from fintrace.core.llm import LLM, LLMResponse
from fintrace.core.tools import ToolBox
from fintrace.core.trace import RunTrace

SYSTEM_PROMPT = """You are a point-in-time financial research agent.
Knowledge cutoff (as_of): {as_of}. Discipline:
1. Use ONLY the provided tools; every tool is PIT-gated at as_of.
2. Every number in your answer must come from a tool result; cite the accession
   number and filing date of the evidence.
3. If the evidence was not public at as_of, the correct answer is "unknown at
   as_of" — never guess from memory.
4. Respond in the language of the question.
"""

# Rough per-call completion estimate for pre-flight authorization; the actual
# usage is recorded afterwards.
_EST_COMPLETION_TOKENS = 2_000


@dataclass
class AgentResult:
    answer: str | None
    trace: RunTrace
    prompt_tokens: int
    completion_tokens: int
    cost_rmb: float
    steps: int
    trace_path: str | None = None


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolBox,
        *,
        model: str = "mock",
        governor: BudgetGovernor | None = None,
        cache: ResponseCache | None = None,
        max_steps: int = 8,
        temperature: float = 0.0,
        system_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.model = model
        self.governor = governor
        self.cache = cache
        self.max_steps = max_steps
        self.temperature = temperature
        # None -> the PIT discipline prompt. The leak audit passes a neutral
        # prompt to model naive agents that have no point-in-time discipline.
        self.system_prompt = system_prompt

    def run(self, question: str, *, as_of: str, save_trace: bool = True) -> AgentResult:
        trace = RunTrace(question=question, as_of=as_of)
        system_text = (self.system_prompt or SYSTEM_PROMPT).format(as_of=as_of)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": question},
        ]
        schemas = self.tools.schemas()
        total_prompt = total_completion = 0
        total_cost = 0.0
        answer: str | None = None

        for step_no in range(1, self.max_steps + 1):
            key = None
            if self.cache is not None:
                key = cache_key(self.model, messages, schemas, self.temperature)
                cached = self.cache.get(key)
            else:
                cached = None

            if cached is not None:
                resp = LLMResponse.from_dict(cached)
                cache_hit = True
            else:
                if self.governor is not None:
                    self.governor.authorize(
                        self.model,
                        rough_token_estimate(messages, schemas),
                        _EST_COMPLETION_TOKENS,
                    )
                resp = self.llm.complete(messages, tools=schemas)
                cache_hit = False
                if self.cache is not None and key is not None:
                    self.cache.put(key, resp.to_dict())

            if self.governor is not None:
                total_cost += self.governor.record(
                    resp.model, resp.prompt_tokens, resp.completion_tokens
                )
            total_prompt += resp.prompt_tokens
            total_completion += resp.completion_tokens
            trace.add(
                {
                    "step": step_no,
                    "type": "llm",
                    "model": resp.model,
                    "cache_hit": cache_hit,
                    "prompt_tokens": resp.prompt_tokens,
                    "completion_tokens": resp.completion_tokens,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in resp.tool_calls
                    ],
                    "content": resp.content,
                }
            )

            if not resp.tool_calls:
                answer = resp.content
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                }
            )
            for tc in resp.tool_calls:
                result = self.tools.call(tc.name, tc.arguments)
                trace.add(
                    {
                        "step": step_no,
                        "type": "tool",
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": ToolBox.dumps(result),
                    }
                )

        trace.finish()
        trace_path = trace.save() if save_trace else None
        return AgentResult(
            answer=answer,
            trace=trace,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            cost_rmb=total_cost,
            steps=len(trace.steps),
            trace_path=str(trace_path) if trace_path else None,
        )
