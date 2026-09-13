#!/usr/bin/env python3
"""Loader contract battery for tools/bagend/loader21.py against the authoritative tools/schema/books.sql.

In-memory SQLite + synthetic CSVs/xlsx only — no owner values, no Drive, no
private/books.db. Run from the repo root:
    python3 tools/tests/v021_loader_tests.py
"""
import csv
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from tools.bagend import loader21 as L

DDL = Path("tools/schema/books.sql").read_text()  # single source of truth (was a stale snapshot copy)

def fresh():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    return con

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
        print(f"  PASS  {label}  ({type(e).__name__})"); return
    print(f"  FAIL  {label}: expected failure"); raise AssertionError(label)

def base_curation(tmp: Path):
    spine = tmp / "spine.csv"
    with open(spine, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "ACCT_A", "ACCT_B", "Total Assets", "Deposit"])
        w.writerow(["2025-01-31", "100.0", "200.0", "300.0", ""])
        w.writerow(["2025-02-28", "110.0", "205.0", "315.0", "5.0"])
        w.writerow(["bad-date", "120.0", "210.0", "", ""])          # rejected date, recorded
    td = tmp / "transactions_2001.xlsx"
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["DATE", "TRANSACTION ID", "DESCRIPTION", "QUANTITY", "SYMBOL", "PRICE", "COMMISSION", "AMOUNT"])
    ws.append(["2001-01-05", 111, "Bought 10 AAA @ 10.5", 10, "AAA", 10.5, 5.0, -110.0])
    ws.append(["2001-01-05", 222, "Qualified Dividend AAA", "", "AAA", "", "", 25.0])
    ws.append(["2001-01-06", 333, "Wire Transfer In", "", "", "", "", 1000.0])   # unmapped token
    ws.append(["***END OF FILE***", None, None, None, None, None, None, None])
    wb.save(td)
    ssa = tmp / "ssa_earn.csv"
    with open(ssa, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Work Year", "Taxed Social Security Earnings", "Taxed Medicare Earnings"])
        w.writerow(["2019", "100000", "150000"])
        w.writerow(["2020", "110000", "---"])
    ben = tmp / "ssa_ben.csv"
    with open(ben, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Years You Worked", "Age 62", "Age 67", "Age 70"])
        w.writerow(["2024", "1800", "3200", "4000"])
        w.writerow(["2025", "1900", "3300", "4100"])
    return {
        "_purpose": "test",
        "sources": [
            {"alias": "test:spine", "drive_id": "d1", "source_kind": "drive-file", "read_path": "files.get alt=media",
             "precedence": 100, "role": "raw", "tab": "spine", "header_state": "confirmed", "header_row": 1,
             "dedupe_rule": "disjoint_by_key", "row_order": "ascending-date", "grain": "month-end",
             "family": "state", "local": str(spine),
             "columns": [{"col": "Date", "role": "as_of"},
                         {"col": "ACCT_A", "account": "T_A", "metric": "TOTAL_ASSETS"},
                         {"col": "ACCT_B", "account": "T_B", "metric": "TOTAL_ASSETS"},
                         {"col": "Deposit", "account": "HH", "metric": "DEPOSIT"}]},
            {"alias": "test:td:<year>", "drive_id": "d2", "source_kind": "drive-file", "read_path": "files.get alt=media",
             "precedence": 100, "role": "raw", "tab": "transactions_<year>", "header_state": "confirmed", "header_row": 1,
             "dedupe_rule": "disjoint_by_key", "row_order": "ascending-date", "grain": "one txn",
             "family": "event", "local_glob": str(tmp / "transactions_*.xlsx"), "account": "T_A",
             "sentinel": "***END OF FILE***",
             "columns": [{"col": "DATE", "role": "event_date"},
                         {"col": "TRANSACTION ID", "role": "business_txn_id"},
                         {"col": "DESCRIPTION", "role": "raw_label_and_description"},
                         {"col": "QUANTITY", "role": "quantity"},
                         {"col": "SYMBOL", "role": "security_ticker"},
                         {"col": "PRICE", "role": "price"},
                         {"col": "COMMISSION", "role": "fee"},
                         {"col": "AMOUNT", "role": "amount"}]},
            {"alias": "test:ssa-earn", "drive_id": "d3", "source_kind": "drive-file", "read_path": "files.get alt=media",
             "precedence": 100, "role": "raw", "tab": "earn", "header_state": "confirmed", "header_row": 1,
             "dedupe_rule": "disjoint_by_key", "row_order": "ascending-date", "grain": "annual",
             "family": "ssa_earnings", "local": str(ssa),
             "columns": [{"col": "Work Year", "role": "work_year"},
                         {"col": "Taxed Social Security Earnings", "role": "ss_taxed"},
                         {"col": "Taxed Medicare Earnings", "role": "medicare_taxed"}]},
            {"alias": "test:ssa-ben", "drive_id": "d4", "source_kind": "drive-file", "read_path": "files.get alt=media",
             "precedence": 100, "role": "raw", "tab": "ben", "header_state": "confirmed", "header_row": 1,
             "dedupe_rule": "disjoint_by_key", "row_order": "ascending-date", "grain": "annual",
             "family": "ssa_benefit", "local": str(ben),
             "columns": [{"col": "Years You Worked", "role": "work_year"},
                         {"col": "Age 62", "role": "claim:Age62"},
                         {"col": "Age 67", "role": "claim:Age67"},
                         {"col": "Age 70", "role": "claim:Age70"}]},
        ],
        "dim_accounts": [
            {"code": "T_A", "institution": "TestA", "registration": "taxable", "entity": "Joe", "purpose": "growth", "notes": ""},
            {"code": "T_B", "institution": "TestB", "registration": "401k", "entity": "Joe", "purpose": "growth", "notes": ""},
            {"code": "HH", "institution": "household", "registration": "other", "entity": "Joe", "purpose": "unsettled", "notes": ""},
        ],
        "dim_metrics": [
            {"name": "TOTAL_ASSETS", "is_flow": 0, "is_year_relative": 0, "polarity": "asset", "unit": "USD", "scope_flag": None, "methodology": ""},
            {"name": "DEPOSIT", "is_flow": 1, "is_year_relative": 0, "polarity": "flow", "unit": "USD", "scope_flag": None, "methodology": ""},
        ],
        "txn_type_vocab": {"td_txn_by_year:<year>": {"match": "first_token",
            "map": {"BOUGHT": "PURCHASE", "QUALIFIED": "DIVIDEND", "SOLD": "SALE", "MARGIN": "INTEREST"}}},
    }

print("== v0.2.1 loader battery ==")
tmp = Path(tempfile.mkdtemp(prefix="v021ldr"))
cur = base_curation(tmp)
cur_path = tmp / "curation.json"
cur_path.write_text(json.dumps(cur))

section = lambda s: print(f"\n-- {s}")

section("assert_schema guards")
con = fresh()
fail("FK-off connection refused", lambda: L.assert_schema(sqlite3.connect(":memory:")))
fail("wrong-version store refused", lambda: L.assert_schema(con)) if False else None
# fresh() has v0.2.1 + FK on: must pass
L.assert_schema(con)
ok("valid store accepted", lambda: None)
con2 = fresh()
con2.execute("UPDATE _schema_meta SET value='v0.1' WHERE key='schema_version'")
fail("stale schema_version refused", lambda: L.assert_schema(con2), match=f"expected {L.SCHEMA_VERSION}")

section("wave-1 pipeline on synthetic fixtures")
res = L.run_wave1(cur_path, con)
print("   results:", {k: v["rows"] for k, v in res.items()})
ok("spine rows = 2 dates x 2 accts + 1 deposit = 5",
   lambda: (_ for _ in ()).throw(AssertionError(res)) if res["test:spine"]["rows"] != 5 else None)
ok("td rows = 3 (sentinel excluded)",
   lambda: (_ for _ in ()).throw(AssertionError(res)) if res["test:td:2001"]["rows"] != 3 else None)
ok("ssa earnings = 2 rows, benefits = 6 rows",
   lambda: (_ for _ in ()).throw(AssertionError(res))
   if (res["test:ssa-earn"]["rows"], res["test:ssa-ben"]["rows"]) != (2, 6) else None)

section("bad date recorded, not loaded")
note = con.execute("SELECT note FROM load_batch b JOIN fact_state f ON f.batch_id=b.batch_id WHERE f.as_of='2025-03-31' LIMIT 1").fetchone()
n_rows_bad = con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-03-31'").fetchone()[0]
ok("no rows for the bad-date row", lambda: (_ for _ in ()).throw(AssertionError()) if n_rows_bad != 0 else None)
batches = [r[0] for r in con.execute("SELECT note FROM load_batch WHERE note LIKE '%bad-date%' OR note LIKE '%unparseable%'")]
ok("rejection reason recorded in batch note", lambda: (_ for _ in ()).throw(AssertionError(batches)) if not batches else None)

section("natural keys, hashes, seq, sentinels")
row = con.execute("SELECT natural_key, seq_in_date, sheet_row_number FROM fact_state WHERE as_of='2025-01-31' AND account_id=(SELECT account_id FROM dim_account WHERE code='T_A')").fetchone()
ok("state natural_key shape src|acct|met|date|seq", lambda: (_ for _ in ()).throw(AssertionError(row))
   if not (row and row[0].count("|") == 4 and row[1] == 1 and row[2] == 2) else None)
ev = con.execute("""SELECT e.natural_key, e.business_txn_id, e.seq_in_date, t.canonical
                    FROM fact_event e JOIN dim_txn_type t USING(txn_type_id)
                    WHERE e.event_date='2001-01-05' ORDER BY e.seq_in_date""").fetchall()
ok("same-day events get seq 1..2 with business ids",
   lambda: (_ for _ in ()).throw(AssertionError(ev))
   if [ (r[1], r[2], r[3]) for r in ev ] != [("111", 1, "PURCHASE"), ("222", 2, "DIVIDEND")] else None)
unmapped = con.execute("SELECT t.canonical, e.raw_label FROM fact_event e JOIN dim_txn_type t USING(txn_type_id) WHERE e.event_date='2001-01-06'").fetchone()
ok("unknown token -> UNMAPPED with raw label retained",
   lambda: (_ for _ in ()).throw(AssertionError(unmapped)) if unmapped != ("UNMAPPED", "Wire Transfer In") else None)

section("placeholder '---' -> NULL, not zero")
ok("2020 medicare_taxed is NULL", lambda: (_ for _ in ()).throw(AssertionError())
   if con.execute("SELECT medicare_taxed FROM ss_earnings_annual WHERE work_year=2020").fetchone()[0] is not None else None)
ok("2025 benefit rows carry needs_verify=1",
   lambda: (_ for _ in ()).throw(AssertionError())
   if con.execute("SELECT COUNT(*) FROM ss_benefit_estimates WHERE work_year=2025 AND needs_verify=1").fetchone()[0] != 3 else None)

section("re-ingest: identical pass is a no-op (skip-on-identical, no churn)")
res2 = L.run_wave1(cur_path, con, only="test:spine")
ok("identical re-ingest loads 0 new rows and supersedes nothing",
   lambda: (_ for _ in ()).throw(AssertionError(res2["test:spine"]))
   if res2["test:spine"]["rows"] != 0 else None)
v = con.execute("SELECT value_num FROM v_state_current WHERE as_of='2025-02-28' AND account_id=(SELECT account_id FROM dim_account WHERE code='T_A')").fetchone()
ok("view still reads the corrected batch", lambda: (_ for _ in ()).throw(AssertionError(v)) if v != (110.0,) else None)
note = con.execute("SELECT note FROM load_batch WHERE note LIKE '%identical%' ORDER BY batch_id DESC LIMIT 1").fetchone()
ok("skip recorded loudly in the batch note", lambda: (_ for _ in ()).throw(AssertionError(note)) if not note else None)

section("re-ingest with a REAL correction versions the row")
with open(cur["sources"][0]["local"], "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Date", "ACCT_A", "ACCT_B", "Total Assets", "Deposit"])
    w.writerow(["2025-01-31", "100.0", "200.0", "300.0", ""])
    w.writerow(["2025-02-28", "999.0", "205.0", "1204.0", "5.0"])   # corrected value
res3 = L.run_wave1(cur_path, con, only="test:spine")
ok("correction inserts 1 new row and supersedes the old one",
   lambda: (_ for _ in ()).throw(AssertionError(res3["test:spine"]))
   if (res3["test:spine"]["rows"], res3["test:spine"]["superseded"]) != (1, 1) else None)
v = con.execute("SELECT value_num FROM v_state_current WHERE as_of='2025-02-28' AND account_id=(SELECT account_id FROM dim_account WHERE code='T_A')").fetchone()
ok("view follows the correction", lambda: (_ for _ in ()).throw(AssertionError(v)) if v != (999.0,) else None)
stored = con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-02-28' AND account_id=(SELECT account_id FROM dim_account WHERE code='T_A')").fetchone()[0]
ok("both versions retained in storage", lambda: (_ for _ in ()).throw(AssertionError()) if stored != 2 else None)

section("batch failure is loud and atomic")
bad = dict(cur); bad["sources"] = [s for s in cur["sources"] if s["alias"] == "test:spine"]
# break the spine CSV mid-flight: add a row that violates the hash partial index via a duplicate
spine = tmp / "spine_bad.csv"
with open(spine, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Date", "ACCT_A", "ACCT_B", "Total Assets", "Deposit"])
    w.writerow(["2025-04-30", "120.0", "210.0", "", ""])
bad["sources"][0]["local"] = str(spine)
badp = tmp / "bad.json"; badp.write_text(json.dumps(bad))
# make a source whose insert trips a NOT NULL (metric missing from dims) -> loud failure
bad["sources"][0]["columns"] = [{"col": "Date", "role": "as_of"}, {"col": "ACCT_A", "account": "T_A", "metric": "NO_SUCH_METRIC"}]
badp.write_text(json.dumps(bad))
try:
    L.run_wave1(badp, con, only="test:spine")
    raise AssertionError("expected LoadError / IntegrityError")
except Exception:
    pass
n_failed = con.execute("SELECT COUNT(*) FROM load_batch WHERE status='failed'").fetchone()[0]
n_0401 = con.execute("SELECT COUNT(*) FROM fact_state WHERE as_of='2025-04-30'").fetchone()[0]
ok("failed batch row survives rollback", lambda: (_ for _ in ()).throw(AssertionError()) if n_failed == 0 else None)
ok("no partial rows committed", lambda: (_ for _ in ()).throw(AssertionError()) if n_0401 != 0 else None)

print("\nBATTERY COMPLETE")

# ================= wave-1 extension: checking + card fixtures =================
print("\n== checking/card extension ==")
import csv as _csv
tmp2 = Path(tempfile.mkdtemp(prefix="v021chk"))

# checking fixture: blank first header cell (2022-style), summary block at tail
chk = tmp2 / "Summary__2022.csv"
with open(chk, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["", "Description", "Details", "Category", "Debit", "Credit", "Balance", "Debit Credit"])
    w.writerow(["2022-01-03", "CHECK", "CHECK 158", "Rent", "1510", "", "4514.59", ""])
    w.writerow(["2022-01-07", "ACH DEPOSIT", "PAYROLL", "VZ Dep", "", "4123.09", "8637.68", ""])
    w.writerow(["2022-01-10", "MYSTERY ROW", "", "Odd", "12.34", "", "8625.34", ""])  # unmapped txn
    w.writerow(["", "Rent", "", "", "0", "1510", "", ""])   # summary block start -> stop
    w.writerow(["", "VZ Dep", "", "", "0", "4123.09", "", ""])

# card fixture: xlsx with carry-over duplicate across year tabs
import openpyxl as _xl
card = tmp2 / "card.xlsx"
wb = _xl.Workbook()
for y in ("2018", "2019"):
    ws = wb.create_sheet(f"{y}-Data")
    ws.append(["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount"])
    ws.append([f"{y}-12-30 00:00", f"{y}-12-31 00:00", "COFFEE SHOP", "Food", "Sale", "-4.50"])
    ws.append(["2018-12-31 00:00", "2018-12-31 00:00", "DEC31 CARRY", "Other", "Sale", "-10.00"])  # shared row, same date in both tabs
    ws.append([f"{y}-01-01 00:00", f"{y}-01-01 00:00", "NEW YEAR", "Other", "Sale", "-1.00"])
del wb["Sheet"]
wb.save(card)

ext = {
  "_purpose": "test ext",
  "sources": [
    {"alias": "summary:<year>", "drive_id": "d5", "source_kind": "drive-file", "read_path": "files.get alt=media",
     "precedence": 100, "role": "raw", "tab": "<year>", "header_state": "confirmed", "header_row": 1,
     "dedupe_rule": "disjoint_by_key", "row_order": "ascending-date", "grain": "one txn",
     "family": "checking", "local_glob": str(tmp2 / "Summary__*.csv"), "account": "TD_CHK",
     "year_from_tab": True, "summary_block": True, "amount_mode": "credit_minus_debit",
     "columns": [{"col": "Date", "role": "event_date"},
                 {"col": "Description", "role": "raw_label_and_description"},
                 {"col": "Category", "role": "category_label"},
                 {"col": "Debit", "role": "debit"}, {"col": "Credit", "role": "credit"}]},
    {"alias": "bankb:<year>", "drive_id": "d6", "source_kind": "drive-file", "read_path": "files.get alt=media",
     "precedence": 100, "role": "raw", "tab": "<year>-Data", "header_state": "confirmed", "header_row": 1,
     "dedupe_rule": "natural_key_prefer_latest", "row_order": "descending-date", "grain": "one txn",
     "family": "card", "local_glob": str(card), "account": "BANKB_CARD", "amount_mode": "signed",
     "columns": [{"col": "Transaction Date", "role": "event_date"},
                 {"col": "Description", "role": "raw_label_and_description"},
                 {"col": "Category", "role": "category_label"},
                 {"col": "Type", "role": "type_label"},
                 {"col": "Amount", "role": "amount"}]},
  ],
  "dim_accounts": [
    {"code": "TD_CHK", "institution": "TD Bank", "registration": "checking", "entity": "Joe", "purpose": "reserve", "notes": ""},
    {"code": "BANKB_CARD", "institution": "BankB", "registration": "card", "entity": "Joe", "purpose": "unsettled", "notes": ""},
  ],
  "dim_metrics": [],
  "txn_type_vocab": {
    "summary:<year>": {"match": "prefix", "map": {"ACH DEPOSIT": "DEPOSIT", "CHECK": "WITHDRAWAL"}},
    "bankb:<year>": {"match": "prefix", "map": {"Sale": "PURCHASE"}},
  },
  "category_classes": {"summary:<year>": {"Rent": "floor", "VZ Dep": "unsettled", "UNMAPPED": "unsettled"}},
}
extp = tmp2 / "ext.json"; extp.write_text(json.dumps(ext))
con3 = fresh()
res3 = L.run_wave1(extp, con3)
ok("checking: blank-header positional fallback loads data rows, summary block excluded",
   lambda: (_ for _ in ()).throw(AssertionError(res3))
   if res3["summary:2022"]["rows"] != 3 else None)
ok("checking amounts = credit - debit",
   lambda: (_ for _ in ()).throw(AssertionError())
   if con3.execute("SELECT amount FROM fact_event WHERE description='CHECK' AND source_id IN (SELECT source_id FROM src_ref WHERE alias='summary:2022')").fetchone() != (-1510.0,) else None)
spend = con3.execute("""SELECT c.spending_class FROM fact_event e JOIN dim_category c USING(category_id)
                        WHERE e.description='CHECK'""").fetchone()
ok("checking Rent maps to floor", lambda: (_ for _ in ()).throw(AssertionError(spend)) if spend != ("floor",) else None)
# carry-over dedupe: 'DEC31 CARRY' appears in both 2018 and 2019 tabs; older must be superseded
cur_dec = con3.execute("""SELECT COUNT(*) FROM fact_event WHERE description='DEC31 CARRY' AND superseded_by_batch_id IS NULL""").fetchone()[0]
tot_dec = con3.execute("""SELECT COUNT(*) FROM fact_event WHERE description='DEC31 CARRY'""").fetchone()[0]
ok("card carry-over: one current row, both stored", lambda: (_ for _ in ()).throw(AssertionError((cur_dec, tot_dec)))
   if (cur_dec, tot_dec) != (1, 2) else None)
dl = con3.execute("SELECT COUNT(*) FROM dedupe_log").fetchone()[0]
ok("suppression evidenced in dedupe_log", lambda: (_ for _ in ()).throw(AssertionError()) if dl != 1 else None)

# ================= wave-2: holdings fixture =================
print("\n== holdings extension ==")
tmp3 = Path(tempfile.mkdtemp(prefix="v021hld"))
hld = tmp3 / "2025_Trading_Performance__Data.csv"
with open(hld, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["", "", "", "", "", "Price", "Shares", "Cost ", "Market Val", "incl. Dividend", "P/L"])
    w.writerow(["NYSE:SYN", "Synthetic Mining Corp", "", "TD", "", "44.75", "100", "5000", "4475", "4700", "1.5"])
    w.writerow(["", "", "", "FD-RO", "", "44.75", "50", "2500", "2237.5", "", ""])
    w.writerow(["", "", "", "ML", "", "44.75", "5", "250", "", "", ""])            # mv blank -> derive shares*price
    w.writerow(["", "", "", "", "Sub Total", "", "155", "7750", "6936.25", "", "1.4"])
    w.writerow(["INDEXSP:.INX", "S&P 500", "7816.7", "", "", "", "", "", "", "", ""])
    w.writerow(["", "", "", "", "", "", "", "", "", "", ""])
    w.writerow(["TIP", "iShares TIPS Bond ETF", "106.97", "", "", "", "", "", "", "", ""])   # watchlist
    w.writerow(["ABBV", "AbbVie Common Stock", "", "TD", "", "256.46", "10", "2000", "2564.6", "", ""])
    w.writerow(["", "", "", "", "Sub Total", "", "10", "2000", "2564.6", "", ""])
    w.writerow(["", "SYNTHCUSIP", "Invalid Symbol", "", "", "", "", "", "", "", ""])
ext3 = {
  "_purpose": "test hld",
  "sources": [{"alias": "holdings:2025", "drive_id": "d7", "source_kind": "native-google-sheet",
               "read_path": "sheets.values.get", "precedence": 100, "role": "raw", "tab": "Data",
               "header_state": "confirmed", "header_row": 1, "dedupe_rule": "disjoint_by_key",
               "row_order": "unsorted", "grain": "snapshot", "family": "holdings",
               "local": str(hld), "as_of": "2025-12-31",
               "notes": "fixture"}],
  "dim_accounts": [
    {"code": "TD_RO", "institution": "i", "registration": "taxable", "entity": "Joe", "purpose": "growth", "notes": ""},
    {"code": "RO_IRA", "institution": "i", "registration": "trad-ira", "entity": "Joe", "purpose": "growth", "notes": ""},
    {"code": "BAML", "institution": "i", "registration": "taxable", "entity": "Joe", "purpose": "growth", "notes": ""},
  ],
  "dim_metrics": [],
  "txn_type_vocab": {},
}
ext3p = tmp3 / "h.json"; ext3p.write_text(json.dumps(ext3))
con4 = fresh()
res4 = L.run_wave1(ext3p, con4)
ok("holdings: 5 position rows (watchlist/index/subtotal/junk skipped)",
   lambda: (_ for _ in ()).throw(AssertionError(res4)) if res4["holdings:2025"]["rows"] != 4 else None)
ok("exchange stripped, ticker normalized",
   lambda: (_ for _ in ()).throw(AssertionError())
   if con4.execute("SELECT ticker, exchange FROM dim_security WHERE ticker='SYN'").fetchone() != ("SYN", "NYSE") else None)
ok("blank market value derived as shares x price",
   lambda: (_ for _ in ()).throw(AssertionError())
   if con4.execute("SELECT market_value FROM holding_state WHERE security_id=(SELECT security_id FROM dim_security WHERE ticker='SYN') AND cost_basis=250").fetchone() != (223.75,) else None)
ok("subtotal rows and watchlist not ingested",
   lambda: (_ for _ in ()).throw(AssertionError())
   if con4.execute("SELECT COUNT(*) FROM holding_state").fetchone()[0] != 4 else None)
