# auditpack: the audit-trail schema

An **auditpack** is the exportable unit of accountability: what the agent
concluded, which evidence supports it, how the run executed, and who signed
off. It is a plain JSON document validated by an open JSON Schema (draft
2020-12), shipped with the package at
`src/fintrace/schemas/auditpack-v0.1.json`.

## What is inside

- **conclusion** — the agent's final answer;
- **claim verdicts** — every numeric claim extracted from the answer, bound
  to evidence at 0.5% relative tolerance, classified
  `supported` / `unsupported` / `leaked` (evidence published after the
  as-of date is *leaked*, independent of tool gating — defense in depth);
- **arithmetic recomputation** — growth percentages recomputed from the two
  most recent distinct periods in the evidence;
- **execution log** — every LLM and tool call with token/cost accounting;
- **human sign-off** — reviewer identity, decision, timestamp.

## Build one

```bash
uv run fintrace agent "How did Apple's revenue trend?" --as-of 2023-06-30
uv run fintrace audit data/traces/<run_id>.json     # rebuild the auditpack
```

The verification layer works on any trace, so a pack can be reconstructed —
or challenged — after the fact. Intended consumers: compliance reviewers,
backtest authors, and evaluation harnesses that want claim-level provenance
instead of a single accuracy number.
