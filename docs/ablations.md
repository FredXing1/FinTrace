# Ablations: which layer actually prevents leakage?

The gated agent bundles three protection layers. The ablation matrix removes
them factorially on the frozen core-200, with a local open-weights backbone
(Qwen2.5-7B, temperature 0, zero API cost) so every difference is attributable
to the removed layer.

| arm | gate | prompt | loop | T1 | T2 | T3 | impossible-task leak |
|---|---|---|---|---|---|---|---|
| full | ✓ | ✓ | multi-step | 50% | 68.3% | 0% | **0/17** |
| gate-off (prompt only) | – | ✓ | multi-step | 40% | 73.3% | 37.5% | **6/17 (35.3%)** |
| prompt-off (gate only) | ✓ | – | multi-step | 25% | 50.0% | 15% | 1/17 (5.9%) |
| neither (naive pattern) | – | – | multi-step | 19% | 56.7% | 20% | 2/17 (11.8%) |
| no-tools | – | ✓ | single call | 17% | 35.0% | 0% | 0/17 |
| one-round | ✓ | ✓ | one tool round | 50% | 68.3% | 0% | 0/17 |

## Findings

1. **Prompt discipline alone does not prevent tool-borne leakage.** With the
   gate removed but the discipline prompt kept, the agent still leaked 35.3%
   of impossible tasks — it retrieved post-`T` values through the tool and
   reported them despite being told the cutoff. A prompt shapes framing; it
   does not change information access.
2. **Structural gating is the load-bearing layer.** Gate-only arms leak 6%
   (residual training memory); the full system leaks 0.
3. **Ungated access manufactures apparent forecasting skill** — gate-off
   scores 37.5% on forward estimation vs 0% under the full gate. The
   "forecast" is retrieval of the realized value.
4. **Loop depth is not a protection mechanism**: one-round reproduces full
   exactly on every family.

Absolute scores of the local 7B backbone are far below API-class models
(T1 50% vs 92%); ablation conclusions are within-model arm differences.
Reproduce locally:

```bash
FINTRACE_LLM_BASE_URL=http://localhost:11434/v1 \
FINTRACE_LLM_API_KEY=ollama FINTRACE_LLM_MODEL=qwen2.5:7b \
scripts/ablation-local.sh
```

Full discussion: [technical report §5.4](https://github.com/FredXing1/FinTrace/blob/main/reports/technical-report.md).
