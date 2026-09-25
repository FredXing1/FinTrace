"""Point-in-time (PIT) query primitives over the local DuckDB store.

Design rule: every method takes a REQUIRED ``as_of`` date — there is deliberately
no default, so no caller can accidentally read "today's" knowledge inside a
backtest (look-ahead bias). All filters anchor on SEC ``filed`` timestamps, never
on reporting-period alignment, and the XBRL ``frames`` API semantics (closest
period, silent look-ahead) are intentionally not replicated.
"""

from __future__ import annotations

from typing import Any

import duckdb

_FACT_COLS = "cik, taxonomy, tag, unit, period_start, period_end, val, accn, fy, fp, form, filed"

_FILING_COLS = "cik, accession_number, filing_date, report_date, form, primary_document"


def _cols(spec: str) -> list[str]:
    return [c.strip() for c in spec.split(",")]


class PitStore:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con

    def resolve_cik(self, ticker: str) -> int | None:
        row = self._con.execute(
            "SELECT cik FROM entities WHERE list_contains(tickers, ?) LIMIT 1",
            [ticker.upper()],
        ).fetchone()
        return int(row[0]) if row is not None else None

    def fact(
        self,
        cik: int,
        tag: str,
        *,
        period_end: str,
        as_of: str,
        taxonomy: str = "us-gaap",
        unit: str = "USD",
        period_start: str | None = None,
    ) -> dict[str, Any] | None:
        """Value of ``tag`` for one reporting period, as knowable at ``as_of``.

        Restatement-aware: returns the fact with the latest ``filed <= as_of``.
        Returns ``None`` when the value was not yet public at ``as_of`` — that is
        the correct answer for a PIT system, not an error.
        """
        sql = f"""
            SELECT {_FACT_COLS}
            FROM facts
            WHERE cik = ?
              AND taxonomy = ?
              AND tag = ?
              AND unit = ?
              AND period_end = CAST(? AS DATE)
              AND filed <= CAST(? AS DATE)
        """
        params: list[Any] = [cik, taxonomy, tag, unit, period_end, as_of]
        if period_start is not None:
            sql += " AND period_start = CAST(? AS DATE)"
            params.append(period_start)
        sql += " ORDER BY filed DESC, accn DESC LIMIT 1"
        row = self._con.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(zip(_cols(_FACT_COLS), row, strict=True))

    def history(
        self,
        cik: int,
        tag: str,
        *,
        as_of: str,
        taxonomy: str = "us-gaap",
        unit: str = "USD",
    ) -> list[dict[str, Any]]:
        """As-known-at series: one row per (period_start, period_end), each the
        latest version filed <= as_of, ordered by period_end."""
        rows = self._con.execute(
            f"""
            SELECT {_FACT_COLS}
            FROM facts
            WHERE cik = ? AND taxonomy = ? AND tag = ? AND unit = ?
              AND filed <= CAST(? AS DATE)
            QUALIFY row_number() OVER (
                PARTITION BY period_start, period_end
                ORDER BY filed DESC, accn DESC
            ) = 1
            ORDER BY period_end
            """,
            [cik, taxonomy, tag, unit, as_of],
        ).fetchall()
        return [dict(zip(_cols(_FACT_COLS), r, strict=True)) for r in rows]

    def filings(
        self,
        cik: int,
        *,
        as_of: str | None = None,
        forms: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Filing index rows (from submissions.zip), optionally PIT- and form-filtered."""
        sql = f"""
            SELECT {_FILING_COLS}
            FROM filings
            WHERE cik = ?
        """
        params: list[Any] = [cik]
        if forms:
            sql += f" AND form IN ({', '.join(['?'] * len(forms))})"
            params.extend(forms)
        if as_of is not None:
            sql += " AND filing_date <= CAST(? AS DATE)"
            params.append(as_of)
        sql += " ORDER BY filing_date DESC LIMIT ?"
        params.append(limit)
        rows = self._con.execute(sql, params).fetchall()
        return [dict(zip(_cols(_FILING_COLS), r, strict=True)) for r in rows]
