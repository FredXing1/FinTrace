#!/usr/bin/env python3
"""Prometheus-format exporter for the budget ledger (roadmap P3 monitoring).

Serves, in Prometheus text format:

- ``fintrace_spend_rmb_total``          lifetime LLM spend from the ledger
- ``fintrace_ledger_calls_total``       recorded LLM calls
- ``fintrace_spend_rmb{session=...}``   per-session spend
- ``fintrace_spend_cap_rmb``            configured hard cap

Zero dependencies: stdlib sqlite3 + http.server. The ledger path is the same
one the BudgetGovernor writes, so the exporter can run next to any workload
(or in the compose stack) without access to the working directory.

Usage: python scripts/metrics_exporter.py [--port 9091] [--ledger PATH]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fintrace.paths import ledger_path

_SQL_SESSIONS = (
    "SELECT session, SUM(cost_rmb), COUNT(*) FROM spend GROUP BY session ORDER BY session"
)
_SQL_TOTAL = "SELECT COALESCE(SUM(cost_rmb), 0), COUNT(*) FROM spend"


def render_metrics(ledger: Path, cap_rmb: float) -> str:
    lines: list[str] = []
    if not ledger.exists():
        return "# HELP fintrace_spend_rmb_total LLM spend (RMB) from the budget ledger.\n# TYPE fintrace_spend_rmb_total gauge\nfintrace_spend_rmb_total 0\n"

    con = sqlite3.connect(str(ledger))
    try:
        total, calls = con.execute(_SQL_TOTAL).fetchone()
        lines += [
            "# HELP fintrace_spend_rmb_total LLM spend (RMB) from the budget ledger.",
            "# TYPE fintrace_spend_rmb_total gauge",
            f"fintrace_spend_rmb_total {total:.4f}",
            "# HELP fintrace_ledger_calls_total Recorded LLM calls.",
            "# TYPE fintrace_ledger_calls_total counter",
            f"fintrace_ledger_calls_total {calls}",
            "# HELP fintrace_spend_rmb LLM spend (RMB) per session.",
            "# TYPE fintrace_spend_rmb gauge",
        ]
        for session, spend, _calls in con.execute(_SQL_SESSIONS):
            safe = session.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            lines.append(f'fintrace_spend_rmb{{session="{safe}"}} {spend:.4f}')
    finally:
        con.close()
    lines += [
        "# HELP fintrace_spend_cap_rmb Configured budget hard cap (RMB).",
        "# TYPE fintrace_spend_cap_rmb gauge",
        f"fintrace_spend_cap_rmb {cap_rmb}",
    ]
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    ledger: Path
    cap_rmb: float = 3000.0

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = render_metrics(self.ledger, self.cap_rmb).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence per-request noise
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9091)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument(
        "--cap-rmb",
        type=float,
        default=None,
        help="budget cap to expose (default: FINTRACE_BUDGET_CAP_RMB or 3000)",
    )
    args = parser.parse_args()
    Handler.ledger = args.ledger or ledger_path()
    Handler.cap_rmb = args.cap_rmb or float(os.environ.get("FINTRACE_BUDGET_CAP_RMB", "3000"))
    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"serving fintrace ledger metrics on :{args.port} (ledger: {Handler.ledger})")
    server.serve_forever()


if __name__ == "__main__":
    main()
