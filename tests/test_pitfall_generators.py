from __future__ import annotations

import pytest

from fintrace.data.edgar import companyfacts
from fintrace.pitfall.generators import generate
from fintrace.pitfall.model import freeze_core, read_jsonl, sha256_of_tasks, write_jsonl
from tests.conftest import make_companyfacts_zip, two_year_apple_doc


@pytest.fixture()
def pit_con(tmp_path, mem_con):
    companyfacts.ingest(make_companyfacts_zip(tmp_path, [two_year_apple_doc()]), mem_con)
    return mem_con


def test_t1_positive_and_null_semantics(pit_con) -> None:
    tasks = generate(pit_con, seed=7, pool_t1=4, pool_t2=0, pool_t3=0)
    t1 = [t for t in tasks if t["family"] == "T1"]
    assert len(t1) == 2  # only two distinct keys exist in the fixture
    for t in t1:
        if t["subtype"] == "null":
            assert t["gold"] == {"kind": "unknown"}
        else:
            assert t["gold"]["kind"] == "value"
            # FY2022 has two filings; after the FY2023 10-K the restated value
            # (394,327,001,000) is the correct as-known-at answer.
            assert t["gold"]["value"] in (365817000000.0, 394328000000.0, 394327001000.0)
    ids = [t["task_id"] for t in tasks]
    assert len(ids) == len(set(ids))


def test_t1_null_really_has_no_prior_disclosure(pit_con) -> None:
    tasks = generate(pit_con, seed=7, pool_t1=4, pool_t2=0, pool_t3=0)
    for t in tasks:
        if t["subtype"] == "null":
            # as_of must precede the first 10-K filing of that key
            assert t["as_of"] < ("2021-10-29" if t["period_end"] == "2021-09-25" else "2022-10-28")


def test_t3_forward_pair_with_restatement_aware_gold(pit_con) -> None:
    tasks = generate(pit_con, seed=7, pool_t1=0, pool_t2=0, pool_t3=2)
    t3 = [t for t in tasks if t["family"] == "T3"]
    assert len(t3) == 1
    t = t3[0]
    assert t["gold"]["kind"] == "forward"
    # gold takes the latest filed version (FY2023 10-K restated the value)
    assert t["gold"]["value"] == 394327001000.0
    assert t["as_of"] < "2022-10-28"  # before the FY2022 10-K became public
    assert t["meta"]["gold_withheld_at_publish"] is True
    assert "fiscal year ending 2022-09-24" in t["question"]


def test_t2_true_false_statements(pit_con) -> None:
    tasks = generate(pit_con, seed=11, pool_t1=0, pool_t2=2, pool_t3=0)
    t2 = [t for t in tasks if t["family"] == "T2"]
    assert len(t2) == 2
    for t in t2:
        assert t["gold"]["kind"] in ("true", "false")
        assert "is this statement correct" in t["question"]
        if t["gold"]["kind"] == "false":
            assert t["gold"]["stated_value"] != t["gold"]["true_value"]


def test_generate_is_deterministic(pit_con) -> None:
    a = generate(pit_con, seed=7, pool_t1=2, pool_t2=1, pool_t3=1)
    b = generate(pit_con, seed=7, pool_t1=2, pool_t2=1, pool_t3=1)
    assert a == b


def test_freeze_core_and_jsonl_roundtrip(pit_con, tmp_path) -> None:
    pool = generate(pit_con, seed=3, pool_t1=3, pool_t2=2, pool_t3=1)
    core, manifest = freeze_core(pool, core_t1=1, core_t2=1, core_t3=1, seed=99)
    # T3 pairs consume keys: with a 2-key fixture the T1/T2 pools may be empty,
    # so freeze takes min(requested, available) per family.
    expected = {
        fam: min(n, sum(1 for t in pool if t["family"] == fam))
        for fam, n in (("T1", 1), ("T2", 1), ("T3", 1))
    }
    assert manifest["counts"]["core_by_family"] == expected
    assert manifest["counts"]["core"] == len(core) == sum(expected.values())
    assert manifest["core_sha256"] == sha256_of_tasks(core)

    path = write_jsonl(core, tmp_path / "core.jsonl")
    assert read_jsonl(path) == core

    _, manifest_again = freeze_core(pool, core_t1=1, core_t2=1, core_t3=1, seed=99)
    assert manifest_again["core_sha256"] == manifest["core_sha256"]
