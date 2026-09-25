from __future__ import annotations

import pytest

from fintrace.core.budget import BudgetExceeded, BudgetGovernor
from fintrace.core.cache import ResponseCache
from fintrace.core.llm import LLMResponse, MockLLM, ToolCall
from fintrace.core.runtime import Agent
from fintrace.core.tools import ToolBox, pit_tools
from fintrace.data.edgar import companyfacts, tickers
from fintrace.data.pit import PitStore
from tests.conftest import apple_facts_doc, make_companyfacts_zip

_QUESTION = "What was Apple's FY2022 revenue?"
_AS_OF = "2023-01-01"


def _mock_llm() -> MockLLM:
    return MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="query_fact",
                        arguments={
                            "ticker": "AAPL",
                            "tag": "Revenues",
                            "period_end": "2022-09-24",
                            "as_of": _AS_OF,
                        },
                    )
                ],
                model="qwen-plus",
                prompt_tokens=1000,
                completion_tokens=100,
            ),
            LLMResponse(
                content="FY2022 revenue was $394,328,000,000 (10-K, filed 2022-10-28).",
                tool_calls=[],
                model="qwen-plus",
                prompt_tokens=1500,
                completion_tokens=50,
            ),
        ],
        model="qwen-plus",
    )


@pytest.fixture()
def agent(tmp_path, mem_con) -> Agent:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    tickers.ingest({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}, mem_con)
    return Agent(
        _mock_llm(),
        ToolBox(pit_tools(PitStore(mem_con))),
        model="qwen-plus",
        governor=BudgetGovernor(session="test", ledger=tmp_path / "ledger.sqlite"),
        max_steps=4,
    )


def test_full_loop_traced_and_priced(agent: Agent, tmp_path) -> None:
    result = agent.run(_QUESTION, as_of=_AS_OF, save_trace=False)
    assert result.answer is not None and "394,328,000,000" in result.answer
    # steps: llm -> tool -> llm
    assert [s["type"] for s in result.trace.steps] == ["llm", "tool", "llm"]
    tool_step = result.trace.steps[1]
    assert tool_step["result"]["result"]["val"] == 394328000000.0
    # cost = (1000+1500)*0.8/1M + (100+50)*2.0/1M = 0.002 + 0.0003
    assert result.cost_rmb == pytest.approx(0.0023)
    assert (result.prompt_tokens, result.completion_tokens) == (2500, 150)


def test_max_steps_exhausted_returns_no_answer(tmp_path, mem_con) -> None:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    loop_llm = MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c", name="query_fact", arguments={"tag": "x"})],
            )
        ]
        * 4
        * 2  # enough tool-call responses to survive every step
    )
    agent = Agent(
        loop_llm,
        ToolBox(pit_tools(PitStore(mem_con))),
        model="mock",
        max_steps=4,
    )
    result = agent.run(_QUESTION, as_of=_AS_OF, save_trace=False)
    assert result.answer is None
    # 4 loop iterations, each an llm step + a tool step
    assert result.steps == 8
    assert sum(1 for s in result.trace.steps if s["type"] == "llm") == 4


def test_budget_hard_stop_aborts_run(tmp_path, mem_con) -> None:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    gov = BudgetGovernor(
        cap_rmb=0.0000001,
        session="t",
        ledger=tmp_path / "l.sqlite",
        prices={"mock": (1000.0, 1000.0)},
    )
    agent = Agent(
        _mock_llm(),
        ToolBox(pit_tools(PitStore(mem_con))),
        model="mock",
        governor=gov,
    )
    with pytest.raises(BudgetExceeded, match="cap"):
        agent.run(_QUESTION, as_of=_AS_OF, save_trace=False)


def test_cache_makes_second_run_free(tmp_path, mem_con) -> None:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    cache = ResponseCache(tmp_path / "cache.sqlite")
    store = PitStore(mem_con)

    run1 = Agent(
        _mock_llm(),
        ToolBox(pit_tools(store)),
        model="qwen-plus",
        cache=cache,
    ).run(_QUESTION, as_of=_AS_OF, save_trace=False)
    assert run1.answer is not None

    # Fresh MockLLM with an EMPTY queue: if anything misses the cache it explodes.
    run2 = Agent(
        MockLLM([]),
        ToolBox(pit_tools(store)),
        model="qwen-plus",
        cache=cache,
    ).run(_QUESTION, as_of=_AS_OF, save_trace=False)
    assert run2.answer == run1.answer
    assert all(step["cache_hit"] for step in run2.trace.steps if step["type"] == "llm")
