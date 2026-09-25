from __future__ import annotations

import pytest

from fintrace.data.edgar import submissions
from tests.conftest import make_zip, submission_doc


def test_ingest_roundtrip(tmp_path, mem_con) -> None:
    zip_path = make_zip(tmp_path, "submissions.zip", [submission_doc(320193)])
    stats = submissions.ingest(zip_path, mem_con)
    assert stats == {"entities": 1, "former_names": 1, "filings": 1}

    row = mem_con.execute(
        "SELECT name, tickers, sic_description FROM entities WHERE cik = 320193"
    ).fetchone()
    assert row is not None
    assert row[0] == "TEST CORP 320193"
    assert row[1] == ["T320193"]
    assert row[2] == "Electronic Computers"

    filing = mem_con.execute(
        "SELECT filing_date, report_date, form, primary_document FROM filings WHERE cik = 320193"
    ).fetchone()
    assert filing is not None
    assert str(filing[0]) == "2023-11-03"
    assert str(filing[1]) == "2023-09-30"
    assert filing[2] == "10-K"
    assert filing[3] == "test-20230930.htm"


def test_ingest_guard_requires_append(tmp_path, mem_con) -> None:
    zip_path = make_zip(tmp_path, "submissions.zip", [submission_doc(1)])
    submissions.ingest(zip_path, mem_con)
    with pytest.raises(RuntimeError, match="--append"):
        submissions.ingest(zip_path, mem_con)
    # append=True is allowed
    stats = submissions.ingest(zip_path, mem_con, append=True)
    assert stats["entities"] == 1


def test_malformed_docs_are_skipped(tmp_path, mem_con) -> None:
    zip_path = make_zip(
        tmp_path,
        "submissions.zip",
        [{"no_cik": True}, submission_doc(2)],
    )
    stats = submissions.ingest(zip_path, mem_con)
    assert stats["entities"] == 1
