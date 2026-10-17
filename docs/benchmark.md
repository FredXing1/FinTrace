# The PITfall benchmark

PITfall is generated deterministically (seeded, sha256-frozen) from SEC EDGAR
as-filed facts — pool of 579 tasks, frozen core-200 evaluation subset. Its
defining feature is the **unknown-gold probe**: tasks whose true answer was
*not public* at the reference date, constructed by setting `as_of` one day
before first disclosure and verified by a set-based join across *all* filing
forms (8-K pre-announcements filtered out). On these tasks the only correct
answer is "unknown at as_of", and any specific value matching the realized
future is provable look-ahead leakage.

## Task families

| family | question shape | gold | metric |
|---|---|---|---|
| T1 time-gated QA | "as of T, what was X's metric for period P?" | latest `filed ≤ T` value, or `unknown` | 1% relative tolerance |
| T2 claim verification | "is this statement correct?" (true / perturbed) | verdict + evidence accn | verdict match + citation |
| T3 forward estimation | "as of T, estimate next-year X" | realized value, first-filed after T | APE ≤ 20% |

T3 windows anchor on *first-filed* dates — last-filed is polluted by
comparative-period restatements, which would invert the window. T3 gold
values are withheld from the public dataset export
([HF dataset](https://huggingface.co/datasets/Fredxing/pitfall), or
`fintrace pitfall-export` to build it locally); the generator reproduces
everything from public EDGAR data.

## Leakage controls in the generator

- impossible-task construction: zero prior facts of any form before `as_of`;
- restatement-aware gold (`filed ≤ T`, accession tiebreaker);
- 8-K pre-announcement filtering;
- deterministic, seeded generation — the frozen core-200 manifest carries the
  sha256 so anyone can verify they are scoring the same tasks.

## The three-configuration audit

| configuration | impossible tasks answered with the true future value |
|---|---|
| bare model (no tools, no as-of framing) | 2/17 (11.8%) — identical across deepseek-chat and GLM-4.7 |
| naive agent (live-data tools, no gate) | **14/17 (82%)** |
| gated FinTrace agent | **0/17** (16/17 correctly "unknown") |

Scoring is deterministic (pattern/numeric matching, no LLM judge); every
reported number carries a bootstrap 95% CI and a per-task cost/latency
accounting. Reproduce: `fintrace pitfall-generate` → `pitfall-run` →
`pitfall-leak`, or walk the evaluation forward through history with
`fintrace pitfall-walkforward`.
