"""Ingest SEC's official ``company_tickers.json`` (ticker <-> CIK <-> name mapping).

Source: https://www.sec.gov/files/company_tickers.json (~800 KB, all listed filers).
This is the P0 replacement for the ``submissions.zip`` bulk file, which currently
returns HTTP 403: the ticker mapping is what the store actually needs for
entity resolution. Upserts are idempotent (``INSERT OR REPLACE`` on ``cik``).

Ingest tickers BEFORE per-CIK submissions fetches so those can enrich
sic/category fields without clobbering ticker rows (they REPLACE too, but carry
the ticker list themselves).
"""

from __future__ import annotations

from typing import Any

import duckdb

from fintrace.data.http import SecHttpClient

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def parse(doc: dict[str, Any]) -> dict[int, tuple[str | None, list[str]]]:
    """Flat listing entries -> {cik: (name, [tickers])}. Aggregates multiple
    listings (GOOGL/GOOG) of one CIK into one ticker list."""
    by_cik: dict[int, tuple[str | None, list[str]]] = {}
    for entry in doc.values():
        cik = int(entry["cik_str"])
        ticker = str(entry.get("ticker") or "").upper()
        if not ticker:
            continue
        name = entry.get("title")
        if cik in by_cik:
            prev_name, tickers = by_cik[cik]
            if ticker not in tickers:
                tickers.append(ticker)
            by_cik[cik] = (prev_name or name, tickers)
        else:
            by_cik[cik] = (name, [ticker])
    return by_cik


def ingest(doc: dict[str, Any], con: duckdb.DuckDBPyConnection) -> int:
    mapping = parse(doc)
    rows = [
        (cik, name, tickers, None, None, None, None, None)
        for cik, (name, tickers) in sorted(mapping.items())
    ]
    con.executemany(
        "INSERT OR REPLACE INTO entities "
        "(cik, name, tickers, exchanges, sic, sic_description, category, fiscal_year_end) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def download_and_ingest(client: SecHttpClient, con: duckdb.DuckDBPyConnection) -> int:
    doc = client.get_json(TICKERS_URL)
    return ingest(doc, con)
