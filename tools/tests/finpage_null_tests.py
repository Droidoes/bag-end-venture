#!/usr/bin/env python3
"""v0.2.6 — the finpage consumer handles an all-copy/all-error NULL total.

Slice B made `v_net_worth.total` additive-only: a group whose rows are ALL copies or
errors publishes NULL, never 0, because "unknown is not zero". `tools/bagend/finpage.py`
read `total` in three places (the anchor balance, the series, and the holdings
denominator). Before this fix the anchor read took the latest group blindly, so a NULL
latest total reached `_a_max(None, …)` and crashed with a TypeError; the holdings
denominator would have divided by NULL and published a NULL weight.

The fix is NOT in the view: the NULL total is correct and this battery asserts it stays
NULL. The fix is that the consumer treats a NULL group as "not a balance" and anchors on
the most recent group that HAS an additive total, exactly as the existing `series` read
already filtered — with the as_of reported alongside, so which month is visible.

Offline, synthetic, in-memory only. No financial value is asserted — only whether a
total is present, which as_of was chosen, and that the view still says NULL.

Run from the repo root:
    python3 tools/tests/finpage_null_tests.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from bagend import finpage  # noqa: E402
from tools.bagend import loader21 as L  # noqa: E402

DDL = Path("tools/schema/books.sql").read_text()
PASS = FAIL = 0
FAILURES: list[str] = []


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def store(latest: str) -> sqlite3.Connection:
    """A tiny store with one additive month and, optionally, a later NULL month.

    latest='ok'    -> only the additive group
    latest='error' -> a later group that is a single error row (total NULL)
    latest='copy'  -> a later group that is a single pure copy  (total NULL)
    """
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    con.execute("INSERT INTO load_batch(batch_id,started_at,status) "
                "VALUES (1,'2026-01-01T00:00:00','complete')")
    con.execute("INSERT INTO src_ref(source_id,alias,drive_id,source_kind,read_path,"
                "precedence,role) VALUES (1,'probe','drv','native-google-sheet',"
                "'sheets.values.get',1,'raw')")
    con.execute("INSERT INTO dim_account(account_id,code,institution,registration,"
                "entity,purpose) VALUES (1,'ACCT_X','synthetic','other','Joe','unsettled')")
    con.execute("INSERT INTO dim_metric(metric_id,name,is_flow,is_year_relative,"
                "polarity,unit) VALUES (1,'TOTAL_ASSETS',0,0,'asset','USD')")
    con.execute("INSERT INTO dim_security(security_id,ticker) VALUES (1,'AAA')")
    con.execute("""INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,
        seq_in_date,value_num,presence,origin,period_grain,content_hash,source_id,
        batch_id,ingested_at) VALUES ('p|1',1,1,'2026-01-31',1,100.0,'measured',
        'entered','month-end','h1',1,1,'2026-01-01T00:00:00')""")
    if latest == "error":
        con.execute("""INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,
            seq_in_date,value_text,error_type,presence,origin,period_grain,content_hash,
            source_id,batch_id,ingested_at) VALUES ('p|2',1,1,'2026-02-28',1,'#REF!',
            '#REF!','error','derived','month-end','h2',1,1,'2026-01-01T00:00:00')""")
    elif latest == "copy":
        con.execute("""INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,
            seq_in_date,value_num,presence,origin,period_grain,content_hash,source_id,
            batch_id,ingested_at) VALUES ('p|2',1,1,'2026-02-28',1,100.0,'measured',
            'copy','month-end','h3',1,1,'2026-01-01T00:00:00')""")
    # finpage's other prerequisite: the two claim ages
    for basis, amount in (("Age62", 1000.0), ("Age67", 1500.0)):
        con.execute("INSERT INTO ss_benefit_estimates(natural_key,work_year,claim_basis,"
                    "amount,unit,is_estimate,source_id,batch_id,ingested_at) "
                    "VALUES (?,2025,?,?,'monthly',1,1,1,'2026-01-01T00:00:00')",
                    (basis, basis, amount))
    con.execute("INSERT INTO holding_state(natural_key,account_id,security_id,as_of,"
                "market_value,source_id,batch_id,ingested_at) VALUES "
                "('h|1',1,1,'2026-01-31',25.0,1,1,'2026-01-01T00:00:00')")
    return con


def main() -> int:
    print("== finpage NULL-total battery (v0.2.6) ==")

    print("\n-- the view is NOT weakened: an all-copy/all-error group stays NULL")
    for kind in ("error", "copy"):
        con = store(kind)
        row = con.execute("SELECT total, n_error, n_copy FROM v_net_worth "
                          "WHERE metric_id=1 AND as_of='2026-02-28'").fetchone()
        check(f"the all-{kind} group publishes total IS NULL (never 0)",
              row[0] is None, row)
        check(f"...and names it: {kind} count = 1",
              row[1 if kind == "error" else 2] == 1, row)
        con.close()

    print("\n-- the consumer anchors on the latest group WITH an additive total")
    for kind in ("error", "copy"):
        con = store(kind)
        payload = finpage.build_payload(con)
        nw = payload["pages"]["retirement"]["networth"]
        check(f"latest={kind}: a payload is built (no TypeError)", payload is not None)
        check(f"latest={kind}: the published total is not None", nw["total"] is not None,
              nw["total"])
        check(f"latest={kind}: the anchor as_of is the additive month, not the NULL one",
              nw["as_of"] == "2026-01-31", nw["as_of"])
        check(f"latest={kind}: the series carries the additive point only",
              nw["as_ofs"] == ["2026-01-31"], nw["as_ofs"])
        top = payload["pages"]["retirement"]["holdings_top"]
        check(f"latest={kind}: the holdings weight uses the same additive denominator "
              f"(no NULL weight)", top and top[0]["weight_pct"] is not None, top)
        con.close()

    print("\n-- an all-NULL store refuses instead of fabricating a balance")
    con = store("error")
    con.execute("DELETE FROM fact_state WHERE natural_key='p|1'")
    try:
        finpage.build_payload(con)
        check("all-NULL store -> SystemExit", False, "no SystemExit")
    except SystemExit as e:
        check("all-NULL store -> SystemExit (unknown is not zero)",
              "additive net-worth total" in str(e), str(e))
    con.close()

    print("\n-- the control: an ordinary store is unchanged")
    con = store("ok")
    nw = finpage.build_payload(con)["pages"]["retirement"]["networth"]
    check("control: as_of and total come from the only (additive) group",
          nw["as_of"] == "2026-01-31" and nw["total"] is not None, nw)
    con.close()

    probe = store("ok")
    check("the fixture store and the loader agree on the schema version (no half-bump)",
          probe.execute("SELECT value FROM _schema_meta WHERE key='schema_version'"
                        ).fetchone()[0] == L.SCHEMA_VERSION, L.SCHEMA_VERSION)
    probe.close()

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAILURES:
        print("FAILURES:", *FAILURES, sep="\n  ")
    print("BATTERY COMPLETE")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
