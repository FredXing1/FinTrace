from __future__ import annotations

from typing import Any

import pytest

from fintrace.verify.verify import collect_evidence, verify


def _fact_step(
    val: float,
    filed: str,
    accn: str = "0000320193-22-000108",
    period_end: str = "2022-09-24",
    tag: str = "Revenues",
) -> dict[str, Any]:
    return {
        "type": "tool",
        "name": "query_fact",
        "result": {
            "ok": True,
            "result": {
                "cik": 320193,
                "entity_name": "APPLE INC",
                "taxonomy": "us-gaap",
                "tag": tag,
                "unit": "USD",
                "period_start": None,
                "period_end": period_end,
                "val": val,
                "accn": accn,
                "fy": 2022,
                "fp": "FY",
                "form": "10-K",
                "filed": filed,
                "frame": None,
            },
        },
    }


def test_supported_and_unsupported() -> None:
    steps = [_fact_step(394328000000.0, "2022-10-28")]
    report = verify("Revenue was $394.3 billion; headcount was 999.", steps, "2023-01-01")
    verdicts = {v["verdict"] for v in report["claims"]}
    assert "supported" in verdicts and "unsupported" in verdicts
    assert report["summary"]["supported"] == 1
    assert report["summary"]["time_gated_ok"] is True


def test_leak_detected_when_evidence_postdates_as_of() -> None:
    steps = [_fact_step(394328000000.0, "2023-06-30")]
    report = verify("Revenue was $394.3 billion.", steps, "2023-01-01")
    assert report["summary"]["leaked"] == 1
    assert report["summary"]["time_gated_ok"] is False


def test_collect_evidence_dedupes() -> None:
    steps = [_fact_step(100.0, "2022-10-28"), _fact_step(100.0, "2022-10-28")]
    assert len(collect_evidence(steps)) == 1


def test_growth_recomputed_from_evidence() -> None:
    steps = [
        _fact_step(365817000000.0, "2021-10-29", accn="fy21", period_end="2021-09-25"),
        _fact_step(394328000000.0, "2022-10-28", accn="fy22", period_end="2022-09-24"),
    ]
    report = verify(
        "Revenue rose to $394.328 billion, up by 7.8% year over year.", steps, "2023-01-01"
    )
    check = report["arithmetic"][0]
    assert check["status"] == "checked" and check["ok"] is True
    assert check["expected_pct"] == pytest.approx(7.7938, abs=0.001)


def test_wrong_growth_fails() -> None:
    steps = [
        _fact_step(365817000000.0, "2021-10-29", accn="fy21", period_end="2021-09-25"),
        _fact_step(394328000000.0, "2022-10-28", accn="fy22", period_end="2022-09-24"),
    ]
    report = verify(
        "Revenue rose to $394.328 billion, up by 21.0% year over year.", steps, "2023-01-01"
    )
    check = report["arithmetic"][0]
    assert check["ok"] is False
    assert report["summary"]["arithmetic_ok"] is False


def test_percent_without_pair_is_not_checkable() -> None:
    steps = [_fact_step(394328000000.0, "2022-10-28")]
    report = verify("Revenue was $394.3 billion, up by 7.8%.", steps, "2023-01-01")
    assert report["arithmetic"][0]["status"] == "not_checkable"
