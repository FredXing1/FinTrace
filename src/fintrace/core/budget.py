"""BudgetGovernor (budget plan docs/03 §5).

Pre-flight cost estimation before every LLM call, a persistent SQLite spend
ledger, threshold warnings, and a hard cap (default ¥3,000 per docs/03) that
stops the run. Prices are RMB per 1M tokens; models are matched by longest
suffix so snapshot names like ``qwen-plus-1220`` or ``deepseek-chat`` resolve
without enumerating every alias.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from fintrace.paths import ledger_path

# RMB per 1M tokens (input, output) — anchors from docs/03 §4, peak pricing.
# "flash" covers the free tiers of the GLM/Qwen flash series by substring match.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek": (2.10, 9.40),
    "qwen-plus": (0.80, 2.00),
    "qwen-flash": (0.30, 0.60),
    "qwen-turbo": (0.30, 0.60),
    "flash": (0.00, 0.00),
    "glm": (2.00, 8.00),
    "doubao": (0.80, 2.00),
    "kimi": (4.00, 12.00),
    "mock": (0.00, 0.00),
}


class BudgetExceeded(RuntimeError):
    """Raised when a call (or its estimate) would push lifetime spend over the cap."""


def _price_for(model: str, prices: dict[str, tuple[float, float]]) -> tuple[float, float]:
    model = model.lower()
    best: tuple[float, float] | None = None
    best_len = -1
    for name, price in prices.items():
        if (model.endswith(name) or name in model) and len(name) > best_len:
            best, best_len = price, len(name)
    if best is None:
        print(
            f"[budget] WARNING: no price entry for model {model!r}; assuming free. "
            "Add it to BudgetGovernor prices to track real spend.",
            file=sys.stderr,
        )
        best = (0.0, 0.0)
    return best


class BudgetGovernor:
    def __init__(
        self,
        cap_rmb: float | None = None,
        *,
        session: str = "default",
        ledger: Path | str | None = None,
        prices: dict[str, tuple[float, float]] | None = None,
        warn_thresholds: tuple[float, ...] = (0.60, 0.85),
    ) -> None:
        if cap_rmb is None:
            cap_rmb = float(os.environ.get("FINTRACE_BUDGET_CAP_RMB", "3000"))
        self.cap_rmb = cap_rmb
        self.session = session
        self.prices = prices if prices is not None else dict(DEFAULT_PRICES)
        self.warn_thresholds = warn_thresholds
        self._warned: set[float] = set()
        target = Path(ledger) if ledger is not None else ledger_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(target))
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS spend ("
            "ts TEXT DEFAULT CURRENT_TIMESTAMP, session TEXT, model TEXT, "
            "prompt_tokens INTEGER, completion_tokens INTEGER, cost_rmb REAL)"
        )
        self._con.commit()
        self.spent_rmb = float(
            self._con.execute("SELECT COALESCE(SUM(cost_rmb), 0) FROM spend").fetchone()[0]
        )

    def cost_of(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pin, pout = _price_for(model, self.prices)
        return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000

    def authorize(self, model: str, est_prompt_tokens: int, est_completion_tokens: int) -> float:
        """Pre-flight check: raise BudgetExceeded if the estimate would breach the cap."""
        est = self.cost_of(model, est_prompt_tokens, est_completion_tokens)
        if self.spent_rmb + est > self.cap_rmb:
            raise BudgetExceeded(
                f"budget cap ¥{self.cap_rmb:.2f} would be exceeded: "
                f"spent ¥{self.spent_rmb:.4f} + est ¥{est:.4f}"
            )
        return est

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Record actual usage; returns the cost. Hard-stops mid-run on breach."""
        cost = self.cost_of(model, prompt_tokens, completion_tokens)
        self._con.execute(
            "INSERT INTO spend (session, model, prompt_tokens, completion_tokens, cost_rmb) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.session, model, int(prompt_tokens), int(completion_tokens), cost),
        )
        self._con.commit()
        self.spent_rmb += cost
        for threshold in self.warn_thresholds:
            if self.spent_rmb >= self.cap_rmb * threshold and threshold not in self._warned:
                self._warned.add(threshold)
                print(
                    f"[budget] {int(threshold * 100)}% of cap used: "
                    f"¥{self.spent_rmb:.2f} / ¥{self.cap_rmb:.2f}",
                    file=sys.stderr,
                )
        if self.spent_rmb > self.cap_rmb:
            raise BudgetExceeded(
                f"budget cap ¥{self.cap_rmb:.2f} exceeded: spent ¥{self.spent_rmb:.4f}"
            )
        return cost

    def close(self) -> None:
        self._con.close()


def rough_token_estimate(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> int:
    """Cheap char-based estimator (~3 chars/token) for pre-flight checks only."""
    blob = str(messages) + (str(tools) if tools else "")
    return len(blob) // 3
