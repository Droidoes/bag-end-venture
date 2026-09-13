#!/usr/bin/env python3
"""P0 schema-parity harness — blueprint v0.3 §8 row P0. Offline, stdlib only.

What it proves, per case:
  1. tools/schema/books.sql applies to a FRESH temp DB and stamps v0.2.5; the
     loader's version assertion accepts it.
  2. Every new column and CHECK exists in sqlite_master (DDL text inspection +
     PRAGMA table_info), and the four composite pair-CHECK bodies are literally
     identical to each other.
  3. The extended presence CHECK accepts each legal value and rejects 'made_up'.
  4. zero_from_blank is accepted, and a measured `0` vs a zero_from_blank `0`
     produce DIFFERENT content_hash values (the v0.2.4 recipe collided — the
     contract change blueprint §5 demanded).
  5. An error row (token in value_text + presence='error' + error_type) satisfies
     the UNCHANGED one-of value CHECK; the one-of CHECK still forbids
     value_num+value_text together.
  6. The composite pair CHECK rejects ('key','estimated') and accepts
     ('derived','estimated'), and the SQL truth table for ALL 24 (origin,
     presence) combinations equals loader21.legal_pair's verdicts.
  7. New defaults hold (presence='measured', needs_verify=0) and src_column.role
     accepts 'value' / rejects 'bogus'.
  8. §8 P0 gate proper: a v0.2.4 store migrated by REBUILD of every affected
     table is compared against a FRESHLY CREATED v0.2.5 store — full catalog DDL
     parity (tables, indexes, views, triggers), row-data parity, and live
     widened-CHECK behaviour post-rebuild. A CHECK change has no ALTER, so an
     ALTER diff is not a valid comparison; rebuilt-vs-fresh is.

Never touches private/ — all databases are temp files under $TMPDIR or in-memory.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bagend import loader21  # noqa: E402  (method under test: hash recipe + legal_pair)

NEW_DDL = (ROOT / "tools" / "schema" / "books.sql").read_text()
OLD_DDL = (HERE / "old_books_v0.2.4.sql").read_text()

PAIR_TABLES = ["fact_state", "holding_state", "ss_earnings_annual", "ss_benefit_estimates"]
REBUILD_TABLES = PAIR_TABLES + ["src_column"]
# views that read the rebuilt tables (must be dropped before, recreated after)
DEPENDENT_VIEWS = ["v_state_current", "v_state_conflicts", "v_net_worth", "v_holding_current"]


# ---------------------------------------------------------------- sql text extraction

def table_ddl(ddl_text: str, table: str) -> str:
    m = re.search(rf"CREATE TABLE {table} \(.*?\n\);", ddl_text, re.S)
    assert m, f"CREATE TABLE {table} not found in DDL"
    return m.group(0)


def index_ddls(ddl_text: str, table: str) -> list[str]:
    # NB: statements ending in ')' too (ix_...) and clauses like 'IS NULL;' (ux_ partial idx)
    return [m.group(0) for m in
            re.finditer(rf"CREATE (?:UNIQUE )?INDEX \w+ ON {table} [^;]*;", ddl_text)]


def view_ddl(ddl_text: str, view: str) -> str:
    m = re.search(rf"CREATE VIEW {view} AS.*?;", ddl_text, re.S)
    assert m, f"CREATE VIEW {view} not found"
    return m.group(0)


# ---------------------------------------------------------------- db helpers

def apply_ddl(ddl_text: str, path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path if path else ":memory:")
    con.executescript(ddl_text)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def seed_parents(con: sqlite3.Connection) -> None:
    """Minimal identical parents in every store so sample fact rows are legal."""
    con.executescript("""
      INSERT INTO load_batch(batch_id, started_at, status) VALUES (1, '2026-09-12T00:00:00', 'complete');
      INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path, precedence, role)
            VALUES (1, 'probe', 'probe-drive-token', 'drive-file', 'files.get alt=media', 1, 'raw');
      INSERT INTO src_tab(tab_id, source_id, tab, role, dedupe_rule, row_order)
            VALUES (1, 1, 'ProbeTab', 'raw', 'none', 'unsorted');
      INSERT INTO dim_account VALUES (1, 'PROBE_AC', 'probe-institution', 'other', 'Joe', 'unsettled', NULL);
      INSERT INTO dim_metric VALUES (1, 'PROBE_METRIC', 0, 0, 'unknown', 'USD', NULL, NULL);
      INSERT INTO dim_security(security_id, ticker) VALUES (1, 'PRB');
    """)


def fact_values(con: sqlite3.Connection) -> int:
    return con.execute("SELECT count(*) FROM fact_state").fetchone()[0]


def insert_fact(con, nk, presence=None, origin=None, value_num=1.0, value_text=None,
                error_type=None, hash_tag=None):
    cols = ["natural_key", "account_id", "metric_id", "as_of", "seq_in_date",
            "source_id", "batch_id", "ingested_at", "period_grain"]
    vals = [nk, 1, 1, "2026-01-31", 1, 1, 1, "2026-09-12T00:00:00", "month-end"]
    if value_num is not None:
        cols.append("value_num"); vals.append(value_num)
    if value_text is not None:
        cols.append("value_text"); vals.append(value_text)
    if presence is not None:
        cols.append("presence"); vals.append(presence)
    if origin is not None:
        cols.append("origin"); vals.append(origin)
    if error_type is not None:
        cols.append("error_type"); vals.append(error_type)
    cols.append("content_hash"); vals.append(hash_tag or f"h-{nk}")
    con.execute(
        f"INSERT INTO fact_state({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def expect_ok(fn, what):
    fn()
    return True


def expect_reject(fn, what, needle=None):
    try:
        fn()
    except sqlite3.IntegrityError as e:
        if needle is not None and needle not in str(e):
            raise AssertionError(f"{what}: rejected, but by the wrong constraint: {e}") from e
        return True
    raise AssertionError(f"{what}: ACCEPTED but must be rejected")


def norm_sql(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", s.replace('"', " ")).strip().lower()


# ---------------------------------------------------------------- cases

def case_fresh_apply_and_version():
    with tempfile.TemporaryDirectory(prefix="p0-schema-") as td:
        db = str(Path(td) / "fresh.db")
        con = apply_ddl(NEW_DDL, db)
        v = con.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()[0]
        assert v == "v0.2.5", f"schema_version is {v!r}, expected 'v0.2.5'"
        assert loader21.SCHEMA_VERSION == "v0.2.5", "loader constant out of sync"
        loader21.assert_schema(con)  # the loader must accept the freshly applied store
        con.close()


def case_columns_and_checks_exist():
    con = apply_ddl(NEW_DDL)
    for t in PAIR_TABLES:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        for c in ("presence", "origin", "error_type"):
            assert c in cols, f"{t} missing column {c}"
        if t == "holding_state":
            assert "needs_verify" in cols, "holding_state still missing needs_verify"
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
        assert "'zero_from_blank'" in sql, f"{t} presence CHECK not widened"
        assert f"ck_{'fact_state' if t == 'fact_state' else t.replace('ss_earnings_annual', 'ss_earnings').replace('ss_benefit_estimates', 'ss_benefit')}_origin_presence" in sql, f"{t} pair CHECK missing"
    sc_cols = {r[1] for r in con.execute("PRAGMA table_info(src_column)")}
    for c in ("origin", "derivation_kind", "formula_shape", "copy_of", "role"):
        assert c in sc_cols, f"src_column missing column {c}"
    sc_sql = con.execute("SELECT sql FROM sqlite_master WHERE name='src_column'").fetchone()[0]
    assert "'scratch'" in sc_sql and "'key'" in sc_sql, "src_column role vocabulary missing"
    # the four composite pair-CHECK bodies must be literally identical (one §4 list, four homes)
    bodies = []
    for t in PAIR_TABLES:
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]
        m = re.search(r"CHECK \(\s*origin IS NULL OR presence IS NULL.*?\)\s*\)", sql, re.S)
        assert m, f"{t}: pair body not parseable"
        bodies.append(re.sub(r"\s+", " ", m.group(0)))
    assert len(set(bodies)) == 1, "the four pair-CHECK bodies differ — §4 list drifted"
    # and identical to the loader's frozenset (string-level sync, before behavioural matrix below)
    sql_pairs = set(re.findall(r"origin='(\w+)' AND presence='(\w+)'", bodies[0]))
    assert sql_pairs == set(loader21.LEGAL_ORIGIN_PRESENCE_PAIRS), \
        f"SQL vs loader pair sets differ: {sql_pairs ^ set(loader21.LEGAL_ORIGIN_PRESENCE_PAIRS)}"


def case_presence_vocabulary():
    con = apply_ddl(NEW_DDL)
    seed_parents(con)
    for p in ("measured", "estimated", "zero_from_blank", "error"):
        vt = "#NAME?" if p == "error" else None
        expect_ok(lambda p=p, vt=vt: insert_fact(con, f"pv|{p}", presence=p,
                  value_num=None if vt else 1.0, value_text=vt,
                  error_type=vt), f"presence={p} insert")
    expect_reject(lambda: insert_fact(con, "pv|bad", presence="made_up"),
                  "presence=made_up", needle="presence")
    # default without a stated presence
    insert_fact(con, "pv|default")
    assert con.execute("SELECT presence FROM fact_state WHERE natural_key='pv|default'").fetchone()[0] == "measured"


def case_two_zeros_diverge_in_hash():
    h_measured = loader21.state_content_hash(1, 1, "2026-01-31", 1, 0.0, "measured", "entered")
    h_blank = loader21.state_content_hash(1, 1, "2026-01-31", 1, 0.0, "zero_from_blank", "entered")
    assert h_measured != h_blank, "the two zeros still collide in the hash recipe"
    # the v0.2.4 recipe (value only) demonstrates the silent-dedupe it replaced
    assert loader21.make_hash(1, 1, "2026-01-31", 1, 0.0) == \
        loader21.make_hash(1, 1, "2026-01-31", 1, 0.0), "old-recipe demo broken"
    con = apply_ddl(NEW_DDL)
    seed_parents(con)
    insert_fact(con, "zero|m", presence="measured", value_num=0.0, hash_tag=h_measured)
    # the loader's dedupe probe must NOT treat the blank zero as a duplicate:
    assert con.execute("SELECT 1 FROM fact_state WHERE content_hash=?", (h_blank,)).fetchone() is None
    insert_fact(con, "zero|b", presence="zero_from_blank", value_num=0.0, hash_tag=h_blank)
    assert fact_values(con) == 2, "a zero_from_blank row was deduped against a measured zero"


def case_error_representation():
    con = apply_ddl(NEW_DDL)
    seed_parents(con)
    insert_fact(con, "err1", presence="error", origin="derived", value_num=None,
                value_text="#NAME?", error_type="#NAME?")
    row = con.execute("SELECT value_text, presence, error_type FROM fact_state WHERE natural_key='err1'").fetchone()
    assert row == ("#NAME?", "error", "#NAME?"), f"error row mangled: {row}"
    # the one-of value CHECK is UNCHANGED: still forbids value_num AND value_text
    expect_reject(lambda: insert_fact(con, "err2", presence="error", origin="derived",
                                      value_num=1.0, value_text="#REF!", error_type="#REF!"),
                  "one-of value CHECK", needle="value_num")


def case_pair_matrix_sql_matches_loader():
    con = apply_ddl(NEW_DDL)
    seed_parents(con)
    i = 0
    for origin in loader21.ORIGIN_VALUES:
        for presence in loader21.PRESENCE_VALUES:
            i += 1
            fn = lambda o=origin, p=presence, n=i: insert_fact(con, f"mx|{n}", presence=p, origin=o)
            if loader21.legal_pair(origin, presence):
                expect_ok(fn, f"({origin},{presence}) legal")
            else:
                expect_reject(fn, f"({origin},{presence}) illegal", needle="origin_presence")
    # the two pairs the blueprint names explicitly, on all four tables
    for t in PAIR_TABLES[1:]:
        if t == "holding_state":
            ins = lambda nk, o, p: con.execute(
                "INSERT INTO holding_state(natural_key,account_id,security_id,as_of,shares,presence,origin,source_id,batch_id,ingested_at) VALUES (?,1,1,'2026-01-31',1.0,?,?,1,1,'2026-09-12T00:00:00')", (nk, p, o))
        else:
            tbl = "ss_earnings_annual" if t == "ss_earnings_annual" else "ss_benefit_estimates"
            def ins(nk, o, p, tbl=tbl):
                if tbl == "ss_earnings_annual":
                    con.execute(f"INSERT INTO {tbl}(natural_key,work_year,ss_taxed,presence,origin,source_id,batch_id,ingested_at) VALUES (?,2020,1.0,?,?,1,1,'2026-09-12T00:00:00')", (nk, p, o))
                else:
                    con.execute(f"INSERT INTO {tbl}(natural_key,work_year,claim_basis,amount,unit,is_estimate,presence,origin,source_id,batch_id,ingested_at) VALUES (?,2020,'Age67',1.0,'monthly',1,?,?,1,1,'2026-09-12T00:00:00')", (nk, p, o))
        expect_reject(lambda nk=f"k|{t}": ins(nk, "key", "estimated"), f"{t} (key,estimated)", needle="origin_presence")
        expect_ok(lambda nk=f"ok|{t}": ins(nk, "derived", "estimated"), f"{t} (derived,estimated)")
    # loader-side assertion raises with a clear message
    try:
        loader21.require_legal_pair("key", "estimated", "unit-check")
        raise AssertionError("require_legal_pair did not raise")
    except loader21.LoadError as e:
        assert "illegal (origin, presence) pair" in str(e)


def case_defaults_and_role():
    con = apply_ddl(NEW_DDL)
    seed_parents(con)
    con.execute("INSERT INTO holding_state(natural_key,account_id,security_id,as_of,source_id,batch_id,ingested_at) VALUES ('hs1',1,1,'2026-01-31',1,1,'x')")
    p, nv = con.execute("SELECT presence, needs_verify FROM holding_state WHERE natural_key='hs1'").fetchone()
    assert (p, nv) == ("measured", 0), f"holding_state defaults wrong: {(p, nv)}"
    con.execute("INSERT INTO src_column(tab_id,col_index,header_text,origin,derivation_kind,role) VALUES (1,7,'Probe','entered','aggregate,chain','value')")
    expect_reject(lambda: con.execute("INSERT INTO src_column(tab_id,col_index,header_text,role) VALUES (1,8,'Bad','bogus')"),
                  "src_column.role", needle="role")


def case_rebuild_vs_fresh():
    """§8 P0 gate: CHECK widening has no ALTER — migrate by REBUILD and compare
    the rebuilt store against a FRESHLY CREATED one (not an ALTER diff)."""
    old = apply_ddl(OLD_DDL)
    seed_parents(old)
    # v0.2.4-shaped sample data (columns that existed then; nothing invented)
    old.execute("INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,seq_in_date,sheet_row_number,value_num,presence,period_grain,content_hash,source_id,batch_id,ingested_at) VALUES ('rb|f1',1,1,'2026-01-31',1,7,10.0,'measured','month-end','rbh1',1,1,'2026-09-12T00:00:00')")
    old.execute("INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,seq_in_date,value_num,presence,period_grain,verify_note,content_hash,source_id,batch_id,ingested_at) VALUES ('rb|f2',1,1,'2026-01-31',1,8.0,'estimated','month-end','derived by difference','rbh2',1,1,'2026-09-12T00:00:00')")
    old.execute("INSERT INTO holding_state(natural_key,account_id,security_id,as_of,shares,market_value,source_id,batch_id,ingested_at) VALUES ('rb|h1',1,1,'2026-01-31',2.0,50.0,1,1,'2026-09-12T00:00:00')")
    old.execute("INSERT INTO ss_earnings_annual(natural_key,work_year,ss_taxed,medicare_taxed,source_id,batch_id,ingested_at) VALUES ('rb|e1',2020,100.0,140.0,1,1,'2026-09-12T00:00:00')")
    old.execute("INSERT INTO ss_benefit_estimates(natural_key,work_year,claim_basis,amount,unit,is_estimate,needs_verify,source_id,batch_id,ingested_at) VALUES ('rb|b1',2020,'Age67',123.0,'monthly',1,1,1,1,'2026-09-12T00:00:00')")
    old.execute("INSERT INTO src_column(map_id,tab_id,col_index,header_text,account_id,metric_id,unit) VALUES (1,1,7,'Probe Col',1,1,'USD')")

    # --- migrate: drop dependent views, rebuild each affected table from the
    # NEW FILE TEXT (the migration source of truth), copy, drop, rename,
    # recreate indexes + views, stamp the new version.
    for v in DEPENDENT_VIEWS:
        old.execute(f"DROP VIEW {v}")
    for t in REBUILD_TABLES:
        cols_old = [r[1] for r in old.execute(f"PRAGMA table_info({t})")]  # old columns, pre-rebuild
        ddl = table_ddl(NEW_DDL, t).replace(f"CREATE TABLE {t} (", f"CREATE TABLE {t}__p0new (", 1)
        old.execute(ddl)
        old.execute(f"INSERT INTO {t}__p0new ({','.join(cols_old)}) SELECT {','.join(cols_old)} FROM {t}")
        old.execute(f"DROP TABLE {t}")
        old.execute(f"ALTER TABLE {t}__p0new RENAME TO {t}")
        for idx in index_ddls(NEW_DDL, t):
            old.execute(idx)
    for v in DEPENDENT_VIEWS:
        old.execute(view_ddl(NEW_DDL, v))
    old.execute("UPDATE _schema_meta SET value='v0.2.5' WHERE key='schema_version'")

    loader21.assert_schema(old)  # the migrated store satisfies the loader's contract

    fresh = apply_ddl(NEW_DDL)
    seed_parents(fresh)
    # logically identical inserts written in the OLD shape (new columns defaulted)
    fresh.execute("INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,seq_in_date,sheet_row_number,value_num,presence,period_grain,content_hash,source_id,batch_id,ingested_at) VALUES ('rb|f1',1,1,'2026-01-31',1,7,10.0,'measured','month-end','rbh1',1,1,'2026-09-12T00:00:00')")
    fresh.execute("INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,seq_in_date,value_num,presence,period_grain,verify_note,content_hash,source_id,batch_id,ingested_at) VALUES ('rb|f2',1,1,'2026-01-31',1,8.0,'estimated','month-end','derived by difference','rbh2',1,1,'2026-09-12T00:00:00')")
    fresh.execute("INSERT INTO holding_state(natural_key,account_id,security_id,as_of,shares,market_value,source_id,batch_id,ingested_at) VALUES ('rb|h1',1,1,'2026-01-31',2.0,50.0,1,1,'2026-09-12T00:00:00')")
    fresh.execute("INSERT INTO ss_earnings_annual(natural_key,work_year,ss_taxed,medicare_taxed,source_id,batch_id,ingested_at) VALUES ('rb|e1',2020,100.0,140.0,1,1,'2026-09-12T00:00:00')")
    fresh.execute("INSERT INTO ss_benefit_estimates(natural_key,work_year,claim_basis,amount,unit,is_estimate,needs_verify,source_id,batch_id,ingested_at) VALUES ('rb|b1',2020,'Age67',123.0,'monthly',1,1,1,1,'2026-09-12T00:00:00')")
    fresh.execute("INSERT INTO src_column(map_id,tab_id,col_index,header_text,account_id,metric_id,unit) VALUES (1,1,7,'Probe Col',1,1,'USD')")

    # --- catalog parity: every stored DDL statement (tables, indexes, views, triggers)
    def catalog(con):
        return {r[0]: norm_sql(r[1]) for r in
                con.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
    co, cf = catalog(old), catalog(fresh)
    drift = sorted(k for k in set(co) | set(cf) if co.get(k) != cf.get(k))
    assert not drift, f"rebuilt-vs-fresh DDL drift: {drift}"

    # --- row-data parity, column-for-column, in pk order
    pk = {"fact_state": "state_id", "holding_state": "holding_id",
          "ss_earnings_annual": "id", "ss_benefit_estimates": "id", "src_column": "map_id"}
    for t in REBUILD_TABLES:
        rows_o = old.execute(f"SELECT * FROM {t} ORDER BY {pk[t]}").fetchall()
        rows_f = fresh.execute(f"SELECT * FROM {t} ORDER BY {pk[t]}").fetchall()
        assert rows_o == rows_f, f"rebuilt data differs from fresh in {t}:\n {rows_o}\n {rows_f}"

    # --- widened checks are LIVE on the migrated store (not just textually present)
    insert_fact(old, "rbz", presence="zero_from_blank", origin="entered", value_num=0.0)
    expect_reject(lambda: insert_fact(old, "rbx", presence="made_up"), "post-rebuild vocab", needle="presence")
    expect_reject(lambda: insert_fact(old, "rbk", presence="estimated", origin="key"),
                  "fact_state post-rebuild pair", needle="origin_presence")
    expect_reject(lambda: old.execute(
        "INSERT INTO holding_state(natural_key,account_id,security_id,as_of,presence,origin,source_id,batch_id,ingested_at) VALUES ('rbk2',1,1,'2026-01-31','estimated','key',1,1,'x')"),
        "holding_state post-rebuild pair", needle="origin_presence")


CASES = [
    ("fresh_apply_and_schema_version", case_fresh_apply_and_version),
    ("new_columns_and_checks_in_sqlite_master", case_columns_and_checks_exist),
    ("presence_vocabulary_accept_reject", case_presence_vocabulary),
    ("two_zeros_diverge_in_content_hash", case_two_zeros_diverge_in_hash),
    ("error_row_via_value_text_oneof_unchanged", case_error_representation),
    ("pair_check_matches_loader_legal_pair_24x", case_pair_matrix_sql_matches_loader),
    ("defaults_and_src_column_role_check", case_defaults_and_role),
    ("rebuild_vs_fresh_parity_§8P0", case_rebuild_vs_fresh),
]


def main() -> int:
    failures = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"PASS - {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL - {name}: {type(e).__name__}: {e}")
    print("BATTERY COMPLETE")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
