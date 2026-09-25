from __future__ import annotations

import pytest

from fintrace.data.edgar import companyfacts
from fintrace.data.pit import PitStore
from tests.conftest import apple_facts_doc, make_companyfacts_zip


@pytest.fixture()
def store(tmp_path, mem_con):
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [apple_facts_doc()]), mem_con)
    return PitStore(mem_con)


def test_no_future_knowledge(store) -> None:
    # FY2022 fact was filed 2022-10-28; before that date it must be invisible.
    before = store.fact(320193, "Revenues", period_end="2022-09-24", as_of="2022-10-01")
    assert before is None
    after = store.fact(320193, "Revenues", period_end="2022-09-24", as_of="2022-10-28")
    assert after is not None
    assert str(after["filed"]) == "2022-10-28"


def test_restatement_awareness(store) -> None:
    # The same period was re-reported in the FY2023 10-K (filed 2023-11-03).
    early = store.fact(320193, "Revenues", period_end="2022-09-24", as_of="2023-01-01")
    late = store.fact(320193, "Revenues", period_end="2022-09-24", as_of="2023-12-31")
    assert early is not None and late is not None
    assert early["accn"] == "0000320193-22-000108"
    assert late["accn"] == "0000320193-23-000106"
    assert late["val"] == 394327001000.0


def test_period_start_filter(store) -> None:
    got = store.fact(
        320193,
        "Revenues",
        period_end="2023-09-30",
        period_start="2023-01-01",
        as_of="2023-12-31",
    )
    assert got is not None and got["val"] == 1000.0
    # without the duration start, the instant-style lookup still works on period_end
    any_kind = store.fact(320193, "Revenues", period_end="2023-09-30", as_of="2023-12-31")
    assert any_kind is not None


def test_as_of_is_required(store) -> None:
    with pytest.raises(TypeError):
        store.fact(320193, "Revenues", period_end="2022-09-24")


def test_history_one_version_per_period(store) -> None:
    rows = store.history(320193, "Revenues", as_of="2023-12-31")
    # 2 distinct periods: FY2022 instant (two filings -> one row) + the 2023 duration
    assert len(rows) == 2
    fy2022 = [r for r in rows if str(r["period_end"]) == "2022-09-24"]
    assert len(fy2022) == 1
    assert fy2022[0]["accn"] == "0000320193-23-000106"


def test_resolve_cik(tmp_path, mem_con) -> None:
    from fintrace.data.edgar import submissions
    from tests.conftest import make_zip, submission_doc

    submissions.ingest(make_zip(tmp_path, "submissions.zip", [submission_doc(320193)]), mem_con)
    store = PitStore(mem_con)
    assert store.resolve_cik("T320193") == 320193
    assert store.resolve_cik("t320193") == 320193  # case-insensitive
    assert store.resolve_cik("NOPE") is None


def test_filings_pit_filter(tmp_path, mem_con) -> None:
    from fintrace.data.edgar import submissions
    from tests.conftest import make_zip, submission_doc

    submissions.ingest(make_zip(tmp_path, "submissions.zip", [submission_doc(7)]), mem_con)
    store = PitStore(mem_con)
    assert store.filings(7, as_of="2023-01-01") == []
    rows = store.filings(7, as_of="2023-12-31", forms=["10-K"])
    assert len(rows) == 1 and rows[0]["form"] == "10-K"
