"""Shared fixtures: in-memory DuckDB store and small EDGAR zip builders."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from fintrace.data.store import connect


@pytest.fixture()
def mem_con():
    con = connect(":memory:")
    yield con
    con.close()


def make_zip(tmp_path: Path, name: str, docs: list[dict[str, Any]]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for i, doc in enumerate(docs):
            zf.writestr(f"CIK{i:010d}.json", json.dumps(doc))
    return path


def apple_facts_doc() -> dict[str, Any]:
    """Crafted companyfacts JSON: two filings for the same FY2022 period (restatement
    pattern), a duration fact with period_start, and a non-USD unit fact."""
    return {
        "cik": 320193,
        "entityName": "APPLE INC",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            {
                                "start": "2021-09-26",
                                "end": "2022-09-24",
                                "val": 394328000000,
                                "accn": "0000320193-22-000108",
                                "fy": 2022,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2022-10-28",
                                "frame": "CY2022",
                            },
                            {
                                "start": "2021-09-26",
                                "end": "2022-09-24",
                                "val": 394327001000,
                                "accn": "0000320193-23-000106",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                            },
                            {
                                "start": "2023-01-01",
                                "end": "2023-09-30",
                                "val": 1000.0,
                                "accn": "0000320193-23-000105",
                                "fy": 2023,
                                "fp": "Q3",
                                "form": "10-Q",
                                "filed": "2023-11-02",
                            },
                        ]
                    },
                }
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2023-10-20",
                                "val": 15550061000,
                                "accn": "0000320193-23-000106",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                            }
                        ]
                    }
                }
            },
        },
    }


def make_companyfacts_zip(tmp_path: Path, docs: list[dict[str, Any]]) -> Path:
    return make_zip(tmp_path, "companyfacts.zip", docs)


def two_year_apple_doc() -> dict[str, Any]:
    """apple_facts_doc + an FY2021 annual fact (with start), giving a consecutive
    two-year pair for T3 forward-task tests."""
    doc = apple_facts_doc()
    revenues = doc["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    revenues.insert(
        0,
        {
            "start": "2020-09-27",
            "end": "2021-09-25",
            "val": 365817000000,
            "accn": "0000320193-21-000105",
            "fy": 2021,
            "fp": "FY",
            "form": "10-K",
            "filed": "2021-10-29",
            "frame": "CY2021",
        },
    )
    return doc


def submission_doc(cik: int, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "cik": cik,
        "name": f"TEST CORP {cik}",
        "tickers": [f"T{cik}"],
        "exchanges": ["Nasdaq"],
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "category": "Large accelerated filer",
        "fiscalYearEnd": "0930",
        "formerNames": [{"name": "OLD NAME", "from": "1997", "to": "2007"}],
        "filings": {
            "recent": {
                "accessionNumber": [f"{cik:010d}-23-000106"],
                "filingDate": ["2023-11-03"],
                "reportDate": ["2023-09-30"],
                "form": ["10-K"],
                "primaryDocument": ["test-20230930.htm"],
            }
        },
    }
    doc.update(overrides)
    return doc


def noop(_: int) -> None:
    """A sleep stub typed for RateLimiter injection (callable from tests)."""


Clock = Callable[[], float]
