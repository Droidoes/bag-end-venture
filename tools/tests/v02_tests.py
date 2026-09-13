#!/usr/bin/env python3
"""Adversarial test harness for the books.db schema. Reads the AUTHORITATIVE
tools/schema/books.sql (v0.2 lineage) — never a copied snapshot.

Reproduces leg 2's executed probe battery (B1..B7, M2..M6, m8, U-1, C1/C2) against
v0.2 on a fresh in-memory store. Synthetic fixtures only — no owner values.
Usage: python3 tools/tests/v02_tests.py   (exit 0 = all green)
"""
import sqlite3, sys, pathlib

DDL = pathlib.Path(__file__).parent / "../../tools/schema/books.sql"
SQL = DDL.read_text()

def fresh():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SQL)
    return con

def expect_ok(con, label, fn):
    try:
        fn(); print(f"  PASS  {label}")
    except Exception as e:
        print(f"  FAIL  {label}: {type(e).__name__}: {e}"); raise

def expect_fail(con, label, fn, match=None):
    try:
        fn()
    except Exception as e:
        if match and match not in str(e):
            print(f"  FAIL  {label}: wrong error: {e}"); raise
        print(f"  PASS  {label}  (rejected: {str(e)[:70]})"); return
    print(f"  FAIL  {label}: accepted, should have been rejected"); raise AssertionError(label)

def seed(con):
    con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (1, '2026-09-07T00:00:00', 'complete')")
    for sid, alias, prec in [(1,'src_a',10),(2,'src_b',90)]:
        con.execute("INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, precedence, role) VALUES (?,?,?,?,?,?,?)",
                    (sid, alias, f'd{sid}', 'native-google-sheet', 'sheets.values.get', prec, 'raw'))
    con.execute("INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (1,'A1','inst','taxable','Joe','growth')")
    con.execute("INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative) VALUES (1,'MKT',0,0)")
    con.execute("INSERT INTO dim_txn_type(txn_type_id, source_id, raw_label, canonical) VALUES (1,1,'UNMAPPED','UNMAPPED')")
    con.execute("INSERT INTO dim_category(category_id, source_id, source_label, canonical, spending_class) VALUES (1,1,'UNMAPPED','UNMAPPED','unsettled')")

def state_row(con, nk, acct=1, met=1, day='2025-06-30', seq=1, val=100.0, src=1, batch=1, grain='monthly', hsh=None, srow=None):
    con.execute("""INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, sheet_row_number,
                   value_num, period_grain, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (nk, acct, met, day, seq, srow, val, grain, hsh or f"c:{acct}:{met}:{day}:{val}", src, batch, '2026-09-07T01:00:00'))

print("== v0.2 adversarial harness ==")
n_fail = 0
def section(t): print(f"\n-- {t}")

con = fresh(); seed(con)

section("B1 — cross-source exact state duplicate blocked (content_hash UNIQUE)")
state_row(con, 'src_a|a1|m1|2025-06-30|1')
expect_fail(con, "identical row from second source", lambda: state_row(con, 'src_b|a1|m1|2025-06-30|1', src=2))

section("B1 — same-day pair with different values coexists")
state_row(con, 'src_a|a1|m1|2025-07-08|1', day='2025-07-08', val=100.0)
state_row(con, 'src_a|a1|m1|2025-07-08|2', day='2025-07-08', seq=2, val=125.0)
n = con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-07-08'").fetchone()[0]
expect_ok(con, "both pair rows stored", lambda: (_ for _ in ()).throw(AssertionError(f"{n} != 2")) if n != 2 else None)

section("B2/U-4 — precedence beats row order; two sources coexist for one day")
state_row(con, 'src_b|a1|m1|2025-09-30|1', day='2025-09-30', val=500.0, src=2)   # stale-ish file, precedence 90
state_row(con, 'src_a|a1|m1|2025-09-30|1', day='2025-09-30', val=512.0, src=1)   # corrected file, precedence 10
v = con.execute("SELECT value_num, source_id FROM v_state_current WHERE as_of='2025-09-30' AND metric_id=1").fetchone()
expect_ok(con, "corrected file wins regardless of seq", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (512.0, 1) else None)

section("B2c — TIPS-style pair: storage keeps both, view picks last-of-day")
v = con.execute("SELECT value_num FROM v_state_current WHERE as_of='2025-07-08' AND metric_id=1").fetchone()
expect_ok(con, "view returns the last event of the day", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (125.0,) else None)

section("B3 — re-ingest versions rows instead of aborting")
con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (2, '2026-09-07T02:00:00', 'complete')")
state_row(con, 'src_a|a1|m1|2025-06-30|1', val=110.0, batch=2)          # corrected value, new batch
con.execute("UPDATE fact_state SET superseded_by_batch_id=2 WHERE natural_key='src_a|a1|m1|2025-06-30|1' AND batch_id=1")
rows = con.execute("SELECT value_num, superseded_by_batch_id IS NOT NULL FROM fact_state WHERE as_of='2025-06-30' ORDER BY batch_id").fetchall()
expect_ok(con, "old row kept + marked superseded, new row current",
          lambda: (_ for _ in ()).throw(AssertionError(f"{rows}")) if rows != [(100.0, 1), (110.0, 0)] else None)
v = con.execute("SELECT value_num FROM v_state_current WHERE as_of='2025-06-30'").fetchone()
expect_ok(con, "view reads the corrected value", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (110.0,) else None)

section("B5 — full role vocabulary + unresolved headers are storable")
con.execute("INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, precedence, role) VALUES (3,'src_c','d3','native-google-sheet','sheets.values.get',50,'duplicate')")
expect_ok(con, "source-level 'duplicate' role stored", lambda: None)
for role in ('derived','scratch','worksheet','deferred'):
    con.execute("INSERT INTO src_tab(source_id, tab, role, header_state, dedupe_rule, row_order) VALUES (1, ?, ?, 'not-applicable','none','unsorted')", (f"tab_{role}", role))
expect_ok(con, "tab roles derived/scratch/worksheet/deferred stored", lambda: None)
con.execute("INSERT INTO src_tab(source_id, tab, role, header_state, dedupe_rule, row_order) VALUES (1,'tab_unres','raw','unresolved','disjoint_by_key','ascending-date')")
expect_ok(con, "unresolved header state stored", lambda: None)
expect_fail(con, "confirmed without header_row", lambda: con.execute(
    "INSERT INTO src_tab(source_id, tab, role, header_state, dedupe_rule, row_order) VALUES (1,'tab_bad','raw','confirmed','disjoint_by_key','ascending-date')"))

section("B6.2 — re-application fails loudly (no IF NOT EXISTS)")
con2 = sqlite3.connect(":memory:")
con2.executescript(SQL)
expect_fail(con2, "second apply raises", lambda: con2.executescript(SQL), match="already exists")

section("B6.4 — classification CHECKs fire, no permissive defaults")
expect_fail(con, "entity 'LLC ' (trailing space)", lambda: con.execute(
    "INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (9,'A9','i','taxable','LLC ','growth')"))
expect_fail(con, "entity NULL", lambda: con.execute(
    "INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (9,'A9','i','taxable',NULL,'growth')"))
expect_fail(con, "registration 'Rollover IRA'", lambda: con.execute(
    "INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (9,'A9','i','Rollover IRA','Joe','growth')"))
expect_fail(con, "purpose NULL", lambda: con.execute(
    "INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (9,'A9','i','taxable','Joe',NULL)"))

section("B6.5 — is_informational lives once, v_cash_flow enforces the exclusion")
cols = [r[1] for r in con.execute("PRAGMA table_info(fact_event)")]
expect_ok(con, "no is_informational on fact_event", lambda: (_ for _ in ()).throw(AssertionError()) if 'is_informational' in cols else None)
con.execute("INSERT INTO dim_txn_type(txn_type_id, source_id, raw_label, canonical, is_informational) VALUES (2,1,'Balance Forward','BALANCE_FORWARD',1)")
con.execute("""INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, amount, unit, content_hash, source_id, batch_id, ingested_at)
               VALUES ('e1',1,'2025-06-01',1,2,1,100.0,'USD','he1',1,1,'2026-09-07T01:00:00')""")
expect_ok(con, "informational event row excluded from v_cash_flow",
          lambda: (_ for _ in ()).throw(AssertionError()) if con.execute("SELECT COUNT(*) FROM v_cash_flow").fetchone()[0] != 0 else None)

section("M2 — strict date guard rejects the corpus's real malformed values")
for bad in ('5/3/2025','4/31/2020','2025-5-3',' 1/22/2021','45720','2019'):
    expect_fail(con, f"date {bad!r}", lambda b=bad: con.execute(
        "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, unit, content_hash, source_id, batch_id, ingested_at) "
        "VALUES (?,1,?,1,1,1,'USD','h',1,1,'2026-09-07T01:00:00')", (f'e:{b}', b)), match="CHECK")
expect_ok(con, "ISO date accepted", lambda: con.execute(
    "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, unit, content_hash, source_id, batch_id, ingested_at) "
    "VALUES ('ok1',1,'2025-05-03',1,1,1,'USD','hok1',1,1,'2026-09-07T01:00:00')"))

section("M4 — two SSA sources for one work year coexist (source-scoped natural key)")
for nk, v in [('src:od|2020', 1000.0), ('src:pe|2020', 2000.0)]:   # synthetic fixtures only (hygiene R6)
    con.execute("""INSERT INTO ss_earnings_annual(natural_key, work_year, ss_taxed, source_id, batch_id, ingested_at)
                   VALUES (?,2020,?,1,1,'2026-09-07T01:00:00')""", (nk, v))
expect_ok(con, "both 2020 rows retained", lambda: (_ for _ in ()).throw(AssertionError())
          if con.execute("SELECT COUNT(*) FROM ss_earnings_annual WHERE work_year=2020").fetchone()[0] != 2 else None)

section("M5 — UNMAPPED sentinel, per-source label UNIQUE, NULL type rejected")
expect_fail(con, "txn_type_id NULL", lambda: con.execute(
    "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, unit, content_hash, source_id, batch_id, ingested_at) "
    "VALUES ('e2',1,'2025-06-02',1,NULL,1,'USD','he2',1,1,'2026-09-07T01:00:00')"))
expect_fail(con, "duplicate raw_label in same source", lambda: con.execute(
    "INSERT INTO dim_txn_type(source_id, raw_label, canonical) VALUES (1,'UNMAPPED','OTHER')"))
expect_ok(con, "same label in different source OK", lambda: con.execute(
    "INSERT INTO dim_txn_type(source_id, raw_label, canonical) VALUES (2,'UNMAPPED','UNMAPPED')"))

section("M6 — lots: same security/date discriminated by lot_seq; null opened_on no longer triples")
con.execute("INSERT INTO dim_security(security_id, ticker) VALUES (1,'NEU')")
for seq in (1, 2, 3):
    con.execute("""INSERT INTO position_lot(natural_key, account_id, security_id, lot_seq, cost_basis, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,1,1,?,100.0,'hl',1,1,'2026-09-07T01:00:00')""", (f'lot|null|{seq}', seq))
expect_ok(con, "three null-opened_on lots stored", lambda: (_ for _ in ()).throw(AssertionError())
          if con.execute("SELECT COUNT(*) FROM position_lot").fetchone()[0] != 3 else None)
expect_fail(con, "same natural_key twice in one batch", lambda: con.execute(
    """INSERT INTO position_lot(natural_key, account_id, security_id, lot_seq, cost_basis, content_hash, source_id, batch_id, ingested_at)
       VALUES ('lot|null|1',1,1,1,100.0,'hl2',1,1,'2026-09-07T01:00:00')"""))

section("m8 — typeof CHECKs: text never masquerades as REAL")
for bad in ('1,234.56', '(45.00)', 'N/A', 'abc'):
    expect_fail(con, f"amount {bad!r}", lambda b=bad: con.execute(
        "INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id, category_id, amount, unit, content_hash, source_id, batch_id, ingested_at) "
        "VALUES (?,1,'2025-06-03',1,1,1,?,'USD','hx',1,1,'2026-09-07T01:00:00')", (f'e:{b}', b)))

section("U-1 — spending_class vocabulary")
expect_fail(con, "spending_class 'food' rejected", lambda: con.execute(
    "INSERT INTO dim_category(source_id, source_label, canonical, spending_class) VALUES (1,'Groc','Groceries','food')"))
expect_ok(con, "spending_class 'floor' accepted", lambda: con.execute(
    "INSERT INTO dim_category(source_id, source_label, canonical, spending_class) VALUES (1,'Rent','Rent','floor')"))

section("C2/U-3 — v_net_worth aggregates across accounts at month-end grain")
con.execute("INSERT INTO dim_account(account_id, code, institution, registration, entity, purpose) VALUES (2,'A2','inst2','401k','Joe','growth')")
state_row(con, 'src_a|a1|m1|2025-12-31|1', acct=1, day='2025-12-31', val=100.0)
state_row(con, 'src_a|a2|m1|2025-12-31|1', acct=2, day='2025-12-31', val=200.0)
state_row(con, 'src_a|a1|m1|2025-12-26|1', acct=1, day='2025-12-26', val=999.0, grain='weekly')
row = con.execute("SELECT total, n_components FROM v_net_worth WHERE as_of='2025-12-31' AND metric_id=1").fetchone()
expect_ok(con, "month-end total = 300 across 2 accounts, weekly row excluded",
          lambda: (_ for _ in ()).throw(AssertionError(f"{row}")) if row != (300.0, 2) else None)

section("M1 — exactly-one value; presence vocabulary")
expect_fail(con, "value_num AND value_text both NULL", lambda: con.execute(
    "INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, period_grain, content_hash, source_id, batch_id, ingested_at) "
    "VALUES ('x1',1,1,'2025-01-01',1,'monthly','hx1',1,1,'2026-09-07T01:00:00')"))
expect_ok(con, "text value with presence='error' stored honestly", lambda: con.execute(
    "INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, value_text, presence, period_grain, content_hash, source_id, batch_id, ingested_at) "
    "VALUES ('x2',1,1,'2025-01-02',1,'pending','error','monthly','hx2',1,1,'2026-09-07T01:00:00')"))

section("coverage_calendar — three absence states, FK to alias")
for st in ('not-loaded','loaded-empty','absent-in-source','loaded'):
    con.execute("INSERT OR REPLACE INTO coverage_calendar(source_alias, tab, period, status) VALUES ('src_a', ?, '2025', ?)", (f't{st}', st))
expect_ok(con, "all four statuses stored", lambda: None)
expect_fail(con, "typo'd alias rejected (FK)", lambda: con.execute(
    "INSERT INTO coverage_calendar(source_alias, period, status) VALUES ('src_zz','2025','loaded')"))
expect_fail(con, "garbage period rejected", lambda: con.execute(
    "INSERT INTO coverage_calendar(source_alias, period, status) VALUES ('src_a','202X','loaded')"))

section("data_defects — verification honesty")
expect_fail(con, "FIXED-VERIFIED without verified_at", lambda: con.execute(
    "INSERT INTO data_defects(source_alias, tab, what, evidence, status) VALUES ('src_a','t','w','e','FIXED-VERIFIED')"))

section("m4 — source_kind/read_path pairing enforced")
expect_fail(con, "native sheet with files.get", lambda: con.execute(
    "INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, role) VALUES (8,'src_x','d','native-google-sheet','files.get alt=media','raw')"))

section("schema meta + assumption register (versionable)")
v = con.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()
# Version-agnostic: read the expectation from the loader rather than pinning a
# literal. The pin broke on every schema bump and was the reason this battery was
# skipped during the v0.2.5 change (COS, 2026-09-12).
sys.path.insert(0, "tools")
from bagend.loader21 import SCHEMA_VERSION as _EXPECTED
expect_ok(con, f"schema_version = {_EXPECTED}", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (_EXPECTED,) else None)
con.execute("INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at) "
            "VALUES ('2026-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2099, '2026-trustees-report', '2026-09-06', 1, '2026-09-07T01:00:00')")
expect_fail(con, "same natural_key twice in one batch", lambda: con.execute(
    "INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at) "
    "VALUES ('2026-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2099, '2026-trustees-report', '2026-09-06', 1, '2026-09-07T01:00:00')"))
expect_ok(con, "new vintage of the same key in a later batch coexists", lambda: con.execute(
    "INSERT INTO assumption_register(natural_key, key, value_num, source, as_of, batch_id, ingested_at) "
    "VALUES ('2027-trustees-report|ssa.go_broke.year', 'ssa.go_broke.year', 2100, '2027-trustees-report', '2027-06-01', 2, '2026-09-07T01:00:00')"))
v = con.execute("SELECT value_num FROM v_assumption_current WHERE key='ssa.go_broke.year'").fetchone()
expect_ok(con, "current assumption = latest batch", lambda: (_ for _ in ()).throw(AssertionError(f"{v}")) if v != (2100,) else None)
expect_fail(con, "assumption both values set", lambda: con.execute(
    "INSERT INTO assumption_register(natural_key, key, value_num, value_text, source, as_of, batch_id, ingested_at) "
    "VALUES ('k2', 'k2', 1.0, 'x', 's', '2026-09-06', 1, '2026-09-07T01:00:00')"))

section("B6.1 — FK pragma is per-connection (loader's assert is the enforcement point)")
con3 = sqlite3.connect(":memory:")
con3.executescript(SQL)   # pragma NOT set on this connection
orphaned = None
try:
    con3.execute("INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date, value_num, period_grain, content_hash, source_id, batch_id, ingested_at) "
                 "VALUES ('o1',77,77,'2025-01-01',1,1.0,'monthly','ho1',77,77,'2026-09-07T01:00:00')")
    orphaned = "inserted without FK enforcement"
except sqlite3.IntegrityError:
    orphaned = "blocked"
print(f"  INFO  no-pragma connection: {orphaned} (expected: inserted — loader MUST assert pragma + version)")

print("\nALL GREEN" if True else "", end="")
print("\nHarness complete.")
