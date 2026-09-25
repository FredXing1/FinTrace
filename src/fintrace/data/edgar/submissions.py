"""Ingest SEC EDGAR ``submissions.zip`` (per-CIK submission history, as-filed).

Source: https://www.sec.gov/Archives/edgar/daily-index/xbrl/submissions.zip
The zip holds one JSON per CIK: entity metadata plus ``filings.recent`` (the most
recent ~1,000 filings). Older filings live in pagination chunks that P0 does not
need — XBRL facts come from companyfacts, not from here.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, cast

import duckdb
import pyarrow as pa

from fintrace.data.store import ensure_empty

SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/submissions.zip"
# Bulk zip currently returns 403; the per-CIK API serves the same schema on demand.
SUBMISSIONS_API = "https://data.sec.gov/submissions/CIK{:010d}.json"

_BATCH_CIKS = 200  # entities per flush


def _opt_str(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def parse_submission(
    doc: dict[str, Any],
) -> tuple[tuple[Any, ...], list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """One submissions JSON -> (entity row, former-name rows, filing rows)."""
    cik = int(doc["cik"])
    entity = (
        cik,
        _opt_str(doc.get("name")),
        list(doc.get("tickers") or []),
        list(doc.get("exchanges") or []),
        _opt_str(doc.get("sic")),
        _opt_str(doc.get("sicDescription")),
        _opt_str(doc.get("category")),
        _opt_str(doc.get("fiscalYearEnd")),
    )
    former = [
        (cik, f.get("name"), _opt_str(f.get("from")), _opt_str(f.get("to")))
        for f in doc.get("formerNames") or []
        if f.get("name")
    ]
    recent = (doc.get("filings") or {}).get("recent") or {}
    accns: list[str] = recent.get("accessionNumber") or []

    def col(key: str) -> list[str]:
        vals = recent.get(key) or []
        return [vals[i] if i < len(vals) else "" for i in range(len(accns))]

    fdates, rdates, forms, pdocs = (
        col("filingDate"),
        col("reportDate"),
        col("form"),
        col("primaryDocument"),
    )
    filings = [
        (
            cik,
            accn,
            _opt_str(fdates[i]),
            _opt_str(rdates[i]),
            forms[i] or None,
            _opt_str(pdocs[i]),
        )
        for i, accn in enumerate(accns)
    ]
    return entity, former, filings


def _flush_filings(con: duckdb.DuckDBPyConnection, buf: list[tuple[Any, ...]]) -> None:
    tbl = pa.Table.from_pydict(
        {
            "cik": pa.array([r[0] for r in buf], pa.int64()),
            "accession_number": pa.array([r[1] for r in buf], pa.string()),
            "filing_date": pa.array([r[2] for r in buf], pa.string()),
            "report_date": pa.array([r[3] for r in buf], pa.string()),
            "form": pa.array([r[4] for r in buf], pa.string()),
            "primary_document": pa.array([r[5] for r in buf], pa.string()),
        }
    )
    con.register("filings_batch", tbl)
    con.execute(
        """
        INSERT INTO filings
        SELECT cik, accession_number,
               TRY_CAST(filing_date AS DATE), TRY_CAST(report_date AS DATE),
               form, primary_document
        FROM filings_batch
        """
    )
    con.unregister("filings_batch")


def ingest_doc(doc: dict[str, Any], con: duckdb.DuckDBPyConnection) -> int:
    """Ingest one per-CIK submissions JSON (data.sec.gov API, same schema as the
    bulk-zip entries). Upserts the entity row, appends filings. Returns filing count."""
    entity, former, filings = parse_submission(doc)
    con.executemany(
        "INSERT OR REPLACE INTO entities "
        "(cik, name, tickers, exchanges, sic, sic_description, category, fiscal_year_end) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [entity],
    )
    if former:
        con.executemany("INSERT INTO former_names VALUES (?, ?, ?, ?)", former)
    if filings:
        _flush_filings(con, filings)
    return len(filings)


def ingest(
    zip_path: str | Path,
    con: duckdb.DuckDBPyConnection,
    *,
    limit: int | None = None,
    append: bool = False,
) -> dict[str, int]:
    """Ingest a submissions.zip into the store. ``limit`` caps entities (smoke runs)."""
    ensure_empty(con, "entities", append=append)
    n_entities = n_former = n_filings = 0
    entity_buf: list[tuple[Any, ...]] = []
    former_buf: list[tuple[Any, ...]] = []
    filing_buf: list[tuple[Any, ...]] = []

    def flush() -> None:
        nonlocal n_entities, n_former, n_filings
        if entity_buf:
            # OR REPLACE: entities has a PK on cik, and --append re-ingests must be idempotent.
            con.executemany(
                "INSERT OR REPLACE INTO entities "
                "(cik, name, tickers, exchanges, sic, sic_description, category, fiscal_year_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                entity_buf,
            )
            n_entities += len(entity_buf)
            entity_buf.clear()
        if former_buf:
            con.executemany("INSERT INTO former_names VALUES (?, ?, ?, ?)", former_buf)
            n_former += len(former_buf)
            former_buf.clear()
        if filing_buf:
            _flush_filings(con, filing_buf)
            n_filings += len(filing_buf)
            filing_buf.clear()

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not info.filename.endswith(".json"):
                continue
            if limit is not None and n_entities >= limit:
                break
            doc = cast("dict[str, Any]", json.loads(zf.read(info)))
            try:
                entity, former, filings = parse_submission(doc)
            except (KeyError, TypeError, ValueError):
                continue
            entity_buf.append(entity)
            former_buf.extend(former)
            filing_buf.extend(filings)
            if len(entity_buf) >= _BATCH_CIKS:
                flush()
    flush()
    return {"entities": n_entities, "former_names": n_former, "filings": n_filings}
