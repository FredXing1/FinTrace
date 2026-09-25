from __future__ import annotations

from fintrace.data.edgar import companyfacts
from tests.conftest import apple_facts_doc, make_companyfacts_zip


def test_ingest_counts_and_units(tmp_path, mem_con) -> None:
    zip_path = make_companyfacts_zip(tmp_path, [apple_facts_doc()])
    stats = companyfacts.ingest(zip_path, mem_con)
    assert stats == {"files": 1, "facts": 4}  # 3 USD facts + 1 shares fact

    rows = mem_con.execute(
        "SELECT taxonomy, tag, unit, period_start, period_end, val, filed "
        "FROM facts WHERE cik = 320193 ORDER BY filed"
    ).fetchall()
    assert len(rows) == 4
    usd = [r for r in rows if r[2] == "USD"]
    assert len(usd) == 3
    # duration facts keep period_start; instant facts have NULL period_start.
    # FY2022 (start 2021-09-26) and the 2023 nine-month period both have one.
    duration = [r for r in usd if r[3] is not None]
    assert {str(r[3]) for r in duration} == {"2021-09-26", "2023-01-01"}


def test_bad_rows_skipped(tmp_path, mem_con) -> None:
    doc = {
        "cik": 1,
        "entityName": "X",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "", "val": 5, "filed": "2020-01-01"},  # no period_end
                            {"end": "2020-12-31", "val": "not-a-number", "filed": "2020-01-01"},
                            {"end": "2020-12-31", "val": 42, "filed": "2020-01-01"},
                        ]
                    }
                }
            }
        },
    }
    zip_path = make_companyfacts_zip(tmp_path, [doc])
    stats = companyfacts.ingest(zip_path, mem_con)
    assert stats["facts"] == 1
