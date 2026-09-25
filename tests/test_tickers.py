from __future__ import annotations

from fintrace.data.edgar import tickers


def test_parse_aggregates_multi_ticker_ciks() -> None:
    doc = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "2": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
        "3": {"cik_str": 1, "ticker": "", "title": "No ticker"},
    }
    mapping = tickers.parse(doc)
    assert set(mapping) == {320193, 1652044}  # empty-ticker entry dropped
    assert mapping[320193] == ("Apple Inc.", ["AAPL"])
    assert mapping[1652044] == ("Alphabet Inc.", ["GOOGL", "GOOG"])


def test_ingest_upserts_entities(mem_con) -> None:
    doc = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    assert tickers.ingest(doc, mem_con) == 1
    # idempotent re-ingest
    assert tickers.ingest(doc, mem_con) == 1
    row = mem_con.execute("SELECT name, tickers FROM entities WHERE cik = 320193").fetchone()
    assert row == ("Apple Inc.", ["AAPL"])
