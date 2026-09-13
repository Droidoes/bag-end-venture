"""Finpage payload builder — the financial page's data seam.

Queries private/books.db and emits ONE JSON bundle (no numbers ever committed;
the bundle is written only to local data dirs) for the static BagEnd.html
viewer. Mirrors the Homepage-projects pattern: hosted page + locally-connected
data file.

CONSUMER CONTRACT (2026-09-13): this module is a READ path. `export finpage` runs
under `loader21.assert_schema(con, mode="read")`, so it keeps serving the page
while the live store is still pre-migration — which means every column it selects
must exist on every version in
`loader21.READ_COMPATIBLE_SCHEMA_VERSIONS`. Selecting a v0.2.6-only column here
(`n_copy`, `composition_class`, `fact_state.origin`, …) silently re-breaks the
dashboard against the live store: `v_net_worth` is read for `as_of`, `metric_id`
and `total` only, which hold all the way back to v0.2.4. If this page ever
genuinely needs a newer column, the fix is the migration, not the gate — promote
the store rather than reading a figure it cannot supply.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BORN_YEAR = 1968
AGE_100 = 100
SS67_FIRST_FULL_YEAR = BORN_YEAR + 67 + 1
SS62_FIRST_FULL_YEAR = BORN_YEAR + 62 + 1


def _assumption(con: sqlite3.Connection, key: str, default):
    row = con.execute("SELECT value_num, value_text FROM v_assumption_current WHERE key=?",
                      (key,)).fetchone()
    if row is None:
        return default
    return row[0] if row[0] is not None else row[1]


def _ss_by_age(con: sqlite3.Connection) -> dict:
    rows = con.execute("""SELECT claim_basis, amount FROM ss_benefit_estimates
                          WHERE claim_basis LIKE 'Age%' AND superseded_by_batch_id IS NULL
                          AND (claim_basis, work_year) IN (
                            SELECT claim_basis, MAX(work_year) FROM ss_benefit_estimates
                            WHERE superseded_by_batch_id IS NULL GROUP BY claim_basis)""").fetchall()
    out = {}
    for basis, amount in rows:
        try:
            out[int(basis[3:])] = amount
        except (ValueError, TypeError):
            continue
    return out


def _ladder(balance: float, spend0: float, *, yield_: float, escalate: float,
            ss_schedule: dict, start_year: int) -> dict:
    bal, s = balance, spend0
    min_bal, broke_at = float("inf"), None
    for y in range(start_year, BORN_YEAR + AGE_100 + 1):
        bal = (bal - s + ss_schedule.get(y, 0.0)) * (1 + yield_)
        if bal < 0:
            broke_at = y
            break
        min_bal = min(min_bal, bal)
        s *= (1 + escalate)
    return {"min_balance": min_bal if broke_at is None else None,
            "broke_at": broke_at,
            "end_balance": bal if broke_at is None else None}


def _schedule(monthly: float, rate: float, go_broke_year: int, first_full_year: int,
              step_change: bool) -> dict:
    out: dict = {}
    if step_change:
        for y in range(first_full_year, go_broke_year):
            out[y] = monthly * 12
    start = go_broke_year if step_change else first_full_year
    for y in range(start, BORN_YEAR + AGE_100 + 1):
        out[y] = monthly * rate * 12
    return out


def _a_max(balance: float, yield_: float, ss_schedule: dict, start_year: int) -> float:
    lo, hi = 0.0, balance * 1.5
    for _ in range(80):
        mid = (lo + hi) / 2
        r = _ladder(balance, mid, yield_=yield_, escalate=0.0,
                    ss_schedule=ss_schedule, start_year=start_year)
        if r["broke_at"] is not None or (r["end_balance"] or 0) < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def build_payload(con: sqlite3.Connection) -> dict:
    con.row_factory = sqlite3.Row
    # v_net_worth.total is additive-only (Slice B): a group whose rows are ALL copies
    # or errors publishes NULL, never 0 — "unknown is not zero". This page's anchor
    # balance is therefore the most recent group that HAS an additive total; a NULL
    # group is not a balance, and `series` below has always dropped NULL points. The
    # as_of travels with the payload, so which month's total was used is visible.
    bal = con.execute("""SELECT total, as_of FROM v_net_worth WHERE metric_id=
                         (SELECT metric_id FROM dim_metric WHERE name='TOTAL_ASSETS')
                         AND total IS NOT NULL
                         ORDER BY as_of DESC LIMIT 1""").fetchone()
    if bal is None:
        raise SystemExit("no additive net-worth total in store (every group is "
                         "all-copy/all-error, or none was loaded)")

    series = con.execute("""SELECT as_of, total FROM v_net_worth WHERE metric_id=
                            (SELECT metric_id FROM dim_metric WHERE name='TOTAL_ASSETS')
                            ORDER BY as_of""").fetchall()
    series = [r for r in series if r[1] is not None]

    ss_by_age = _ss_by_age(con)
    ss67 = ss_by_age.get(67)
    ss62 = ss_by_age.get(62)
    if ss67 is None or ss62 is None:
        raise SystemExit("no Age62/Age67 SS estimates in store")
    rate = _assumption(con, "ssa.go_broke.rate", 0.78)
    gb = int(_assumption(con, "ssa.go_broke.year", 2032))
    yield_lt = _assumption(con, "yield.long_term", 0.03)
    mult = _assumption(con, "spending.plan.multiplier", 2.0)
    spend2025 = _assumption(con, "spending.current.2025", 57_274.88)
    plan = spend2025 * mult

    variants = [
        ("claim 67 · SS 78% flat (base)", SS67_FIRST_FULL_YEAR,
         _schedule(ss67, rate, gb, SS67_FIRST_FULL_YEAR, False)),
        ("claim 62 · full until go-broke year, then haircut", SS62_FIRST_FULL_YEAR,
         _schedule(ss62, rate, gb, SS62_FIRST_FULL_YEAR, True)),
        ("claim 62 · SS 78% flat", SS62_FIRST_FULL_YEAR,
         _schedule(ss62, rate, gb, SS62_FIRST_FULL_YEAR, False)),
    ]
    reference = []
    for name, first_yr, sched in variants:
        for yld, label in ((yield_lt, "store"), (0.02, "fragile")):
            am = _a_max(bal[0], yld, sched, 2026)
            p = _ladder(bal[0], plan, yield_=yld, escalate=0.0,
                        ss_schedule=sched, start_year=2026)
            reference.append({"variant": name, "yield": yld, "yield_label": label,
                              "a_max": round(am, 2),
                              "plan_end_at_100": round(p["end_balance"], 2)
                              if p["end_balance"] is not None else None,
                              "plan_broke_at": p["broke_at"]})

    tax = [dict(r) for r in con.execute("""SELECT tax_year, filing_status, agi,
        taxable_income, total_tax, std_deduction, state_income_tax, marginal_bracket,
        source, needs_verify FROM tax_year_facts
        WHERE superseded_by_batch_id IS NULL ORDER BY tax_year""").fetchall()]

    assumptions = []
    for r in con.execute("""SELECT key, value_num, value_text FROM v_assumption_current
                            ORDER BY key""").fetchall():
        assumptions.append({"key": r[0], "value": r[1] if r[1] is not None else r[2]})

    top = [dict(r) for r in con.execute("""SELECT s.ticker AS symbol, ROUND(SUM(h.market_value),2) AS market_value,
        ROUND(100.0 * SUM(h.market_value) / (SELECT total FROM v_net_worth WHERE metric_id=
        (SELECT metric_id FROM dim_metric WHERE name='TOTAL_ASSETS')
        AND total IS NOT NULL
        ORDER BY as_of DESC LIMIT 1), 1) AS weight_pct
        FROM v_holding_current h JOIN dim_security s ON s.security_id = h.security_id
        GROUP BY s.ticker ORDER BY 2 DESC LIMIT 8""").fetchall()]

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": con.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()[0],
            "page_protocol": 2,
        },
        "pages": {
            "retirement": {
                "networth": {
                    "total": bal[0], "as_of": bal[1],
                    "as_ofs": [r[0] for r in series],
                    "totals": [round(r[1], 2) for r in series],
                },
                "annuity": {
                    "born_year": BORN_YEAR, "zero_age": AGE_100,
                    "age_now": 2026 - BORN_YEAR, "start_year": 2026,
                    "balance": bal[0], "balance_as_of": bal[1],
                    "ss_by_age": ss_by_age,
                    "ss67_monthly": ss67, "ss62_monthly": ss62,
                    "go_broke_year": gb, "go_broke_rate": rate,
                    "yield_long_term": yield_lt,
                    "spending": {"current_2025": spend2025, "multiplier": mult, "planned": plan},
                    "reference": reference,
                },
                "tax": tax,
                "holdings_top": top,
                "assumptions": assumptions,
            },
        },
    }
