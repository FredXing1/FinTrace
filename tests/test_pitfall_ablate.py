from __future__ import annotations

from typing import Any

from fintrace.core.budget import DEFAULT_PRICES, _price_for
from fintrace.core.llm import LLMResponse, MockLLM
from fintrace.data.edgar import companyfacts, tickers
from fintrace.data.pit import PitStore
from fintrace.pitfall.ablate import ARMS, NEUTRAL_PROMPT
from fintrace.pitfall.harness import run_tasks
from tests.conftest import make_companyfacts_zip, two_year_apple_doc


def test_arms_cover_the_factorial() -> None:
    # structural gate x prompt discipline x loop, one layer removed per arm
    assert set(ARMS) == {
        "full",
        "prompt-off",
        "gate-off",
        "neither",
        "no-tools",
        "single-shot",
    }
    assert ARMS["full"].tools == "gated" and ARMS["full"].prompt == "pit"
    assert ARMS["prompt-off"].tools == "gated" and ARMS["prompt-off"].prompt == "neutral"
    assert ARMS["gate-off"].tools == "ungated" and ARMS["gate-off"].prompt == "pit"
    assert ARMS["neither"].tools == "ungated" and ARMS["neither"].prompt == "neutral"
    assert ARMS["no-tools"].tools == "none" and ARMS["no-tools"].max_steps == 1
    assert ARMS["single-shot"].max_steps == 1
    # the neutral prompt must not carry any point-in-time discipline
    for banned in ("as_of", "point-in-time", "unknown"):
        assert banned not in NEUTRAL_PROMPT.lower()


def _null_task() -> dict[str, Any]:
    return {
        "task_id": "t1-null-1",
        "family": "T1",
        "subtype": "null",
        "cik": 320193,
        "tag": "Revenues",
        "period_start": "2021-09-26",
        "period_end": "2022-09-24",
        "as_of": "2022-01-01",
        "question": "q",
        "gold": {"kind": "unknown"},
    }


def test_run_tasks_reports_leak_and_latency(tmp_path, mem_con) -> None:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [two_year_apple_doc()]), mem_con)
    tickers.ingest({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}, mem_con)
    store = PitStore(mem_con)
    llm = MockLLM(
        [LLMResponse(content="Apple's FY2022 revenue was $394,328,000,000.", tool_calls=[])]
    )
    report = run_tasks([_null_task()], lambda _t: llm.complete([]).content, store=store)
    entry = report["results"][0]
    assert entry["correct"] is False  # gold is unknown; a specific value is wrong
    assert entry["leak"] is True  # ...and matches the realized future value
    assert entry["latency_s"] >= 0.0
    audit = report["t1_null_leak_audit"]
    assert audit["leaked_true_value"] == 1
    assert audit["leakage_rate"] == 1.0


def test_run_tasks_without_store_skips_leak_audit() -> None:
    report = run_tasks([_null_task()], lambda _t: "I don't have that information.")
    assert report["t1_null_leak_audit"] is None


def test_local_models_priced_free() -> None:
    assert "qwen2.5:14b" in DEFAULT_PRICES
    assert _price_for("qwen2.5:14b-instruct-q4_K_M", DEFAULT_PRICES) == (0.0, 0.0)
