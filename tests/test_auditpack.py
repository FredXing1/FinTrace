from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from fintrace.verify.auditpack import build_auditpack, load_schema, save_auditpack
from fintrace.verify.verify import verify


def _trace_dict() -> dict[str, Any]:
    return {
        "run_id": "abc123def456",
        "question": "What was Apple's FY2022 revenue?",
        "as_of": "2023-01-01",
        "started_at": "2026-09-25T10:00:00+0800",
        "finished_at": "2026-09-25T10:00:05+0800",
        "steps": [
            {
                "step": 1,
                "type": "llm",
                "model": "mock",
                "cache_hit": False,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "tool_calls": [],
                "content": "Revenue was $394.3 billion.",
            },
            {
                "step": 1,
                "type": "tool",
                "name": "query_fact",
                "arguments": {"ticker": "AAPL", "tag": "Revenues"},
                "result": {
                    "ok": True,
                    "result": {
                        "cik": 320193,
                        "entity_name": "APPLE INC",
                        "taxonomy": "us-gaap",
                        "tag": "Revenues",
                        "unit": "USD",
                        "period_start": None,
                        "period_end": "2022-09-24",
                        "val": 394328000000.0,
                        "accn": "0000320193-22-000108",
                        "fy": 2022,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2022-10-28",
                        "frame": None,
                    },
                },
            },
        ],
    }


@pytest.fixture()
def pack() -> dict[str, Any]:
    trace = _trace_dict()
    report = verify("Revenue was $394.3 billion.", trace["steps"], "2023-01-01")
    return build_auditpack(
        trace["question"], "2023-01-01", "Revenue was $394.3 billion.", trace, report
    )


def test_validates_against_bundled_schema(pack: dict[str, Any]) -> None:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(pack)


def test_signoff_defaults_unsigned(pack: dict[str, Any]) -> None:
    assert pack["human_signoff"]["approved"] is False
    assert pack["human_signoff"]["reviewer"] is None


def test_supported_claim_carries_evidence(pack: dict[str, Any]) -> None:
    supported = [c for c in pack["verification"]["claims"] if c["verdict"] == "supported"]
    assert len(supported) == 1
    assert supported[0]["evidence"]["accn"] == "0000320193-22-000108"
    assert str(supported[0]["evidence"]["filed"]) <= pack["as_of"]


def test_save_writes_json(tmp_path, pack: dict[str, Any]) -> None:
    path = save_auditpack(pack, tmp_path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == pack["run_id"]
    Draft202012Validator(load_schema()).validate(loaded)
