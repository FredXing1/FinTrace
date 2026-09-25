"""PITfall task generators, sampling from the local PIT store.

Leakage-control rules baked into generation:
- Candidate keys come from as-filed 10-K facts only.
- T1 "null" tasks set as_of BEFORE the first disclosure of ANY form (verified
  by a set-based join over the whole facts table, so 8-K pre-announcements are
  caught); gold is "unknown" and candidates with any earlier fact are dropped.
- T3 forward tasks require the gold fact to be absent at as_of (verified the
  same way) and take their label from the latest filing ever recorded.
- Set-based (temp-table join) evidence assembly — no per-candidate scans over
  the 125M-row facts table.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from fintrace.pitfall.model import task_to_dict

METRIC_NAMES: dict[str, str] = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue",
    "NetIncomeLoss": "net income",
    "OperatingIncomeLoss": "operating income",
    "Assets": "total assets",
    "Liabilities": "total liabilities",
    "StockholdersEquity": "stockholders' equity",
    "CashAndCashEquivalentsAtCarryingValue": "cash and cash equivalents",
    "ResearchAndDevelopmentExpense": "research and development expense",
    "CostOfRevenue": "cost of revenue",
}

_TAGS = list(METRIC_NAMES)
_GOLD_AS_OF = "2200-01-01"  # far-future cutoff to fetch "value as known today"


def _day(value: Any) -> str | None:
    return str(value)[:10] if value is not None else None


def _sample_keys(
    con: Any, *, tags: list[str], filed_from: str, filed_to: str, limit: int
) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" * len(tags))
    rows = con.execute(
        f"""
        SELECT cik, tag, period_start, period_end,
               MIN(CAST(filed AS DATE)) AS first_filed,
               MAX(CAST(filed AS DATE)) AS last_filed,
               ARG_MAX(entity_name, CAST(filed AS DATE)) AS entity
        FROM facts
        WHERE tag IN ({placeholders}) AND unit = 'USD' AND form = '10-K' AND val > 0
          AND CAST(filed AS DATE) BETWEEN ? AND ?
        GROUP BY cik, tag, period_start, period_end
        ORDER BY hash(cik, tag, period_start, period_end)
        LIMIT ?
        """,
        [*tags, filed_from, filed_to, limit],
    ).fetchall()
    ent_map: dict[int, Any] = {
        int(r[0]): r[1] for r in con.execute("SELECT cik, tickers FROM entities").fetchall()
    }
    out: list[dict[str, Any]] = []
    for r in rows:
        tickers = ent_map.get(int(r[0])) or []
        out.append(
            {
                "cik": int(r[0]),
                "tag": str(r[1]),
                "period_start": _day(r[2]),
                "period_end": _day(r[3]),
                "first_filed": _day(r[4]) or "",
                "last_filed": _day(r[5]) or "",
                "entity": r[6],
                "ticker": tickers[0] if tickers else None,
            }
        )
    return out


def _assemble_evidence(con: Any, cands: list[tuple[Any, ...]]) -> dict[int, dict[str, Any]]:
    """One set-based join for every candidate: the latest fact filed <= as_of,
    plus a count of how many facts were already public at as_of."""
    if not cands:
        return {}
    con.execute(
        "CREATE OR REPLACE TEMP TABLE cand "
        "(id INTEGER, cik BIGINT, tag VARCHAR, period_start DATE, period_end DATE, as_of DATE)"
    )
    con.executemany("INSERT INTO cand VALUES (?, ?, ?, ?, ?, ?)", cands)
    rows = con.execute(
        """
        SELECT c.id,
               MAX(CAST(f.filed AS DATE)) AS latest_filed,
               ARG_MAX(f.val, CAST(f.filed AS DATE)) AS latest_val,
               ARG_MAX(f.accn, CAST(f.filed AS DATE)) AS latest_accn,
               COUNT(f.val) AS n_known
        FROM cand c
        LEFT JOIN facts f
          ON f.cik = c.cik AND f.tag = c.tag AND f.unit = 'USD'
         AND CAST(f.filed AS DATE) <= c.as_of
         AND f.period_end = c.period_end
         AND f.period_start IS NOT DISTINCT FROM c.period_start
        GROUP BY c.id
        """
    ).fetchall()
    return {
        int(r[0]): {
            "latest_filed": _day(r[1]),
            "latest_val": r[2],
            "latest_accn": r[3],
            "n_known": int(r[4]),
        }
        for r in rows
    }


def _sample_pairs(
    con: Any, *, tags: list[str], filed_from: str, filed_to: str, limit: int
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Consecutive annual period pairs (330-395 days apart) per (cik, tag).
    Self-join over the grouped key set — random key samples almost never
    contain both periods of a pair."""
    placeholders = ", ".join("?" * len(tags))
    rows = con.execute(
        f"""
        WITH k AS (
            SELECT cik, tag, period_start, period_end,
                   MIN(CAST(filed AS DATE)) AS first_filed,
                   MAX(CAST(filed AS DATE)) AS last_filed,
                   ARG_MAX(entity_name, CAST(filed AS DATE)) AS entity
            FROM facts
            WHERE tag IN ({placeholders}) AND unit = 'USD' AND form = '10-K' AND val > 0
              AND CAST(filed AS DATE) BETWEEN ? AND ?
            GROUP BY cik, tag, period_start, period_end
        )
        SELECT a.cik, a.tag, a.period_start, a.period_end, a.first_filed, a.last_filed, a.entity,
               b.period_start, b.period_end, b.first_filed, b.last_filed
        FROM k a JOIN k b
          ON a.cik = b.cik AND a.tag = b.tag AND b.period_end > a.period_end
         AND (CAST(b.period_end AS DATE) - CAST(a.period_end AS DATE)) BETWEEN 330 AND 395
        ORDER BY hash(a.cik, a.tag, a.period_end, b.period_end)
        LIMIT ?
        """,
        [*tags, filed_from, filed_to, limit],
    ).fetchall()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for r in rows:
        a = {
            "cik": int(r[0]),
            "tag": str(r[1]),
            "period_start": _day(r[2]),
            "period_end": _day(r[3]),
            "first_filed": _day(r[4]) or "",
            "last_filed": _day(r[5]) or "",
            "entity": r[6],
        }
        b = {
            "cik": int(r[0]),
            "tag": str(r[1]),
            "period_start": _day(r[7]),
            "period_end": _day(r[8]),
            "first_filed": _day(r[9]) or "",
            "last_filed": _day(r[10]) or "",
            "entity": r[6],
        }
        pairs.append((a, b))
    return pairs


def _ident(key: dict[str, Any]) -> str:
    """Entity identifier embedded in every question: benchmarks test point-in-time
    reasoning, not the model's ability to guess ticker symbols."""
    return f"(ticker: {key['ticker']})" if key.get("ticker") else f"(CIK {key['cik']})"


def _t1_question(entity: str, ident: str, metric: str, period_end: str, as_of: str) -> str:
    return (
        f"According to public SEC filings available as of {as_of}, what was the "
        f"{metric} of {entity} {ident} for the fiscal period ending {period_end}? "
        "If this was not public at that date, answer exactly: unknown."
    )


def _t3_question(entity: str, ident: str, metric: str, period_end: str, as_of: str) -> str:
    return (
        f"As of {as_of}, estimate the {metric} of {entity} {ident} for the fiscal "
        f"year ending {period_end}, using only information that was public at that "
        "time. Reply with a single number in USD."
    )


def generate(
    con: Any,
    *,
    seed: int = 42,
    pool_t1: int = 300,
    pool_t2: int = 200,
    pool_t3: int = 120,
    filed_from: str = "2016-01-01",
    filed_to: str = "2024-12-31",
) -> list[dict[str, Any]]:
    """Generate the full pool (T1+T2+T3). Deterministic for a given database
    state + seed. core-set selection happens in model.freeze_core."""
    rng = random.Random(seed)
    pairs = (
        _sample_pairs(con, tags=_TAGS, filed_from=filed_from, filed_to=filed_to, limit=pool_t3 * 2)
        if pool_t3
        else []
    )
    needed = pool_t1 + pool_t2 + 20 + 2 * len(pairs)  # headroom for dropped candidates
    keys = _sample_keys(con, tags=_TAGS, filed_from=filed_from, filed_to=filed_to, limit=needed)
    rng.shuffle(keys)
    pair_key_ids = {id(k) for pair in pairs for k in pair}
    keys = [k for k in keys if id(k) not in pair_key_ids]

    tasks: list[dict[str, Any]] = []
    counter = {"n": 0}

    def next_id(family: str) -> str:
        counter["n"] += 1
        return f"{family.lower()}-{counter['n']:06d}"

    def base_task(family: str, subtype: str, key: dict[str, Any], as_of: str) -> dict[str, Any]:
        return {
            "task_id": next_id(family),
            "family": family,
            "subtype": subtype,
            "cik": key["cik"],
            "entity": key["entity"],
            "tag": key["tag"],
            "metric": METRIC_NAMES.get(key["tag"], key["tag"]),
            "period_start": key["period_start"],
            "period_end": key["period_end"],
            "as_of": as_of,
            "question": "",
            "gold": {},
            "meta": {},
        }

    # --- allocate keys: T3 pairs first (rarest), then T1, then T2 -----------
    accepted_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    t1_keys = keys[: pool_t1]
    t2_keys = keys[pool_t1 : pool_t1 + pool_t2]

    # --- T3: question-at-as_of + gold-from-future as two candidate rows -----
    if pairs:
        cands: list[tuple[Any, ...]] = []
        pair_meta: list[tuple[str, str]] = []  # (question task id, gold row id)
        for a, b in pairs:
            if len(accepted_pairs) >= pool_t3:
                break
            # Window: [period-a first public, period-b first public). a's
            # last_filed is polluted by comparative restatements in later 10-Ks
            # (it always postdates b.first_filed), so anchor lo on first_filed.
            lo = date.fromisoformat(a["first_filed"]) + timedelta(days=1)
            hi = date.fromisoformat(b["first_filed"]) - timedelta(days=1)
            if lo > hi:
                continue
            as_of = lo + timedelta(days=rng.randint(0, (hi - lo).days))
            q_task = base_task("T3", "forward", b, _day(as_of) or "")
            id_q = q_task["task_id"]
            id_g = next_id("T3")  # id for the gold candidate row only
            q_task["question"] = _t3_question(
                str(b["entity"]),
                _ident(b),
                METRIC_NAMES.get(b["tag"], b["tag"]),
                b["period_end"],
                q_task["as_of"],
            )
            q_task["gold"] = {"kind": "forward"}
            q_task["meta"]["gold_withheld_at_publish"] = True
            tasks.append(q_task)
            accepted_pairs.append((a, b))
            pair_meta.append((id_q, id_g))
            cands.append(
                (len(cands), b["cik"], b["tag"], b["period_start"], b["period_end"], as_of)
            )
            cands.append(
                (len(cands), b["cik"], b["tag"], b["period_start"], b["period_end"], _GOLD_AS_OF)
            )
        resolved = _assemble_evidence(con, cands)
        # rows were appended question-first, gold-second per pair
        ids = [c[0] for c in cands]
        for i, (id_q, _id_g) in enumerate(pair_meta):
            at_as_of = resolved.get(ids[2 * i], {})
            gold = resolved.get(ids[2 * i + 1], {})
            for t in tasks:
                if t["task_id"] == id_q:
                    if at_as_of.get("n_known", 1) != 0:
                        t["gold"] = {"kind": "forward", "invalid": "value already public at as_of"}
                        t["meta"]["drop"] = True
                    else:
                        t["gold"] = {
                            "kind": "forward",
                            "value": gold.get("latest_val"),
                            "accn": gold.get("latest_accn"),
                            "filed": gold.get("latest_filed"),
                        }

    # --- T1 + T2 evidence ----------------------------------------------------
    cands = []
    plan: list[tuple[str, str, dict[str, Any], str]] = []
    for key in t1_keys:
        first = date.fromisoformat(key["first_filed"])
        last = date.fromisoformat(key["last_filed"])
        subtype = "null" if rng.random() < 0.3 else "positive"
        as_of = (
            first - timedelta(days=1)
            if subtype == "null"
            else last + timedelta(days=rng.randint(7, 180))
        )
        task = base_task("T1", subtype, key, _day(as_of) or "")
        task["question"] = _t1_question(
            str(key["entity"]),
            _ident(key),
            METRIC_NAMES.get(key["tag"], key["tag"]),
            key["period_end"],
            task["as_of"],
        )
        tasks.append(task)
        plan.append((task["task_id"], subtype, key, task["as_of"]))
        cands.append(
            (len(cands), key["cik"], key["tag"], key["period_start"], key["period_end"], as_of)
        )
    for key in t2_keys:
        first = date.fromisoformat(key["first_filed"])
        as_of = first + timedelta(days=rng.randint(1, 60))
        task = base_task("T2", "placeholder", key, _day(as_of) or "")
        tid = task["task_id"]
        tasks.append(task)
        plan.append((tid, "t2", key, task["as_of"]))
        cands.append(
            (len(cands), key["cik"], key["tag"], key["period_start"], key["period_end"], as_of)
        )

    resolved = _assemble_evidence(con, cands)
    # cands were appended in plan order; id i corresponds to plan[i]
    for i, (tid, subtype, key, as_of_str) in enumerate(plan):
        task = next(t for t in tasks if t["task_id"] == tid)
        ev = resolved.get(i, {})
        metric = METRIC_NAMES.get(key["tag"], key["tag"])
        if subtype in ("positive", "null"):
            if subtype == "null":
                if ev.get("n_known", 1) != 0:
                    task["meta"]["drop"] = True  # 8-K or earlier form pre-announced it
                task["gold"] = {"kind": "unknown"}
            else:
                task["gold"] = {
                    "kind": "value",
                    "value": ev.get("latest_val"),
                    "accn": ev.get("latest_accn"),
                    "filed": ev.get("latest_filed"),
                }
        else:  # T2
            val = ev.get("latest_val")
            accn = ev.get("latest_accn")
            filed = ev.get("latest_filed")
            statement_val = val
            expected = "true"
            if rng.random() < 0.5 and val:
                factor = rng.choice([0.7, 0.85, 1.15, 1.3])
                statement_val = val * factor
                expected = "false"
            statement = (
                f"{key['entity']} {_ident(key)} reported {metric} of "
                f"{statement_val:,.0f} USD for the fiscal period ending "
                f"{key['period_end']}."
            )
            task["question"] = (
                f"As of {as_of_str}, is this statement correct according to public SEC "
                "filings? Answer with exactly 'true' or 'false', then cite the "
                f"filing (accession number). Statement: {statement}"
            )
            task["subtype"] = expected
            task["gold"] = {
                "kind": expected,
                "true_value": val,
                "stated_value": statement_val,
                "accn": accn,
                "filed": filed,
            }
    return [task_to_dict(t) for t in tasks if not t.get("meta", {}).get("drop")]
