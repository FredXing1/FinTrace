"""Ablation arms for the PITfall harness (budget plan module C, ¥0 local runs).

Each arm removes exactly one protection layer from the full gated agent, so
their marginal contributions can be measured on the same frozen core-200:

- ``full``        gated tools + PIT discipline prompt + multi-step loop
- ``prompt-off``  gated tools, NEUTRAL prompt   -> what the structural gate alone catches
- ``gate-off``    ungated tools, PIT prompt     -> what prompt discipline alone catches
- ``neither``     ungated tools, neutral prompt -> the naive open-source pattern
- ``no-tools``    no tools at all, PIT prompt   -> framing/discipline without data access
- ``single-shot`` gated tools, one LLM call      -> removes the multi-step ReAct loop

Every arm is scored with the T1-null leakage audit (answers matching the
realized future value on tasks whose gold was not public at as_of), so arms
compare on the RQ1 headline metric, not just accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass

# The naive-agent system prompt shared by leak-style arms; deliberately free of
# any point-in-time language (the counterpart of runtime.SYSTEM_PROMPT).
NEUTRAL_PROMPT = (
    "You are a financial research assistant. Use the provided tools to "
    "answer. Cite accession numbers when you have them. Respond in the "
    "language of the question."
)


@dataclass(frozen=True)
class ArmConfig:
    name: str
    tools: str  # "gated" | "ungated" | "none"
    prompt: str  # "pit" | "neutral"
    max_steps: int | None  # None -> keep the CLI default
    description: str


ARMS: dict[str, ArmConfig] = {
    "full": ArmConfig(
        "full", "gated", "pit", None, "gated tools + PIT prompt + multi-step loop"
    ),
    "prompt-off": ArmConfig(
        "prompt-off",
        "gated",
        "neutral",
        None,
        "gated tools, neutral prompt: structural gate alone",
    ),
    "gate-off": ArmConfig(
        "gate-off", "ungated", "pit", None, "PIT prompt only, tools return latest values"
    ),
    "neither": ArmConfig(
        "neither",
        "ungated",
        "neutral",
        None,
        "ungated tools + neutral prompt: the naive agent pattern",
    ),
    "no-tools": ArmConfig(
        "no-tools", "none", "pit", 1, "PIT framing and discipline, no data access"
    ),
    "single-shot": ArmConfig(
        "single-shot",
        "gated",
        "pit",
        1,
        "gated tools, one LLM call: no multi-step loop",
    ),
}
