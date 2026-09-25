from __future__ import annotations

import pytest

from fintrace.core.budget import BudgetExceeded, BudgetGovernor, _price_for


def test_price_matching_by_suffix_and_alias() -> None:
    assert _price_for("deepseek-chat", {}) == (0.0, 0.0)  # unknown -> free + warning
    prices = {"deepseek": (2.1, 9.4), "qwen-plus": (0.8, 2.0)}
    assert _price_for("deepseek-reasoner", prices) == (2.1, 9.4)
    assert _price_for("qwen-plus-1220", prices) == (0.8, 2.0)


def test_authorize_blocks_when_estimate_exceeds_cap(tmp_path) -> None:
    gov = BudgetGovernor(
        cap_rmb=0.01,
        ledger=tmp_path / "ledger.sqlite",
        prices={"mock": (100.0, 100.0)},
    )
    with pytest.raises(BudgetExceeded, match="cap"):
        gov.authorize("mock", est_prompt_tokens=100_000, est_completion_tokens=1_000)


def test_record_accumulates_and_hard_stops(tmp_path) -> None:
    gov = BudgetGovernor(
        cap_rmb=1.5,
        ledger=tmp_path / "ledger.sqlite",
        prices={"mock": (1.0, 0.0)},
        warn_thresholds=(0.5,),
    )
    cost = gov.record("mock", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == pytest.approx(1.0)
    with pytest.raises(BudgetExceeded, match="exceeded"):
        gov.record("mock", prompt_tokens=1_000_000, completion_tokens=0)


def test_ledger_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite"
    gov1 = BudgetGovernor(cap_rmb=100, ledger=path, prices={"m": (1.0, 0.0)})
    gov1.record("m", prompt_tokens=1_000_000, completion_tokens=0)
    gov1.close()
    gov2 = BudgetGovernor(cap_rmb=100, ledger=path, prices={"m": (1.0, 0.0)})
    assert gov2.spent_rmb == pytest.approx(1.0)
    gov2.close()


def test_free_models_cost_zero(tmp_path) -> None:
    gov = BudgetGovernor(cap_rmb=1, ledger=tmp_path / "l.sqlite")
    assert gov.cost_of("glm-4.7-flash", 1_000_000, 1_000_000) == 0.0
    assert gov.cost_of("mock", 5, 5) == 0.0
