from __future__ import annotations

from typing import Any

import pytest

from fintrace.core.llm import LLMResponse, MockLLM
from fintrace.data.edgar import companyfacts, tickers
from fintrace.data.pit import PitStore
from fintrace.pitfall.leak import run_leak_audit, ungated_question
from tests.conftest import make_companyfacts_zip, two_year_apple_doc


def _t1_null_task() -> dict[str, Any]:
    return {
        "task_id": "t1-1",
        "family": "T1",
        "subtype": "null",
        "cik": 320193,
        "entity": "APPLE INC",
        "tag": "Revenues",
        "metric": "revenue",
        "period_start": "2021-09-26",
        "period_end": "2022-09-24",
        "as_of": "2022-01-01",
        "question": (
            "According to public SEC filings available as of 2022-01-01, what was the "
            "revenue of APPLE INC (ticker: AAPL) for the fiscal period ending 2022-09-24? "
            "If this was not public at that date, answer exactly: unknown."
        ),
        "gold": {"kind": "unknown"},
        "meta": {},
    }


def test_ungated_question_strips_as_of_framing() -> None:
    q = ungated_question(_t1_null_task())
    assert q.startswith("What was the revenue of APPLE INC (ticker: AAPL)")
    assert "as of" not in q.lower()
    assert "unknown" not in q.lower()


def test_ungated_t3_question() -> None:
    task = {
        "task_id": "t3-1",
        "family": "T3",
        "subtype": "forward",
        "question": (
            "As of 2022-03-28, estimate the research and development expense of "
            "SOME CORP (CIK 123) for the fiscal year ending 2022-12-31, using only "
            "information that was public at that time. Reply with a single number in USD."
        ),
        "gold": {"kind": "forward"},
    }
    q = ungated_question(task)
    assert q.startswith("What was the research and development expense of SOME CORP")
    assert "as of" not in q.lower()
    assert q.endswith("Answer with a single number in USD.")


@pytest.fixture()
def store(tmp_path, mem_con) -> PitStore:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [two_year_apple_doc()]), mem_con)
    tickers.ingest({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}, mem_con)
    return PitStore(mem_con)


def test_leak_audit_detects_memorized_value(store) -> None:
    task = _t1_null_task()
    llm = MockLLM(
        [LLMResponse(content="Apple's FY2022 revenue was $394,328,000,000.", tool_calls=[])]
    )
    report = run_leak_audit([task], llm, store)
    entry = report["results"][0]
    # gold is "unknown": any specific answer is wrong under gating...
    assert entry["correct"] is False
    # ...and the value matches the realized (restated) figure within 1% -> LEAK
    assert entry["leak"] is True
    assert report["t1_null_leak_audit"]["leaked_true_value"] == 1
    assert report["t1_null_leak_audit"]["leakage_rate"] == 1.0


def test_leak_audit_honest_unknown_is_not_leak(store) -> None:
    task = _t1_null_task()
    llm = MockLLM([LLMResponse(content="I don't have that information.", tool_calls=[])])
    report = run_leak_audit([task], llm, store)
    entry = report["results"][0]
    assert entry["correct"] is True  # unknown is the correct gated answer
    assert entry["leak"] is False
    assert report["t1_null_leak_audit"]["ungated_said_unknown"] == 1
