"""FinTrace demo: point-in-time lookup with a look-ahead "leak view".

Standalone Streamlit app for Hugging Face Spaces — queries a small DuckDB
subset of as-filed SEC XBRL facts (star companies) and needs no LLM API.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import streamlit as st

st.set_page_config(
    page_title="FinTrace — point-in-time financial facts", page_icon="⏳", layout="wide"
)


@st.cache_resource
def db():
    # Streamlit Cloud runs from the repo root; keep the path relative to it.
    return duckdb.connect("demo/demo.duckdb", read_only=True)


con = db()

st.title("⏳ FinTrace: point-in-time financial facts")
st.caption(
    "Pick a company, a metric, and a knowledge cutoff — the left card answers "
    "with what was actually PUBLIC at that date, the right card shows what a "
    "naive live-data API would hand back today. Data: SEC EDGAR as-filed "
    "XBRL. Research demo — not investment advice."
)

companies = con.execute(
    "SELECT cik, name, tickers FROM entities WHERE tickers IS NOT NULL ORDER BY name"
).fetchall()


def _label(row):
    cik, name, tickers = row
    sym = tickers[0] if tickers else f"CIK {cik}"
    return f"{name} ({sym})"


# Deep links: /?company=apple&tag=RevenueFromContract...&period=2022-09-24&asof=2023-01-01
qp = st.query_params
q_company, q_tag = qp.get("company"), qp.get("tag")
q_period, q_asof = qp.get("period"), qp.get("asof")


def _index_of(options: list[str], wanted: str | None) -> int:
    if not wanted:
        return 0
    for i, option in enumerate(options):
        if wanted.lower() in option.lower():
            return i
    return 0


labels = [_label(r) for r in companies]
pick = st.selectbox("Company", labels, index=_index_of(labels, q_company))
cik, name, tickers = companies[labels.index(pick)]
symbol = tickers[0] if tickers else f"CIK {cik}"

tags = [
    r[0]
    for r in con.execute(
        "SELECT DISTINCT tag FROM facts WHERE cik = ? ORDER BY tag", [cik]
    ).fetchall()
]
tag = st.selectbox("XBRL tag", tags, index=_index_of(tags, q_tag))

periods = [
    str(r[0])
    for r in con.execute(
        "SELECT DISTINCT period_end FROM facts WHERE cik = ? AND tag = ? ORDER BY period_end",
        [cik, tag],
    ).fetchall()
]
period_end = st.selectbox(
    "Fiscal period ending", periods, index=_index_of(periods, q_period)
)
period_end_date = date.fromisoformat(period_end)

fmin, fmax = con.execute(
    "SELECT MIN(CAST(filed AS DATE)), MAX(CAST(filed AS DATE)) "
    "FROM facts WHERE cik = ? AND tag = ? AND period_end = ?",
    [cik, tag, period_end],
).fetchone()
if fmin is None or fmax is None:
    st.info("No filings on record for this selection.")
    st.stop()

# Slider spans [period end, latest filing + 1d]: its left half covers the
# window where the fact existed as a question but was NOT yet public — the
# unknown zone is the point, so the user must be able to slide into it.
slider_min = period_end_date
slider_max = max(fmax, period_end_date) + timedelta(days=1)
as_of_default = slider_max
if q_asof:
    try:
        parsed = date.fromisoformat(q_asof)
        as_of_default = min(max(parsed, slider_min), slider_max)
    except ValueError:
        pass
as_of = st.slider(
    "Knowledge cutoff (as_of)",
    min_value=slider_min,
    max_value=slider_max,
    value=as_of_default,
    format="YYYY-MM-DD",
    key=f"asof-{cik}-{tag}-{period_end}",
    help="Slide left to travel back in time: the answer must only use filings public at this date.",
)

gated = con.execute(
    "SELECT val, accn, filed FROM facts "
    "WHERE cik = ? AND tag = ? AND period_end = ? AND CAST(filed AS DATE) <= ? "
    "ORDER BY filed DESC LIMIT 1",
    [cik, tag, period_end, as_of],
).fetchone()
leak = con.execute(
    "SELECT val, accn, filed FROM facts "
    "WHERE cik = ? AND tag = ? AND period_end = ? ORDER BY filed DESC LIMIT 1",
    [cik, tag, period_end],
).fetchone()

left, right = st.columns(2, gap="large")
first_public = min(
    (date.fromisoformat(str(d)) for (d,) in con.execute(
        "SELECT DISTINCT CAST(filed AS DATE) FROM facts "
        "WHERE cik = ? AND tag = ? AND period_end = ? AND filed IS NOT NULL",
        [cik, tag, period_end],
    ).fetchall()),
    default=None,
)
with left:
    st.subheader("✅ Point-in-time answer (public at as_of)")
    if gated:
        st.metric(symbol, f"${gated[0]:,.0f}")
        st.write(f"evidence: accn `{gated[1]}` · filed `{gated[2]}`")
    else:
        st.error("unknown — this fact was not public at the as_of date.")
        if first_public:
            days = (first_public - as_of).days
            st.write(f"(first became public on {first_public}, {days} days after your cutoff)")

with right:
    st.subheader("🔓 What a naive live-data API returns today")
    if leak:
        st.metric(symbol, f"${leak[0]:,.0f}")
        st.write(f"evidence: accn `{leak[1]}` · filed `{leak[2]}`")
        if gated is None or str(leak[2]) > str(as_of):
            st.warning(
                "⚠️ Look-ahead: this version was NOT public at the as_of date. "
                "Scoring it in a backtest is leakage."
            )
        else:
            st.success("Same as the gated answer — no leakage at this cutoff.")

st.divider()
pack = {
    "question": f"{symbol} {tag} for period ending {period_end}",
    "as_of": str(as_of),
    "point_in_time_answer": {
        "value": gated[0],
        "accn": gated[1],
        "filed": str(gated[2]),
    }
    if gated
    else {"answer": "unknown"},
    "latest_known": {
        "value": leak[0],
        "accn": leak[1],
        "filed": str(leak[2]),
    }
    if leak
    else None,
}
st.download_button(
    "⬇️ Download mini auditpack (JSON)",
    json.dumps(pack, indent=2),
    file_name="auditpack.json",
    mime="application/json",
)
