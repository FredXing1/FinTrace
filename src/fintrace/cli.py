"""Command-line interface: download/ingest EDGAR bulk data, PIT queries, FTS crawling.

Examples:
    fintrace download submissions
    fintrace ingest submissions
    fintrace download companyfacts
    fintrace ingest companyfacts --limit 500      # smoke
    fintrace ingest companyfacts                  # full (run in background)
    fintrace query-fact --ticker AAPL --tag Revenues --period-end 2022-09-24 --as-of 2023-06-30
    fintrace agent "How did Apple's revenue trend?" --as-of 2023-06-30 --mock
    fintrace fts-search "artificial intelligence" --forms 10-K --startdt 2024-01-01 --max 200
    fintrace fts-fetch "risk factor" --forms 10-K --startdt 2024-01-01 --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fintrace.core.budget import BudgetGovernor
from fintrace.core.cache import ResponseCache
from fintrace.core.llm import LLMResponse, MockLLM, OpenAICompatLLM, ToolCall
from fintrace.core.runtime import Agent
from fintrace.core.tools import ToolBox, pit_tools, pit_tools_ungated
from fintrace.data.edgar import companyfacts, fts, submissions, tickers
from fintrace.data.http import SecHttpClient
from fintrace.data.pit import PitStore
from fintrace.data.store import connect
from fintrace.paths import raw_dir
from fintrace.verify.auditpack import build_auditpack, save_auditpack
from fintrace.verify.verify import verify

_BULK_TIMEOUT = 900.0  # big files over slow links


def _cmd_download(args: argparse.Namespace) -> int:
    dest = raw_dir()
    with SecHttpClient(rate_per_sec=2.0) as client:
        if args.what == "submissions":
            path = client.download(submissions.SUBMISSIONS_URL, dest / "submissions.zip")
        else:
            path = client.download(companyfacts.COMPANYFACTS_URL, dest / "companyfacts.zip")
    print(path)
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip) if args.zip else raw_dir() / f"{args.what}.zip"
    if not zip_path.exists():
        print(
            f"zip not found: {zip_path} — run `fintrace download {args.what}` first",
            file=sys.stderr,
        )
        return 2
    con = connect()
    try:
        if args.what == "submissions":
            stats = submissions.ingest(zip_path, con, limit=args.limit, append=args.append)
        else:
            stats = companyfacts.ingest(zip_path, con, limit=args.limit, append=args.append)
        print(json.dumps(stats))
        return 0
    finally:
        con.close()


def _cmd_ingest_tickers(args: argparse.Namespace) -> int:
    con = connect()
    try:
        with SecHttpClient() as client:
            n = tickers.download_and_ingest(client, con)
        print(json.dumps({"entities": n}))
        return 0
    finally:
        con.close()


def _cmd_fetch_facts(args: argparse.Namespace) -> int:
    con = connect()
    try:
        total = 0
        with SecHttpClient(timeout=_BULK_TIMEOUT, rate_per_sec=2.0) as client:
            for cik in args.cik:
                doc = client.get_json(companyfacts.COMPANYFACTS_API.format(cik))
                total += companyfacts.ingest_doc(doc, con)
                print(f"[fetch-facts] cik={cik} cumulative_facts={total}", file=sys.stderr)
        print(json.dumps({"facts": total}))
        return 0
    finally:
        con.close()


def _cmd_fetch_submission(args: argparse.Namespace) -> int:
    con = connect()
    try:
        total = 0
        with SecHttpClient(timeout=_BULK_TIMEOUT, rate_per_sec=2.0) as client:
            for cik in args.cik:
                doc = client.get_json(submissions.SUBMISSIONS_API.format(cik))
                total += submissions.ingest_doc(doc, con)
                print(f"[fetch-submission] cik={cik} filings={total}", file=sys.stderr)
        print(json.dumps({"filings": total}))
        return 0
    finally:
        con.close()


def _mock_llm(as_of: str) -> MockLLM:
    """Scripted offline demo: one real PIT tool call against the local store."""
    return MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_demo_1",
                        name="query_fact",
                        arguments={
                            "ticker": "AAPL",
                            "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                            "period_end": "2022-09-24",
                            "as_of": as_of,
                        },
                    )
                ],
            ),
            LLMResponse(
                content=(
                    "(mock demo) The PIT tool returned the as-filed fact — evidence "
                    "(accn + filed date) is in the trace JSON. Configure FINTRACE_LLM_* "
                    "and drop --mock for a real written analysis."
                ),
                tool_calls=[],
            ),
        ]
    )


def _cmd_agent(args: argparse.Namespace) -> int:
    con = connect()
    try:
        store = PitStore(con)
        llm: MockLLM | OpenAICompatLLM
        if args.mock:
            llm = _mock_llm(args.as_of)
            model = "mock"
        else:
            llm = OpenAICompatLLM(model=args.model)
            model = llm.model
        agent = Agent(
            llm,
            ToolBox(pit_tools(store)),
            model=model,
            governor=BudgetGovernor(session="cli-agent"),
            cache=ResponseCache(),
            max_steps=args.max_steps,
        )
        result = agent.run(args.question, as_of=args.as_of)
        verification = verify(result.answer, result.trace.to_dict()["steps"], args.as_of)
        pack = build_auditpack(
            args.question, args.as_of, result.answer, result.trace.to_dict(), verification
        )
        pack_path = save_auditpack(pack)
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "steps": result.steps,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cost_rmb": round(result.cost_rmb, 6),
                    "trace": result.trace_path,
                    "auditpack": str(pack_path),
                    "verification_summary": verification["summary"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        con.close()


def _cmd_audit(args: argparse.Namespace) -> int:
    """Rebuild the auditpack from a saved trace (answer = last non-empty LLM step)."""
    trace_path = Path(args.trace)
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    steps = list(data.get("steps", []))
    answer = None
    for step in reversed(steps):
        if step.get("type") == "llm" and step.get("content"):
            answer = str(step["content"])
            break
    as_of = str(data.get("as_of"))[:10]
    verification = verify(answer, steps, as_of)
    pack = build_auditpack(str(data.get("question", "")), as_of, answer, data, verification)
    pack_path = save_auditpack(pack, trace_path.parent)
    print(
        json.dumps(
            {"auditpack": str(pack_path), "summary": verification["summary"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_pitfall_generate(args: argparse.Namespace) -> int:
    from fintrace.pitfall.generators import generate
    from fintrace.pitfall.model import freeze_core, sha256_of_tasks, write_jsonl

    con = connect()
    try:
        pool = generate(
            con,
            seed=args.seed,
            pool_t1=args.pool_t1,
            pool_t2=args.pool_t2,
            pool_t3=args.pool_t3,
            filed_from=args.filed_from,
            filed_to=args.filed_to,
        )
        core, manifest = freeze_core(
            pool,
            core_t1=args.core_t1,
            core_t2=args.core_t2,
            core_t3=args.core_t3,
            seed=args.seed,
        )
        out = Path(args.out)
        write_jsonl(pool, out / "pool.jsonl")
        write_jsonl(core, out / "core.jsonl")
        manifest["pool_sha256"] = sha256_of_tasks(pool)
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    finally:
        con.close()


def _cmd_pitfall_run(args: argparse.Namespace) -> int:
    from fintrace.core.llm import MockLLM, OpenAICompatLLM
    from fintrace.pitfall.harness import run_tasks
    from fintrace.pitfall.model import read_jsonl

    tasks = read_jsonl(Path(args.tasks))
    if args.limit:
        tasks = tasks[: args.limit]
    if args.ungated:
        # leak audit mode: strip as-of framing from questions (tools/prompts
        # are swapped below) so the naive agent never sees the cutoff.
        from fintrace.pitfall.leak import ungated_question

        tasks = [{**t, "question": ungated_question(t)} for t in tasks]
    con = connect()
    try:
        llm: MockLLM | OpenAICompatLLM
        if args.mock:
            llm = MockLLM([])
            model = "mock"
        else:
            llm = OpenAICompatLLM(model=args.model)
            model = llm.model
        governor = BudgetGovernor(session="pitfall-run")
        tools = (
            pit_tools_ungated(PitStore(con)) if args.ungated else pit_tools(PitStore(con))
        )
        naive_prompt = (
            "You are a financial research assistant. Use the provided tools to "
            "answer. Cite accession numbers when you have them. Respond in the "
            "language of the question."
        )

        def run_fn(task: dict[str, Any]) -> str | None:
            agent = Agent(
                llm,
                ToolBox(tools),
                model=model,
                governor=governor,
                cache=ResponseCache(),
                max_steps=args.max_steps,
                system_prompt=naive_prompt if args.ungated else None,
            )
            try:
                return agent.run(task["question"], as_of=task["as_of"], save_trace=False).answer
            except RuntimeError as exc:
                # MockLLM with an empty queue: the pipeline still gets exercised
                # and every task scores as no-answer.
                if "MockLLM" in str(exc):
                    return None
                raise

        report = run_tasks(tasks, run_fn, ci_seed=args.seed)
    finally:
        con.close()
    summary = {k: v for k, v in report.items() if k != "results"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    return 0


def _cmd_pitfall_leak(args: argparse.Namespace) -> int:
    from fintrace.pitfall.leak import run_leak_audit
    from fintrace.pitfall.model import read_jsonl

    tasks = read_jsonl(Path(args.tasks))
    if args.limit:
        tasks = tasks[: args.limit]
    con = connect()
    try:
        llm: MockLLM | OpenAICompatLLM = (
            MockLLM([]) if args.mock else OpenAICompatLLM(model=args.model)
        )
        report = run_leak_audit(tasks, llm, PitStore(con))
    finally:
        con.close()
    if args.gated_report:
        gated = json.loads(Path(args.gated_report).read_text(encoding="utf-8"))
        report["gated_baseline_by_family"] = gated.get("by_family")
    summary = {k: v for k, v in report.items() if k != "results"}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    return 0


def _cmd_query_fact(args: argparse.Namespace) -> int:
    con = connect()
    try:
        store = PitStore(con)
        cik = args.cik
        if args.ticker:
            cik = store.resolve_cik(args.ticker)
            if cik is None:
                print(f"unknown ticker: {args.ticker}", file=sys.stderr)
                return 2
        result = store.fact(
            cik,
            args.tag,
            period_end=args.period_end,
            as_of=args.as_of,
            taxonomy=args.taxonomy,
            unit=args.unit,
            period_start=args.period_start,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        con.close()


def _print_hits(hits: list[dict[str, Any]]) -> None:
    for hit in hits:
        source = hit.get("_source") or {}
        compact = {
            "_id": fts.hit_id(hit),
            "file_date": source.get("file_date"),
            "file_type": source.get("file_type"),
            "display_names": source.get("display_names"),
        }
        print(json.dumps(compact, ensure_ascii=False))


def _cmd_fts_search(args: argparse.Namespace) -> int:
    with SecHttpClient(rate_per_sec=args.rate) as client:
        payload = fts.search(
            client,
            args.query,
            forms=args.forms,
            startdt=args.startdt,
            enddt=args.enddt,
            count=min(args.max, 100),
        )
    total = ((payload.get("hits") or {}).get("total") or {}).get("value")
    print(f"# total: {total}", file=sys.stderr)
    hits = (payload.get("hits") or {}).get("hits") or []
    _print_hits(hits[: args.max])
    return 0


def _cmd_fts_fetch(args: argparse.Namespace) -> int:
    with SecHttpClient(rate_per_sec=args.rate) as client:
        hits = fts.iter_hits(
            client,
            args.query,
            forms=args.forms,
            startdt=args.startdt,
            enddt=args.enddt,
            max_hits=args.limit,
        )
        paths = fts.fetch_documents(client, hits, Path(args.dest), limit=args.limit)
    for p in paths:
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fintrace",
        description="FinTrace: auditable point-in-time financial data primitives",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="download an EDGAR bulk zip into data/raw/")
    p.add_argument("what", choices=["submissions", "companyfacts"])
    p.set_defaults(func=_cmd_download)

    p = sub.add_parser("ingest", help="ingest an EDGAR bulk zip into the DuckDB store")
    p.add_argument("what", choices=["submissions", "companyfacts"])
    p.add_argument("--zip", help="path to zip (default: data/raw/<what>.zip)")
    p.add_argument("--limit", type=int, default=None, help="cap entities/files (smoke runs)")
    p.add_argument("--append", action="store_true", help="allow ingest into non-empty tables")
    p.set_defaults(func=_cmd_ingest)

    p = sub.add_parser(
        "ingest-tickers", help="ingest official company_tickers.json (ticker->CIK map)"
    )
    p.set_defaults(func=_cmd_ingest_tickers)

    p = sub.add_parser("fetch-facts", help="fetch+ingest per-CIK XBRL facts from data.sec.gov")
    p.add_argument("--cik", type=int, nargs="+", required=True)
    p.set_defaults(func=_cmd_fetch_facts)

    p = sub.add_parser("fetch-submission", help="fetch+ingest per-CIK submission history")
    p.add_argument("--cik", type=int, nargs="+", required=True)
    p.set_defaults(func=_cmd_fetch_submission)

    p = sub.add_parser("query-fact", help="PIT value of one XBRL tag as known at --as-of")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--cik", type=int)
    group.add_argument("--ticker")
    p.add_argument("--tag", required=True, help="XBRL tag, e.g. Revenues")
    p.add_argument("--period-end", required=True, help="YYYY-MM-DD")
    p.add_argument("--as-of", required=True, help="knowledge cutoff YYYY-MM-DD (mandatory)")
    p.add_argument("--period-start", default=None)
    p.add_argument("--taxonomy", default="us-gaap")
    p.add_argument("--unit", default="USD")
    p.set_defaults(func=_cmd_query_fact)

    p = sub.add_parser("agent", help="run the PIT research agent loop (fully traced)")
    p.add_argument("question")
    p.add_argument("--as-of", required=True, help="knowledge cutoff YYYY-MM-DD (mandatory)")
    p.add_argument("--mock", action="store_true", help="scripted offline demo, no LLM API")
    p.add_argument("--model", default=None, help="model name (default: FINTRACE_LLM_MODEL)")
    p.add_argument("--max-steps", type=int, default=8)
    p.set_defaults(func=_cmd_agent)

    p = sub.add_parser(
        "pitfall-generate",
        help="generate the PITfall pool and frozen core set from the local PIT store",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pool-t1", type=int, default=300)
    p.add_argument("--pool-t2", type=int, default=200)
    p.add_argument("--pool-t3", type=int, default=120)
    p.add_argument("--core-t1", type=int, default=100)
    p.add_argument("--core-t2", type=int, default=60)
    p.add_argument("--core-t3", type=int, default=40)
    p.add_argument("--filed-from", default="2016-01-01")
    p.add_argument("--filed-to", default="2024-12-31")
    p.add_argument("--out", default=str(raw_dir().parent / "pitfall"))
    p.set_defaults(func=_cmd_pitfall_generate)

    p = sub.add_parser("pitfall-run", help="run and score an agent on a PITfall task file")
    p.add_argument("--tasks", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--mock", action="store_true", help="MockLLM (no API): validates the harness only"
    )
    p.add_argument(
        "--ungated",
        action="store_true",
        help="leak-audit mode: naive tools (latest values, no time gate) + no PIT prompt",
    )
    p.add_argument("--model", default=None)
    p.add_argument("--max-steps", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None, help="write full report JSON here")
    p.set_defaults(func=_cmd_pitfall_run)

    p = sub.add_parser(
        "pitfall-leak", help="ungated baseline: same questions, bare model, no as-of framing"
    )
    p.add_argument("--tasks", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--gated-report", default=None, help="pitfall-run report to compare against")
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_pitfall_leak)

    p = sub.add_parser("audit", help="rebuild the auditpack from a saved trace")
    p.add_argument("trace", help="path to data/traces/<run_id>.json")
    p.set_defaults(func=_cmd_audit)

    for name, cmd in (("fts-search", _cmd_fts_search), ("fts-fetch", _cmd_fts_fetch)):
        p = sub.add_parser(name, help=cmd.__doc__ or name)
        p.add_argument("query")
        p.add_argument("--forms", nargs="*", help="e.g. 10-K 10-Q 8-K")
        p.add_argument("--startdt", help="YYYY-MM-DD (filing date window start)")
        p.add_argument("--enddt", help="YYYY-MM-DD (filing date window end)")
        p.add_argument("--rate", type=float, default=5.0, help="requests per second cap")
        if name == "fts-search":
            p.add_argument("--max", type=int, default=50, help="max hits to print")
        else:
            p.add_argument("--limit", type=int, default=5, help="max documents to download")
            p.add_argument("--dest", default=str(raw_dir() / "fts"), help="download directory")
        p.set_defaults(func=cmd)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
