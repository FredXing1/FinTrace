# TradingAgents v0.6.0: a point-in-time audit of the dominant open-source financial agent framework

**Code-level audit** · 2026-10-16 · commit `1394a3f` (v0.6.0, merged 2026-10-03) · no LLM runs

Scope: every data surface TradingAgents exposes to its agents, audited against
one question — *can a run dated T observe information that was not public at
T?* This is the same look-ahead axis PITfall measures (§5 of the technical
report), applied by reading code rather than running tasks. TradingAgents is
the most-referenced open-source multi-agent trading framework and defines the
pattern most derivatives copy, so its defaults matter beyond its own users.

## 1. Context: the pattern changed in v0.6.0

The "naive agent" of our leakage audit — live-data tools with no time gate —
was modeled on TradingAgents' earlier architecture. **v0.6.0 ships a genuine
point-in-time layer** (`tradingagents/dataflows/date_window.py`, per-vendor
guards, and an as-filed SEC EDGAR source). The audit below therefore documents
both what the layer gets right and the surfaces it does not yet cover. This is
good news for the ecosystem: the dominant framework is converging toward
time discipline, not away from it.

## 2. What v0.6.0 gets right

1. **As-filed fundamentals from SEC EDGAR** (`dataflows/vendors/sec_edgar.py`).
   Statements are served at `filed ≤ as_of_date`, restatement-aware (a period
   keeps the latest filing on or before the date, so amendments count from
   their filing day), with duration-span checks that stop a six-month figure
   reading as a quarter, no Q4 derived by subtraction ("a number no filing
   states"), and no sums across tags. The module docstring's framing — "a
   figure that was later restated is not what investors saw at the time" — is
   exactly the as-filed semantics FinTrace's data layer is built on.
2. **Price/indicator paths bounded at `as_of`**
   (`dataflows/vendors/yahoo/ohlcv.py`): rows after the as-of date are
   filtered even when a vendor over-returns, cached windows are
   freshness-checked against the as-of date, and stale-window results are
   rejected rather than served.
3. **Macro data at true vintages** (`dataflows/vendors/fred.py`): FRED's
   realtime windows pin observations to what was published by the as-of date
   (ALFRED-style), with the vintage clamp documented.
4. **Conservative window filtering for dated feeds**
   (`dataflows/date_window.py`): news/social items outside
   `[start, end)` are dropped, and an *undated* item is kept only when the
   window reaches the present — "a backtest cannot prove it is not from the
   future". Windows a feed could not observe are reported as coverage gaps,
   not as empty results.
5. **Live snapshots withheld from historical runs**: company overview
   (yfinance `info`), yfinance statements (no per-filing vintage), insider
   transactions, and Polymarket odds are all withheld when the run date is in
   the past, each with a message saying why.
6. **Request clamping**: windows the model asks for are clamped to the run's
   trade date, so the agent cannot reach a vendor with a later one.

## 3. Remaining look-ahead surfaces

1. **Identity context is unguarded** (`tradingagents/agents/context.py:88`).
   Every run — including backtests dated years back — injects fields from
   today's vendor profile (`get_company_profile` → live `Ticker.info`, no
   `as_of` parameter): company name, sector, industry, exchange, quote type.
   Severity is low (these change slowly) but the surface is conceptually the
   same one `withhold_live_profile` guards elsewhere, and sector/exchange
   reclassifications do happen.
2. **Withholding is not the same as serving as-filed.** For a historical run,
   the fundamentals overview, yfinance statements, insider data, and
   prediction-market odds are *withheld outright*; only US filers keep
   statement-level fundamentals (via EDGAR). A backtest therefore runs its
   fundamentals analyst with large holes — an honesty-preserving but
   capability-destroying choice that pressures users toward live-data
   configurations, where the leakage our audit measures (82% of impossible
   tasks answered by a naive agent) re-enters through the door. The data to
   serve more of it as-filed exists (EDGAR covers the overview's quantitative
   fields too).
3. **Per-surface reasoning, not a shared primitive.** The PIT guarantees are
   implemented vendor-by-vendor with shared helpers, but nothing *forces* a
   new data path through them: the guard is a convention each integration
   must opt into. FinTrace's design inverts this — `as_of(T)` is a required
   argument on the query primitive itself, so a new surface that forgets the
   date fails loudly instead of silently serving "latest".
4. **Vendor timestamps are trusted where present.** Dated feeds are window-
   filtered using vendor-supplied timestamps; a misdated item passes. The
   undated-item rule is conservative, but nothing downstream can tell a
   verified-old item from a merely-claimed-old one.
5. **No measurement layer.** Nothing verifies the guardrails bind the agent:
   there is no equivalent of unknown-gold probes (tasks whose answers were
   not public at T, where any specific answer is proof of leakage) and no
   reported leakage rate. Our ablation (technical report §5.4) shows why this
   matters: guardrails that exist but are not structural fail silently — a
   discipline prompt alone still leaked 35% of impossible tasks.

## 4. Comparison with FinTrace's approach

| axis | TradingAgents v0.6.0 | FinTrace |
|---|---|---|
| time discipline | per-surface guards, opt-in per vendor | `as_of(T)` required on the shared query primitive |
| fundamentals | as-filed statements (US filers); overview withheld for historical runs | 125.5M as-filed facts served at any vintage |
| live data in backtests | withheld with explanations | structurally unreachable |
| leakage verification | none in-repo | PITfall unknown-gold probes + per-run leakage rate |
| audit trail | logged tool calls | auditpack (claims → evidence chain → verdicts → sign-off) |

## 5. Conclusion

v0.6.0 is a substantive step toward time discipline: the as-filed EDGAR path
and the withhold/coverage-gap machinery are correct in direction and mostly
careful in detail. The gaps that remain are (i) one unguarded context surface,
(ii) a withhold-not-serve posture that degrades historical backtests and
invites users back to leaky live-data mode, (iii) discipline that is
conventional rather than structural, and (iv) no measurement that would catch
a future regression. All four are addressable, and items (ii)–(iv) are exactly
what the FinTrace + PITfall pairing exists to provide: serve the past as it
was, make the gate structural, and measure leakage instead of assuming it.

*We audited source code only; this is not a claim about TradingAgents' live
behavior beyond commit `1394a3f`, nor an investment recommendation.*
