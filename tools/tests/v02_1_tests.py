#!/usr/bin/env python3
"""v0.2.1 panel-fix battery: reproduces leg B's P01-P14 and leg C's NEW-C1/Q2d
against the authoritative tools/schema/books.sql (v0.2 lineage, post-reconciliation). Synthetic fixtures only.
"""
import sqlite3, pathlib, sys

DDL = (pathlib.Path(__file__).parent / "../../tools/schema/books.sql").read_text()

def fresh():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    return con

def seed(con):
    con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (1,'2026-09-07T00:00:00','complete')")
    for sid, alias, prec in [(1,'src_a',10),(2,'src_b',10)]:   # NOTE: equal precedence for tie tests
        con.execute("INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, precedence, role) "
                    "VALUES (?,?,?,?,?,?,?)", (sid, alias, f'd{sid}', 'native-google-sheet', 'sheets.values.get', prec, 'raw'))
    con.execute("INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (1,'A1','i','taxable','Joe','growth')")
    con.execute("INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative, polarity) VALUES (1,'MKT',0,0,'asset')")
    con.execute("INSERT INTO dim_txn_type(txn_type_id, source_id, raw_label, canonical) VALUES (1,1,'UNMAPPED','UNMAPPED')")
    con.execute("INSERT INTO dim_category(category_id, source_id, source_label, canonical, spending_class) VALUES (1,1,'UNMAPPED','UNMAPPED','unsettled')")

def S(con, nk, day, val, src=1, batch=1, seq=1, acct=1, met=1, hsh=None):
    con.execute("""INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, value_num,
                   period_grain, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,?,?,?,?,?,'monthly',?,?,?, '2026-09-07T01:00:00')""",
                (nk, acct, met, day, seq, val, hsh or f"c:{acct}:{met}:{day}:{seq}:{val}", src, batch))

def ok(label, fn):
    try:
        fn(); print(f"  PASS  {label}")
    except Exception as e:
        print(f"  FAIL  {label}: {e}"); raise

def fail(label, fn, match=None):
    try:
        fn()
    except Exception as e:
        if match and match not in str(e):
            print(f"  FAIL  {label}: wrong error {e}"); raise
        print(f"  PASS  {label}  (rejected)"); return
    print(f"  FAIL  {label}: accepted"); raise AssertionError(label)

print("== v0.2.1 panel-fix battery ==")
con = fresh(); seed(con)

print("\n-- P01: equal-valued same-day pair coexists (ordinal in hash)")
S(con, 'src_a|a1|m1|2025-07-08|1', '2025-07-08', 100.0, seq=1)
S(con, 'src_a|a1|m1|2025-07-08|2', '2025-07-08', 100.0, seq=2)   # same value, different ordinal
ok("both equal-valued rows stored", lambda: (_ for _ in ()).throw(AssertionError())
   if con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-07-08'").fetchone()[0] != 2 else None)

print("\n-- P02: unchanged re-ingest succeeds as a fresh version (supersede-then-insert)")
con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (2,'2026-09-07T02:00:00','complete')")
con.execute("UPDATE fact_state SET superseded_by_batch_id=2 WHERE batch_id=1")   # loader step 1
S(con, 'src_a|a1|m1|2025-07-08|1', '2025-07-08', 100.0, seq=1, batch=2)          # loader step 3
S(con, 'src_a|a1|m1|2025-07-08|2', '2025-07-08', 100.0, seq=2, batch=2)
ok("unchanged rows re-inserted under new batch", lambda: (_ for _ in ()).throw(AssertionError())
   if con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-07-08' AND batch_id=2").fetchone()[0] != 2 else None)

print("\n-- P03: partial supersession cannot publish a stale ordinal (max-batch rule)")
con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (3,'2026-09-07T03:00:00','complete')")
S(con, 'src_a|a1|m1|2025-07-08|1', '2025-07-08', 111.0, seq=1, batch=3)   # batch 3 loads ONLY ordinal 1, corrected
# ordinal 2 of batch 2 is NOT marked superseded (the loader bug leg B simulated)
v = con.execute("SELECT value_num, seq_in_date FROM v_state_current WHERE as_of='2025-07-08' AND metric_id=1").fetchone()
ok("stale ordinal-2 row excluded, corrected batch wins", lambda: (_ for _ in ()).throw(AssertionError(f"{v}"))
   if v != (111.0, 1) else None)

print("\n-- P04/P14: equal-authority disagreements surface as conflicts, not silent winners")
S(con, 'src_a|a1|m1|2025-09-30|1', '2025-09-30', 500.0, src=1)
S(con, 'src_b|a1|m1|2025-09-30|1', '2025-09-30', 512.0, src=2)
n = con.execute("SELECT COUNT(*) FROM v_state_conflicts WHERE as_of='2025-09-30' AND metric_id=1").fetchone()[0]
ok("conflict view reports the tie", lambda: (_ for _ in ()).throw(AssertionError(f"{n}"))
   if n != 1 else None)
v = con.execute("SELECT value_num FROM v_state_current WHERE as_of='2025-09-30' AND metric_id=1").fetchone()
ok("one deterministic winner still published (auditable via v_state_conflicts)",
   lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v[0] not in (500.0, 512.0) else None)

print("\n-- P05: malformed sheet_modified rejected; ISO ordering correct")
fail("sheet_modified '2026-9-7'", lambda: con.execute(
    "INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, precedence, role, sheet_modified) "
    "VALUES (9,'src_x','d','native-google-sheet','sheets.values.get',50,'raw','2026-9-7')"))
con.execute("UPDATE src_ref SET sheet_modified='2026-09-01T00:00:00' WHERE source_id=1")
con.execute("UPDATE src_ref SET sheet_modified='2026-10-01T00:00:00' WHERE source_id=2")
v = con.execute("SELECT source_id FROM v_state_current WHERE as_of='2025-09-30' AND metric_id=1").fetchone()
ok("October source outranks September", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (2,) else None)

print("\n-- P06: precedence edits are audited")
con.execute("UPDATE src_ref SET precedence=5 WHERE source_id=2")
n = con.execute("SELECT COUNT(*) FROM src_audit WHERE source_id=2").fetchone()[0]
ok("curation change lands in src_audit", lambda: (_ for _ in ()).throw(AssertionError(f"{n}")) if n == 0 else None)

print("\n-- P07: error components visible in v_net_worth, never silently summed")
con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (4,'2026-09-07T04:00:00','complete')")
S(con, 'src_a|a1|m1|2025-12-31|1', '2025-12-31', 100.0, batch=4)
con.execute("INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (2,'A2','i2','401k','Joe','growth')")
con.execute("""INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, value_text, presence,
               period_grain, content_hash, source_id, batch_id, ingested_at)
               VALUES ('src_a|a2|m1|2025-12-31|1', 2, 1, '2025-12-31', 1, 'pending', 'error',
               'month-end', 'c:2:1:2025-12-31:1:err', 1, 4, '2026-09-07T01:00:00')""")
row = con.execute("SELECT total, n_components, n_error FROM v_net_worth WHERE as_of='2025-12-31' AND metric_id=1").fetchone()
ok("total sums only numeric, n_error=1", lambda: (_ for _ in ()).throw(AssertionError(f"{row}"))
   if row != (100.0, 2, 1) else None)

print("\n-- P09/P10: event re-ingest replaces the day; cross-source duplicates under dedupe rules")
def E(con, nk, day, amt, src=1, batch=1, seq=1):
    con.execute("""INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id,
                   category_id, amount, unit, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,1,?,?,1,1,?,'USD',?,?,?, '2026-09-07T01:00:00')""",
                (nk, day, seq, amt, f"he:{nk}:{amt}", src, batch))
E(con, 'src_a|e|2025-06-01|1', '2025-06-01', 50.0, batch=1)
E(con, 'src_a|e|2025-06-01|1', '2025-06-01', 60.0, batch=2)   # corrected re-load, no supersede marking
tot = con.execute("SELECT SUM(amount) FROM v_cash_flow WHERE event_date='2025-06-01'").fetchone()[0]
ok("day's cash flow = corrected batch only (60, not 110)", lambda: (_ for _ in ()).throw(AssertionError(f"{tot}"))
   if tot != 60.0 else None)

print("\n-- P11: UNMAPPED visible in cash flow with raw label exposed")
cols = [r[1] for r in con.execute("PRAGMA table_info(v_cash_flow)")]
ok("v_cash_flow exposes raw_label", lambda: (_ for _ in ()).throw(AssertionError()) if 'raw_label' not in cols else None)

print("\n-- P13: impossible ISO calendar dates rejected (roundtrip guard)")
for bad in ('2024-02-31','2023-02-30','2025-02-29'):   # 2025 is not a leap year
    fail(f"date {bad}", lambda b=bad: con.execute(
        "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, unit, content_hash, source_id, batch_id, ingested_at) "
        "VALUES (?,1,?,1,1,1,'USD','hx',1,1,'2026-09-07T01:00:00')", (f'e:{b}', b)))
ok("leap-day 2024-02-29 still accepted", lambda: con.execute(
    "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, unit, content_hash, source_id, batch_id, ingested_at) "
    "VALUES ('leap',1,'2024-02-29',1,1,1,'USD','hleap',1,1,'2026-09-07T01:00:00')"))

print("\n-- leg C NEW-C1: assumption_register versions per batch, current by max batch")
con.execute("""INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at)
               VALUES ('2026-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2032, '2026-trustees-report', '2026-09-06', 1, '2026-09-07T01:00:00')""")
con.execute("""INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at)
               VALUES ('2027-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2033, '2027-trustees-report', '2027-06-01', 4, '2026-09-07T02:00:00')""")
fail("same natural_key twice in one batch", lambda: con.execute(
    "INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at) "
    "VALUES ('2027-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2033, '2027-trustees-report', '2027-06-01', 4, '2026-09-07T02:00:00')"))
v = con.execute("SELECT value_num FROM v_assumption_current WHERE key='ssa.go_broke.year'").fetchone()
ok("current assumption = latest batch", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (2033,) else None)

print("\n-- leg C Q2d: filing_status vocabulary enforced (no silent-empty join)")
fail("filing_status 'Single'", lambda: con.execute(
    "INSERT INTO tax_year_facts(natural_key, tax_year, filing_status, source, is_estimate, as_of, source_id, batch_id, ingested_at) "
    "VALUES ('k',2027,'Single','estimate',1,'2026-09-06',1,1,'2026-09-07T01:00:00')"))
ok("filing_status 'single' accepted", lambda: con.execute(
    "INSERT INTO tax_year_facts(natural_key, tax_year, filing_status, source, is_estimate, as_of, source_id, batch_id, ingested_at) "
    "VALUES ('k',2027,'single','estimate',1,'2026-09-06',1,1,'2026-09-07T01:00:00')"))

print("\n-- dim_tax_bracket: schedules + estimate-sourced future bounds")
con.execute("INSERT INTO dim_tax_bracket(tax_year, filing_status, schedule, ordinal, upper_limit, rate, source, ingested_at) "
            "VALUES (2028,'single','ordinary',1,10000.0,0.10,'estimate','2026-09-07T01:00:00')")
con.execute("INSERT INTO dim_tax_bracket(tax_year, filing_status, schedule, ordinal, upper_limit, rate, source, ingested_at) "
            "VALUES (2028,'single','ltcg',1,50000.0,0.0,'estimate','2026-09-07T01:00:00')")
ok("ordinary + ltcg schedules coexist", lambda: (_ for _ in ()).throw(AssertionError())
   if con.execute("SELECT COUNT(*) FROM dim_tax_bracket WHERE tax_year=2028").fetchone()[0] != 2 else None)

print("\n-- polarity + needs_verify coverage")
fail("polarity 'gross' rejected", lambda: con.execute(
    "INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative, polarity) VALUES (2,'X',0,0,'gross')"))
cols = [r[1] for r in con.execute("PRAGMA table_info(position_lot)")]
ok("position_lot carries needs_verify", lambda: (_ for _ in ()).throw(AssertionError()) if 'needs_verify' not in cols else None)

print("\nBATTERY COMPLETE")
