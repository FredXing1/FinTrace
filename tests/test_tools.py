from __future__ import annotations

import pytest

from fintrace.core.tools import ToolBox, pit_tools
from fintrace.data.edgar import companyfacts, submissions, tickers
from fintrace.data.pit import PitStore
from tests.conftest import apple_facts_doc, make_companyfacts_zip, make_zip, submission_doc

_TICKER_MAP = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


@pytest.fixture()
def box(tmp_path, mem_con) -> ToolBox:
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    # entities already populated by the ticker map -> append mode; tickers go
    # LAST so the AAPL entity row (and its ticker) survives the upsert.
    submissions.ingest(
        make_zip(tmp_path, "submissions.zip", [submission_doc(320193)]), mem_con, append=True
    )
    tickers.ingest(_TICKER_MAP, mem_con)
    return ToolBox(pit_tools(PitStore(mem_con)))


def test_query_fact_via_toolbox(box: ToolBox) -> None:
    out = box.call(
        "query_fact",
        {"ticker": "AAPL", "tag": "Revenues", "period_end": "2022-09-24", "as_of": "2023-01-01"},
    )
    assert out["ok"] is True
    assert out["result"]["val"] == 394328000000.0
    assert str(out["result"]["filed"]) == "2022-10-28"


def test_query_fact_not_yet_public(box: ToolBox) -> None:
    out = box.call(
        "query_fact",
        {"ticker": "AAPL", "tag": "Revenues", "period_end": "2022-09-24", "as_of": "2022-10-01"},
    )
    assert out["ok"] is True
    assert out["result"] is None


def test_fact_history_and_filing_history(box: ToolBox) -> None:
    hist = box.call("fact_history", {"ticker": "AAPL", "tag": "Revenues", "as_of": "2023-12-31"})
    assert hist["ok"] is True and len(hist["result"]) == 2

    filings = box.call(
        "filing_history", {"ticker": "AAPL", "as_of": "2023-12-31", "forms": ["10-K"]}
    )
    assert filings["ok"] is True and len(filings["result"]) == 1


def test_as_of_is_enforced(mem_con) -> None:
    box = ToolBox(pit_tools(PitStore(mem_con)))
    out = box.call("query_fact", {"ticker": "AAPL", "tag": "Revenues", "period_end": "2022-09-24"})
    assert out["ok"] is False
    assert "as_of" in out["error"]


def test_unknown_tool_and_unknown_ticker(mem_con) -> None:
    box = ToolBox(pit_tools(PitStore(mem_con)))
    assert box.call("nope", {})["ok"] is False
    out = box.call(
        "query_fact",
        {"ticker": "NOPE", "tag": "t", "period_end": "2020-01-01", "as_of": "2021-01-01"},
    )
    assert out["ok"] is False
    assert "unknown ticker" in out["error"]


def test_ungated_tools_return_latest_ignoring_as_of(tmp_path, mem_con) -> None:
    from fintrace.core.tools import ToolBox as TB
    from fintrace.core.tools import pit_tools_ungated
    from fintrace.data.edgar import tickers as tkg
    from fintrace.data.pit import PitStore
    from tests.conftest import apple_facts_doc, make_companyfacts_zip

    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    tkg.ingest({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}, mem_con)
    box = TB(pit_tools_ungated(PitStore(mem_con)))

    # no as_of argument exists; returns the LATEST filed version (restated)
    out = box.call(
        "query_fact",
        {"ticker": "AAPL", "tag": "Revenues", "period_end": "2022-09-24"},
    )
    assert out["ok"] is True
    assert out["result"]["val"] == 394327001000.0
    assert str(out["result"]["filed"]) == "2023-11-03"
