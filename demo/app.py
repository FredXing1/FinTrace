"""FinTrace demo: point-in-time lookup with a look-ahead "leak view".

Standalone Streamlit app for Hugging Face Spaces — queries a small DuckDB
subset of as-filed SEC XBRL facts (star companies) and needs no LLM API.
"""

from __future__ import annotations

import json

import duckdb
import streamlit as st

st.set_page_config(
    page_title="FinTrace — point-in-time financial facts", page_icon="⏳", layout="wide"
)


@st.cache_resource
def db():
    return duckdb.connect("demo.duckdb", read_only=True)


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


labels = [_label(r) for r in companies]
pick = st.selectbox("Company", labels)
cik, name, tickers = companies[labels.index(pick)]
symbol = tickers[0] if tickers else f"CIK {cik}"

tags = [
    r[0]
    for r in con.execute(
        "SELECT DISTINCT tag FROM facts WHERE cik = ? ORDER BY tag", [cik]
    ).fetchall()
]
tag = st.selectbox("XBRL tag", tags)

periods = [
    str(r[0])
    for r in con.execute(
        "SELECT DISTINCT period_end FROM facts WHERE cik = ? AND tag = ? ORDER BY period_end",
        [cik, tag],
    ).fetchall()
]
period_end = st.selectbox("Fiscal period ending", periods)

fmin, fmax = con.execute(
    "SELECT MIN(CAST(filed AS DATE)), MAX(CAST(filed AS DATE)) "
    "FROM facts WHERE cik = ? AND tag = ? AND period_end = ?",
    [cik, tag, period_end],
).fetchone()
as_of = st.slider(
    "Knowledge cutoff (as_of)",
    min_value=fmin,
    max_value=fmax,
    value=fmax,
    format="YYYY-MM-DD",
    help="Slide left to travel back in time: the answer must only use filings public at this date.",
)

gated = con.execute(
    "SELECT val, accn, MAX(CAST(filed AS DATE)) FROM facts "
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
with left:
    st.subheader("✅ Point-in-time answer (public at as_of)")
    if gated:
        st.metric(symbol, f"${gated[0]:,.0f}")
        st.write(f"evidence: accn `{gated[1]}` · filed `{gated[2]}`")
    else:
        st.error("unknown — this fact was not public at the as_of date.")
        if leak:
            days = (leak[2] - as_of).days
            st.write(f"(first filed `{leak[2]}`, {days} days after your cutoff)")

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
