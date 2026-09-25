"""DuckDB schema and connection for the local PIT store.

Everything lives in one DuckDB file under ``$FINTRACE_DATA_DIR`` (default ``./data``).
The store is a local build artifact: gitignored, never redistributed as-is
(redistribution of SEC public-domain bulk files happens via download scripts).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from fintrace.paths import db_path

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS entities (
        cik BIGINT PRIMARY KEY,
        name VARCHAR,
        tickers VARCHAR[],
        exchanges VARCHAR[],
        sic VARCHAR,
        sic_description VARCHAR,
        category VARCHAR,
        fiscal_year_end VARCHAR,
        ingested_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS former_names (
        cik BIGINT,
        name VARCHAR,
        from_date VARCHAR,
        to_date VARCHAR
    )
    """,
    # No PRIMARY KEY on filings/facts: tens of millions of rows, and an ART index
    # would cost GBs of RAM. Uniqueness is guaranteed by guarded ingestion instead.
    """
    CREATE TABLE IF NOT EXISTS filings (
        cik BIGINT,
        accession_number VARCHAR,
        filing_date DATE,
        report_date DATE,
        form VARCHAR,
        primary_document VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS facts (
        cik BIGINT,
        entity_name VARCHAR,
        taxonomy VARCHAR,
        tag VARCHAR,
        unit VARCHAR,
        period_start DATE,
        period_end DATE,
        val DOUBLE,
        accn VARCHAR,
        fy INTEGER,
        fp VARCHAR,
        form VARCHAR,
        filed DATE,
        frame VARCHAR
    )
    """,
)


def connect(path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    target = str(path) if path is not None else str(db_path())
    if target == ":memory:":
        con = duckdb.connect(":memory:")
    else:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(target)
    for stmt in SCHEMA_STATEMENTS:
        con.execute(stmt)
    return con


def row_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    if row is None:
        raise RuntimeError(f"no result for COUNT(*) on {table}")
    return int(row[0])


def ensure_empty(con: duckdb.DuckDBPyConnection, table: str, *, append: bool) -> None:
    """Refuse to double-ingest unless the caller explicitly appends."""
    if append:
        return
    if row_count(con, table) > 0:
        raise RuntimeError(
            f"table {table} is not empty; pass --append to add more data, "
            "or start from a fresh database"
        )
