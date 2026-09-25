from __future__ import annotations

from fintrace.data.edgar import companyfacts
from fintrace.data.pit import PitStore
from tests.conftest import apple_facts_doc


def test_ingest_doc_roundtrip(mem_con) -> None:
    n = companyfacts.ingest_doc(apple_facts_doc(), mem_con)
    assert n == 4
    store = PitStore(mem_con)
    # append=True semantics: a second pull just inserts again (harmless duplicates)
    companyfacts.ingest_doc(apple_facts_doc(), mem_con)
    fact = store.fact(320193, "Revenues", period_end="2022-09-24", as_of="2023-01-01")
    assert fact is not None and fact["val"] == 394328000000.0


def test_ingest_doc_respects_append_false(mem_con) -> None:
    companyfacts.ingest_doc(apple_facts_doc(), mem_con, append=True)
    with __import__("pytest").raises(RuntimeError, match="--append"):
        companyfacts.ingest_doc(apple_facts_doc(), mem_con, append=False)
