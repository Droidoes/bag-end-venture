#!/usr/bin/env python3
"""Slice B view-contract battery: the store's READ SURFACE must be honest about
`presence` and `origin` (blueprint v0.3 section 5, P2/P3; DM-2026-01 blank rule).

Offline, in-memory, synthetic only: no network, no Drive, nothing read from
`private/`, no owner values. Every figure below is a made-up fixture number.

WHY THIS FILE EXISTS. `v_state_current` did not expose `presence`, and `v_net_worth`
summed whatever it was given and detected errors through `value_num IS NULL`. So the
`zero_from_blank` / `copy` / `error` labels were queryable in the tables and invisible in
the published surface: the protection existed only for a reader who remembered to write
the filter. A naive average over a column whose blanks were materialised divided by every
row instead of by the observations the source actually stated, and a declared duplicate
was summed together with its source. Comments cannot enforce that; the view can. These
tests are the enforcement point.

WHAT IS ASSERTED (one line per case, grouped):
  * a fixture built from tools/schema/books.sql has EVERY view present and queryable;
  * the change is view-only — no table appeared, disappeared or lost a column, and the
    schema version was NOT bumped (read from both files, never pinned in this one);
  * `v_state_current` exposes `presence` + `origin` (+ `error_type`, `derivation_kind`),
    and filtering `presence <> 'zero_from_blank'` is possible and moves the denominator a
    naive average would use;
  * every legal (origin, presence) pair — parsed out of the CHECK, not copied — lands in
    exactly one composition class, under the ratified precedence `copy` > `error` >
    presence, because `copy` is a value of ORIGIN and (copy, error) is a legal pair;
  * a `copy` row is NOT in an additive total and its source IS;
  * an `error` row is not counted as a value, including one carrying a number;
  * `n_error` is keyed on `presence='error'`, NOT on `value_num IS NULL` — the old
    conflation reported a non-error text component as an error;
  * the composition counts sum to the row count for EVERY group of the fixture, and each
    total equals the additive sum computed independently;
  * exposing the labels added no row and dropped no row: the new views are compared
    against the pre-Slice-B view DDL on the columns those views always had;
  * what Slice B could NOT do is stated, not papered over: `fact_event` carries no
    `presence`, so `v_cash_flow` has nothing to expose (ratified scope, v0.3 section 2).

Run from the repo root:
    python3 tools/tests/view_contract_tests.py
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DDL = (ROOT / "tools" / "schema" / "books.sql").read_text()

# The sole sanctioned previous-schema file (the same exception tools/tests/README.md
# grants to schema_parity.py): it holds the view DDL as it stood BEFORE Slice B, so the
# row-invariance assertions compare against the real previous contract instead of a
# snapshot pasted into this file — which is exactly how a harness goes stale.
BASELINE = (HERE / "old_books_v0.2.4.sql").read_text()

VIEWS = ["v_state_current", "v_state_conflicts", "v_net_worth", "v_cash_flow",
         "v_holding_current", "v_assumption_current"]
COMPOSITION_COLS = ["n_measured", "n_estimated", "n_copy", "n_zero_from_blank", "n_error"]
GRAIN = "month-end"
ISOTIME = "2026-09-12T00:00:00"

PASS = 0
FAIL = 0
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


def view_ddl(text, view):
    """Extract one CREATE VIEW statement, the way schema_parity.py does."""
    m = re.search(rf"CREATE VIEW {view} AS.*?;", text, re.S)
    return m.group(0) if m else None


def cols_of(con, name):
    return [r[1] for r in con.execute(f"PRAGMA table_info({name})")]


# ---------------------------------------------------------------- fixtures

def fresh():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    return con


def seed(con):
    """Two sources (so precedence is exercised), four accounts, six metrics, one tab."""
    for bid in (1, 2):
        con.execute("INSERT INTO load_batch(batch_id, started_at, status) VALUES (?,?,'complete')",
                    (bid, f"2026-09-1{bid}T00:00:00"))
    for sid, alias, prec, mod in [(1, "src_a", 10, "2026-09-01T00:00:00"),
                                 (2, "src_b", 20, "2026-09-02T00:00:00")]:
        con.execute("INSERT INTO src_ref(source_id, alias, drive_id, source_kind, read_path,"
                    " precedence, role, sheet_modified) VALUES (?,?,?,?,?,?,?,?)",
                    (sid, alias, f"drv-synth-{sid}", "native-google-sheet",
                     "sheets.values.get", prec, "raw", mod))
    for aid in (1, 2, 3, 4):
        con.execute("INSERT INTO dim_account(account_id, code, institution, registration,"
                    " entity, purpose) VALUES (?,?,?,?,?,?)",
                    (aid, f"A{aid}", "synth-inst", "taxable", "Joe", "growth"))
    for mid in range(1, 7):
        con.execute("INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative, polarity)"
                    " VALUES (?,?,?,?,?)", (mid, f"SYN_M{mid}", 0, 0, "asset"))
    con.execute("INSERT INTO dim_txn_type(txn_type_id, source_id, raw_label, canonical)"
                " VALUES (1,1,'UNMAPPED','UNMAPPED')")
    con.execute("INSERT INTO dim_category(category_id, source_id, source_label, canonical,"
                " spending_class) VALUES (1,1,'UNMAPPED','UNMAPPED','unsettled')")
    con.execute("INSERT INTO dim_security(security_id, ticker, name, asset_class)"
                " VALUES (1,'SYNTH','synthetic security','equity')")
    con.execute("INSERT INTO src_tab(tab_id, source_id, tab, role, dedupe_rule, row_order)"
                " VALUES (1,1,'Synth Tab','raw','none','ascending-date')")
    return con


def extra_account(con, aid, registration="401k"):
    con.execute("INSERT INTO dim_account(account_id, code, institution, registration, entity,"
                " purpose) VALUES (?,?,?,?,?,?)", (aid, f"A{aid}", "synth-inst", registration,
                                                   "Joe", "reserve"))


def _hash(nk, presence, origin, val, txt):
    return f"h:{nk}:{presence}:{origin}:{val}:{txt}"


def state(con, acct, met, day, *, val=None, txt=None, presence="measured", origin=None,
          error_type=None, grain=GRAIN, src=1, batch=1, seq=1, supersede=None):
    """One fact_state row. Synthetic values only; content_hash unique per row."""
    nk = f"src_{'a' if src == 1 else 'b'}|a{acct}|m{met}|{day}|{seq}"
    con.execute(
        """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
               value_num, value_text, presence, origin, error_type, period_grain,
               content_hash, source_id, batch_id, superseded_by_batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (nk, acct, met, day, seq, val, txt, presence, origin, error_type, grain,
         _hash(nk, presence, origin, val, txt), src, batch, supersede, ISOTIME))
    return nk


def wnr(con, day, met):
    """One v_net_worth group as a positional row. Column order is asserted in section 1."""
    return con.execute("SELECT * FROM v_net_worth WHERE as_of=? AND metric_id=?",
                       (day, met)).fetchone()


def classes(row):
    """(n_measured, n_estimated, n_copy, n_zero_from_blank, n_error) of a v_net_worth row."""
    return row[5:10]


# ------------------------------------------------- vocabularies read from the schema

def presence_vocab():
    m = re.search(r"presence\s+TEXT NOT NULL DEFAULT 'measured' CHECK \(presence IN \(([^)]*)\)\)", DDL)
    assert m, "presence CHECK vocabulary not found in books.sql"
    return [s.strip().strip("'") for s in m.group(1).split(",")]


def legal_pairs():
    m = re.search(r"CONSTRAINT ck_fact_state_origin_presence CHECK \((.*?)\n  \)", DDL, re.S)
    assert m, "ck_fact_state_origin_presence not found in books.sql"
    return [(a, b) for a, b in re.findall(r"origin='(\w+)' AND presence='(\w+)'", m.group(1))]


# ================================================================ 1. the script builds

def section_build():
    print("\n-- 1. a fixture built from tools/schema/books.sql has every view present and queryable")
    try:
        con = fresh()
        check("books.sql applies clean to a fresh store", True)
    except Exception as e:
        check("books.sql applies clean to a fresh store", False, str(e))
        return
    check("integrity_check ok", con.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check("no FK violations on an empty store", con.execute("PRAGMA foreign_key_check").fetchall() == [])

    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    for v in VIEWS:
        check(f"view {v} present", v in have, f"views: {sorted(have)}")

    seed(con)
    state(con, 1, 1, "2025-01-31", val=10.0)
    con.execute("INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date,"
                " txn_type_id, category_id, amount, unit, content_hash, source_id, batch_id,"
                " ingested_at) VALUES ('src_a|e|2025-01-15|1',1,'2025-01-15',1,1,1,5.0,'USD',"
                "'hev1',1,1,'2026-09-12T00:00:00')")
    con.execute("INSERT INTO holding_state(natural_key, account_id, security_id, as_of, shares,"
                " market_value, source_id, batch_id, ingested_at) VALUES ('src_a|h|1|2025-01-31',"
                "1,1,'2025-01-31',2.0,50.0,1,1,'2026-09-12T00:00:00')")
    con.execute("INSERT INTO assumption_register(natural_key, key, value_num, source, as_of,"
                " batch_id, ingested_at) VALUES ('src_a|k1','syn.key',1.0,'synthetic',"
                "'2026-01-01',1,'2026-09-12T00:00:00')")
    for v in VIEWS:
        try:
            con.execute(f"SELECT * FROM {v} LIMIT 1").fetchall()
            ran, err = True, ""
        except Exception as e:
            ran, err = False, str(e)
        check(f"view {v} queryable and reports columns", ran and bool(cols_of(con, v)), err)

    # Slice B was supposed to be VIEW-ONLY. Tables are compared against the sanctioned
    # previous-schema file: none may vanish, none may lose a column.
    old_tables = {m.group(1) for m in re.finditer(r"CREATE TABLE (\w+) \(", BASELINE)}
    new_tables = {m.group(1) for m in re.finditer(r"CREATE TABLE (\w+) \(", DDL)}
    check("no table was dropped by the view change", old_tables <= new_tables,
          f"missing: {sorted(old_tables - new_tables)}")
    check("no table was added by the view change", new_tables <= old_tables,
          f"added: {sorted(new_tables - old_tables)}")

    def table_cols(text, t):
        body = re.search(rf"CREATE TABLE {t} \((.*?)\n\);", text, re.S).group(1)
        out = []
        for line in body.split("\n"):
            mm = re.match(r"\s*([a-z_][a-z0-9_]*)\s+", line)
            if mm and mm.group(1).upper() not in {"CHECK", "UNIQUE", "CONSTRAINT",
                                                  "PRIMARY", "FOREIGN"}:
                out.append(mm.group(1))
        return set(out)

    lost = [t for t in sorted(old_tables & new_tables)
            if not table_cols(BASELINE, t) <= table_cols(DDL, t)]
    check("no table lost a column (the change is additive)", not lost, f"tables: {lost}")
    vcol = cols_of(con, "v_net_worth")
    check("v_net_worth column order is as documented",
          vcol[:5] == ["as_of", "metric_id", "period_grain", "total", "n_components"], f"{vcol}")
    check("v_state_current column order keeps the pre-Slice-B prefix intact",
          cols_of(con, "v_state_current")[:10] == ["account_id", "metric_id", "as_of", "value_num",
                                                   "value_text", "period_grain", "seq_in_date",
                                                   "source_id", "batch_id", "ingested_at"])

    # Version discipline: this slice must NOT bump. Read from both files, never pinned here.
    in_ddl = re.search(r"INSERT INTO _schema_meta\(key, value\) VALUES \('schema_version', '([^']+)'\)", DDL)
    loader_py = (ROOT / "tools" / "bagend" / "loader21.py").read_text()
    in_loader = re.search(r'SCHEMA_VERSION = "([^"]+)"', loader_py)
    sql_v = in_ddl and in_ddl.group(1)
    check("the schema script declares exactly one version, in exactly one place",
          len(re.findall(r"'schema_version',", DDL)) == 1 and bool(sql_v))
    check("the loader's asserted version still agrees with the schema script (no half-bump)",
          bool(sql_v) and bool(in_loader) and sql_v == in_loader.group(1),
          f"sql={sql_v} loader={in_loader and in_loader.group(1)}")
    check("the fresh store reports that same version",
          con.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()[0] == sql_v)
    con.close()


# ================================================================ 2. exposure + blank filter

def section_exposure():
    print("\n-- 2. v_state_current exposes presence/origin, and the fabricated-zero filter works")
    con = fresh(); seed(con)
    cols = cols_of(con, "v_state_current")
    for c in ("presence", "origin", "error_type", "derivation_kind", "composition_class", "is_additive"):
        check(f"v_state_current exposes {c}", c in cols, f"cols: {cols}")
    check("v_net_worth carries the composition breakdown",
          all(c in cols_of(con, "v_net_worth") for c in COMPOSITION_COLS),
          f"cols: {cols_of(con, 'v_net_worth')}")
    check("v_state_conflicts exposes presence/origin/error_type",
          {"presence", "origin", "error_type"} <= set(cols_of(con, "v_state_conflicts")))
    check("v_holding_current exposes presence/origin/error_type",
          {"presence", "origin", "error_type"} <= set(cols_of(con, "v_holding_current")))

    # A monthly spine carrying an ANNUAL observation: 3 stated observations, 5 blanks
    # materialised as zero_from_blank (DM-2026-01's shape; synthetic values).
    days = ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30",
            "2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31"]
    for i, day in enumerate(days):
        blank = i >= 3
        state(con, 1, 2, day, val=(0.0 if blank else 100.0),
              presence=("zero_from_blank" if blank else "measured"), origin="entered")
    got = (con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=2").fetchone()[0],
           con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=2"
                       " AND presence='zero_from_blank'").fetchone()[0],
           con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=2"
                       " AND presence <> 'zero_from_blank'").fetchone()[0])
    check("filtering presence <> 'zero_from_blank' is possible and selective",
          got == (8, 5, 3), f"got {got}")
    naive = con.execute("SELECT AVG(value_num) FROM v_state_current WHERE metric_id=2").fetchone()[0]
    honest = con.execute("SELECT AVG(value_num) FROM v_state_current WHERE metric_id=2"
                         " AND presence <> 'zero_from_blank'").fetchone()[0]
    check("a naive average is understated by the fabricated rows; the filtered one is not",
          abs(honest / naive - 8 / 3) < 1e-9, f"naive {naive} filtered {honest}")
    check("the same filter expressed through is_additive keeps the zero (it IS a stated zero)",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=2"
                      " AND is_additive=1").fetchone()[0] == 8)
    check("every exposed presence is inside the ratified vocabulary",
          {r[0] for r in con.execute("SELECT DISTINCT presence FROM v_state_current")}
          <= set(presence_vocab()))
    check("presence is never NULL on the read surface",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE presence IS NULL").fetchone()[0] == 0)
    m = re.search(r"origin\s+TEXT CHECK \(origin IS NULL OR origin IN \(([^)]*)\)\)", DDL)
    origin_vocab = {s.strip().strip("'") for s in m.group(1).split(",")}
    check("every exposed origin is inside the ratified vocabulary",
          {r[0] for r in con.execute("SELECT DISTINCT origin FROM v_state_current"
                                     " WHERE origin IS NOT NULL")} <= origin_vocab)
    check("'copy' is a value of ORIGIN, not of presence (why the breakdown mixes grains)",
          "copy" in origin_vocab and "copy" not in presence_vocab())
    con.close()


# ================================================================ 3. classification is total

def section_classification():
    print("\n-- 3. every legal (origin, presence) pair lands in exactly one composition class")
    pairs = legal_pairs()
    check("legal pairs parsed from the schema CHECK, not copied here", len(pairs) == 12, f"{len(pairs)}")

    def expect(origin, presence):
        if origin == "copy":
            return ("copy", 0)
        if presence == "error":
            return ("error", 0)
        return (presence, 1)

    con = fresh(); seed(con)
    months = [(1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30),
              (7, 31), (8, 31), (9, 30), (10, 31), (11, 30), (12, 31)]
    want = {}
    for (origin, presence), (m, d) in zip(pairs, months):
        day = f"2025-{m:02d}-{d:02d}"
        errored = presence == "error"
        state(con, 1, 3, day, val=(None if errored else 11.0),
              txt=("synth-TOKEN" if errored else None), presence=presence, origin=origin,
              error_type=("synth-TOKEN" if errored else None))
        want[day] = expect(origin, presence)
    got = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT as_of, composition_class, is_additive FROM v_state_current WHERE metric_id=3")}
    bad = {d: (got.get(d), want[d]) for d in want if got.get(d) != want[d]}
    check(f"all {len(pairs)} legal pairs classified by the ratified precedence", not bad, str(bad))
    check("composition classes are exactly the presence vocabulary plus copy",
          {r[0] for r in con.execute("SELECT DISTINCT composition_class FROM v_state_current")}
          == set(presence_vocab()) | {"copy"})
    check("is_additive is a 0/1 flag, never NULL",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE is_additive IS NULL"
                      " OR is_additive NOT IN (0,1)").fetchone()[0] == 0)
    check("a copy is never additive, whatever presence it inherited",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE composition_class='copy'"
                      " AND is_additive=1").fetchone()[0] == 0)
    check("an error is never additive",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE composition_class='error'"
                      " AND is_additive=1").fetchone()[0] == 0)
    check("no row is unclassified",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE composition_class NOT IN"
                      " ('measured','estimated','zero_from_blank','copy','error')").fetchone()[0] == 0)
    check("the (copy, error) pair is in the legal list, so precedence had to be decided",
          ("copy", "error") in pairs)
    con.close()


# ================================================================ 4. copies

def section_copy():
    print("\n-- 4. a copy is NOT in an additive total, and its source IS")
    con = fresh(); seed(con)
    # the same figure stated twice — one entered column and one pure reference — which is
    # the double-count vector the copy rule exists to stop. Distinct accounts, so
    # v_state_current keeps both rows and v_net_worth must choose correctly.
    state(con, 1, 1, "2025-06-30", val=40.0, presence="measured", origin="entered")
    state(con, 2, 1, "2025-06-30", val=17.0, presence="measured", origin="copy")
    r = wnr(con, "2025-06-30", 1)
    check("total excludes the copy: the source's 40 only, never the 57 of double counting",
          r[3] == 40.0, f"got {r[3]}")
    check("the copy's own source IS in the total", r[12] == 40.0 and r[13] == 40.0,
          f"min/max {r[12]}/{r[13]}")
    check("n_components still counts the copy", r[4] == 2, f"got {r[4]}")
    check("n_copy names it", r[7] == 1, f"got {r[7]}")
    check("n_additive counts only what the total summed", r[10] == 1, f"got {r[10]}")

    # min/max must not be set by a duplicate either
    state(con, 3, 1, "2025-06-30", val=999.0, presence="measured", origin="copy")
    r = wnr(con, "2025-06-30", 1)
    check("min/max components ignore copies", (r[12], r[13]) == (40.0, 40.0),
          f"got {(r[12], r[13])}")

    # a copy is reported as a copy whatever presence it inherited
    for day, p in [("2025-07-31", "estimated"), ("2025-08-31", "zero_from_blank"),
                   ("2025-09-30", "error")]:
        errored = p == "error"
        state(con, 1, 4, day, val=(None if errored else 3.0),
              txt=("synth-TOKEN" if errored else None), presence=p, origin="copy",
              error_type=("synth-TOKEN" if errored else None))
        state(con, 2, 4, day, val=8.0, presence="measured", origin="entered")
        r = wnr(con, day, 4)
        check(f"a copy is counted as copy, never also as its inherited '{p}'",
              classes(r) == (1, 0, 1, 0, 0) and r[3] == 8.0, f"got {classes(r)} total {r[3]}")
    check("copy rows stay visible on the read surface (the exclusion is at the total, not the row set)",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE origin='copy'").fetchone()[0] == 5)

    # NULL-safety: a bare `origin <> 'copy'` silently drops unlabelled legacy rows
    state(con, 4, 1, "2025-06-30", val=7.0, presence="measured", origin=None)
    bare = con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=1"
                       " AND origin <> 'copy'").fetchone()[0]
    coalesced = con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=1"
                            " AND COALESCE(origin,'') <> 'copy'").fetchone()[0]
    flagged = con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=1"
                          " AND is_additive=1").fetchone()[0]
    check("is_additive is the NULL-safe filter a bare origin <> 'copy' is not",
          bare < coalesced == flagged, f"bare={bare} coalesced={coalesced} flagged={flagged}")
    r = wnr(con, "2025-06-30", 1)
    check("an unlabelled legacy row is additive by default (unknown is not excluded)",
          r[3] == 47.0 and r[10] == 2, f"total={r[3]} n_additive={r[10]}")
    con.close()


# ================================================================ 5. errors

def section_error():
    print("\n-- 5. an error row is not counted as a value, and n_error is not a null-value proxy")
    con = fresh(); seed(con)
    state(con, 1, 1, "2025-09-30", val=10.0, presence="measured", origin="entered")
    state(con, 2, 1, "2025-09-30", val=20.0, presence="estimated", origin="derived")
    state(con, 3, 1, "2025-09-30", txt="synth-TOKEN", presence="error", origin="derived",
          error_type="synth-TOKEN")
    r = wnr(con, "2025-09-30", 1)
    check("total sums the two real components only", r[3] == 30.0, f"got {r[3]}")
    check("n_error=1, keyed on presence", r[9] == 1, f"got {r[9]}")
    check("the error row is excluded from n_additive", r[10] == 2, f"got {r[10]}")
    check("n_components still sees it", r[4] == 3, f"got {r[4]}")

    # THE CONFLATION, FIXED. value_num IS NULL is NOT presence='error'. A text component
    # that never errored used to be reported as an error; it is really an additive row
    # carrying no numeric value — a different fact, now reported separately.
    state(con, 4, 1, "2025-09-30", txt="awaiting-statement", presence="measured", origin="entered")
    r = wnr(con, "2025-09-30", 1)
    check("a non-error text component is NOT counted as an error (the old view said 2)",
          r[9] == 1, f"n_error={r[9]}")
    check("it IS reported as an additive row carrying no numeric value",
          r[11] == 1, f"n_additive_null_value={r[11]}")
    check("and the total is still the two numerics", r[3] == 30.0, f"got {r[3]}")
    check("n_additive counts it, so the total cannot look complete while it contributes nothing",
          r[10] == 3, f"got {r[10]}")
    check("the old signal and the new one disagree, which is the point of the fix",
          con.execute("SELECT SUM(CASE WHEN value_num IS NULL THEN 1 ELSE 0 END) FROM"
                      " v_state_current WHERE as_of='2025-09-30' AND metric_id=1").fetchone()[0]
          != r[9])

    # An error row that carries a NUMBER must not be summed either: §5 puts the token in
    # value_text, but no CHECK stops a stale number riding along, so the exclusion has to
    # be on the label rather than on the value shape.
    state(con, 1, 5, "2025-09-30", val=77.0, presence="error", origin="derived",
          error_type="synth-TOKEN")
    state(con, 2, 5, "2025-09-30", val=5.0, presence="measured", origin="entered")
    r = wnr(con, "2025-09-30", 5)
    check("an error row carrying a number is still not a value",
          (r[3], r[9], r[10]) == (5.0, 1, 1), f"total={r[3]} n_error={r[9]} n_additive={r[10]}")
    check("the errored rows stay visible with their token on the read surface",
          con.execute("SELECT COUNT(*) FROM v_state_current WHERE presence='error'"
                      " AND error_type='synth-TOKEN'").fetchone()[0] == 2)
    con.execute("INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative, polarity)"
                " VALUES (8,'SYN_M8',0,0,'asset')")
    state(con, 1, 8, "2025-06-30", val=12.0, presence="measured", origin="copy")
    state(con, 2, 8, "2025-06-30", txt="synth-TOKEN", presence="error", origin="external",
          error_type="synth-TOKEN")
    r = wnr(con, "2025-06-30", 8)
    check("a group with nothing additive publishes NULL, so it cannot read as a zero total",
          r[3] is None and r[10] == 0 and r[4] == 2, f"got total={r[3]} n_additive={r[10]}")
    con.close()


# ================================================================ 6. the partition invariant

def section_partition():
    print("\n-- 6. the composition counts sum to the row count for every group of the fixture")
    con = fresh(); seed(con)
    day, met = "2025-12-31", 1
    state(con, 1, met, day, val=10.0, presence="measured", origin="entered")
    state(con, 2, met, day, val=20.0, presence="estimated", origin="derived")
    state(con, 3, met, day, val=0.0, presence="zero_from_blank", origin="entered")
    state(con, 4, met, day, val=30.0, presence="measured", origin="copy")
    for aid, reg in [(5, "401k"), (6, "roth"), (7, "hsa")]:
        extra_account(con, aid, reg)
    state(con, 5, met, day, txt="synth-TOKEN", presence="error", origin="derived",
          error_type="synth-TOKEN")
    state(con, 6, met, day, val=1.0, presence="error", origin="copy", error_type="synth-TOKEN")
    state(con, 7, met, day, val=60.0, presence="measured", origin=None)   # unlabelled legacy
    # a second group on the same date, and a non-monthly row that must not join either
    state(con, 1, 2, day, val=1.0, presence="estimated", origin="external")
    state(con, 2, 2, day, val=2.0, presence="measured", origin="entered", grain="weekly")

    r = wnr(con, day, met)
    check("seven components: five labelled classes, one copy-and-error, one unlabelled",
          r[4] == 7, f"got {r[4]}")
    check("the five composition counts sum to n_components",
          sum(classes(r)) == r[4], f"{classes(r)} vs {r[4]}")
    check("each class holds exactly the rows the fixture stated", classes(r) == (2, 1, 2, 1, 1),
          f"got {classes(r)}")
    check("n_additive = n_components - n_copy - n_error", r[10] == r[4] - r[7] - r[9], f"got {r[10]}")
    check("total = measured + estimated + zero_from_blank + unlabelled only", r[3] == 90.0,
          f"got {r[3]}")
    check("the unfiltered sum is larger, so the exclusion is load-bearing here",
          con.execute("SELECT SUM(value_num) FROM v_state_current WHERE as_of=? AND metric_id=?",
                      (day, met)).fetchone()[0] > r[3])
    check("a weekly-grain row is excluded from the month-end view entirely", wnr(con, day, 2)[4] == 1)

    bad = con.execute("SELECT COUNT(*) FROM v_net_worth WHERE n_measured + n_estimated + n_copy"
                      " + n_zero_from_blank + n_error <> n_components").fetchone()[0]
    check("the partition holds for EVERY group in the fixture", bad == 0, f"{bad} groups break it")
    mismatch = con.execute("""SELECT COUNT(*) FROM v_net_worth w WHERE COALESCE(w.total,-1) <>
            COALESCE((SELECT SUM(s.value_num) FROM v_state_current s
                      WHERE s.as_of = w.as_of AND s.metric_id = w.metric_id
                        AND s.is_additive = 1
                        AND s.period_grain IN ('monthly','month-end')), -1)""").fetchone()[0]
    check("every total equals the additive sum computed independently", mismatch == 0,
          f"{mismatch} groups differ")
    check("every group reports its composition (no NULL counts)",
          con.execute("SELECT COUNT(*) FROM v_net_worth WHERE n_measured IS NULL OR n_copy IS NULL"
                      " OR n_error IS NULL OR n_additive IS NULL").fetchone()[0] == 0)
    check("n_components of every group equals the current rows in that grain",
          con.execute("""SELECT COUNT(*) FROM v_net_worth w WHERE w.n_components <>
              (SELECT COUNT(*) FROM v_state_current s WHERE s.as_of = w.as_of
                 AND s.metric_id = w.metric_id
                 AND s.period_grain IN ('monthly','month-end'))""").fetchone()[0] == 0)
    con.close()


# ================================================================ 7. derivation via src_column

def section_derivation():
    print("\n-- 7. derivation_kind is attributed from src_column; absence reads as UNKNOWN")
    con = fresh(); seed(con)
    con.execute("INSERT INTO dim_metric(metric_id, name, is_flow, is_year_relative, polarity)"
                " VALUES (7,'SYN_DERIVED',0,0,'asset')")
    state(con, 1, 7, "2025-03-31", val=5.0, presence="estimated", origin="derived")
    pre = con.execute("SELECT COUNT(*) FROM v_state_current").fetchone()[0]

    def attr(acct, day="2025-03-31"):
        return con.execute("SELECT derivation_kind, n_column_candidates, column_map_id"
                           " FROM v_state_current WHERE metric_id=7 AND account_id=?"
                           " AND as_of=?", (acct, day)).fetchone()

    check("with no curated column, derivation_kind is NULL and n_column_candidates says so",
          attr(1) == (None, 0, None), f"got {attr(1)}")

    con.execute("INSERT INTO src_column(map_id, tab_id, col_index, header_text, account_id,"
                " metric_id, unit, origin, derivation_kind, role)"
                " VALUES (1,1,7,'Derived Col',1,7,'USD','derived','aggregate,chain','derived')")
    check("derivation_kind reaches the row through (source, account, metric)",
          attr(1) == ("aggregate,chain", 1, 1), f"got {attr(1)}")
    check("the attribution names the src_column row it came from",
          con.execute("SELECT column_map_id FROM v_state_current WHERE metric_id=7"
                      " AND account_id=1").fetchone()[0] is not None)
    check("curating a column added no row to the read surface",
          con.execute("SELECT COUNT(*) FROM v_state_current").fetchone()[0] == pre)

    # curated but undifferentiated: NULL derivation_kind WITH a candidate. The two NULLs
    # must stay distinguishable or "unknown" launders into "not derived".
    con.execute("INSERT INTO src_column(map_id, tab_id, col_index, header_text, account_id,"
                " metric_id, unit, origin, role) VALUES (2,1,8,'Plain Col',2,7,'USD','entered','value')")
    state(con, 2, 7, "2025-03-31", val=5.0, presence="measured", origin="entered")
    check("curated-and-plain is distinguishable from never-curated", attr(2) == (None, 1, 2),
          f"got {attr(2)}")

    # a key column is row addressing, never a value column (v0.3 section 4)
    con.execute("INSERT INTO src_column(map_id, tab_id, col_index, header_text, account_id,"
                " metric_id, origin, role) VALUES (3,1,0,'Date Key',3,7,'key','key')")
    state(con, 3, 7, "2025-03-31", val=5.0, presence="measured", origin="entered")
    check("a role='key' column never attributes a row's derivation", attr(3)[1] == 0,
          f"got {attr(3)}")

    # ambiguity is reported, never silently resolved away
    con.execute("INSERT INTO src_column(map_id, tab_id, col_index, header_text, account_id,"
                " metric_id, origin, derivation_kind, role) VALUES (4,1,9,'Dup Col',1,7,"
                "'derived','projection','derived')")
    r = attr(1)
    check("two candidate columns report n_column_candidates=2 instead of hiding it",
          r[1] == 2, f"got {r}")
    check("and the pick is deterministic (lowest map_id wins)", r == ("aggregate,chain", 2, 1),
          f"got {r}")

    # attribution is scoped to the winning row's own source
    con.execute("INSERT INTO src_tab(tab_id, source_id, tab, role, dedupe_rule, row_order)"
                " VALUES (2,2,'Synth Tab','raw','none','ascending-date')")
    con.execute("INSERT INTO src_column(map_id, tab_id, col_index, header_text, account_id,"
                " metric_id, origin, derivation_kind, role) VALUES (5,2,9,'Other Src',1,7,"
                "'external','chain','external')")
    state(con, 1, 7, "2025-04-30", val=6.0, presence="estimated", origin="external", src=2)
    state(con, 1, 7, "2025-04-30", val=5.0, presence="estimated", origin="derived", src=1)
    r = con.execute("SELECT source_id, derivation_kind, n_column_candidates FROM v_state_current"
                    " WHERE metric_id=7 AND as_of='2025-04-30'").fetchall()
    check("precedence still picks exactly one row", len(r) == 1 and r[0][0] == 1, f"got {r}")
    check("and the derivation comes from THAT source's column, not the rival's",
          r[0][1] == "aggregate,chain" and r[0][2] == 2, f"got {r}")
    con.close()


# ================================================================ 8. exposure changed no rows

def section_invariance():
    print("\n-- 8. exposing labels changed which COLUMNS are readable, never which ROWS")
    con = fresh(); seed(con)
    con.execute("UPDATE src_ref SET precedence=10, sheet_modified='2026-09-01T00:00:00'")
    # a deliberately gnarly store: equal precedence, a re-ingested batch, a non-latest
    # batch left behind, copies, errors, holdings and an event.
    state(con, 1, 1, "2025-06-30", val=10.0, batch=1)
    state(con, 1, 1, "2025-06-30", val=11.0, batch=2)
    state(con, 2, 1, "2025-06-30", val=44.0, src=1, batch=1)
    state(con, 2, 1, "2025-06-30", val=99.0, src=2, batch=1)
    state(con, 3, 1, "2025-06-30", val=30.0, presence="measured", origin="copy")
    state(con, 4, 1, "2025-06-30", txt="synth-TOKEN", presence="error", origin="derived",
          error_type="synth-TOKEN")
    state(con, 1, 2, "2025-07-31", val=1.0, grain="monthly")
    state(con, 2, 2, "2025-07-31", val=2.0, grain="weekly")
    # a monthly component that carries TEXT but never errored: the old n_error counted it
    state(con, 4, 2, "2025-07-31", txt="awaiting-statement", presence="measured", origin="entered",
          grain="monthly")
    for nk, acct, shares, mv, presence, origin, batch in [
            ("h1", 1, 1.0, 10.0, "measured", "entered", 1),
            ("h2", 1, 1.0, 12.0, "measured", "copy", 2),
            ("h3", 2, 5.0, 50.0, "measured", None, 1)]:
        con.execute("INSERT INTO holding_state(natural_key, account_id, security_id, as_of,"
                    " shares, market_value, presence, origin, source_id, batch_id, ingested_at)"
                    " VALUES (?,?,1,?,?,?,?,?,1,?,?)",
                    (nk, acct, "2025-06-30", shares, mv, presence, origin, batch, ISOTIME))
    con.execute("INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date,"
                " txn_type_id, category_id, amount, unit, content_hash, source_id, batch_id,"
                " ingested_at) VALUES ('e1',1,'2025-06-15',1,1,1,3.0,'USD','hev1',1,1,?)",
                (ISOTIME,))

    made = []
    for v in VIEWS:
        base = view_ddl(BASELINE, v)
        check(f"pre-Slice-B DDL found for {v}", bool(base))
        if not base:
            continue
        renamed = re.sub(rf"\b{v}\b", f"b_{v}", base, count=1)
        for other in VIEWS:
            renamed = re.sub(rf"\b{other}\b", f"b_{other}", renamed)
        try:
            con.executescript(renamed)
            made.append(v)
            check(f"baseline {v} recreated alongside the new one", True)
        except Exception as e:
            check(f"baseline {v} recreated alongside the new one", False, str(e))

    def rows(sql):
        return sorted(con.execute(sql).fetchall())

    n_m1 = con.execute("SELECT COUNT(*) FROM v_state_current WHERE metric_id=1").fetchone()[0]
    check("the fixture really holds a re-ingested slice and a cross-source pair (4 winners)",
          n_m1 == 4, f"got {n_m1}")
    check("v_state_current returns EXACTLY the pre-Slice-B row set",
          rows("SELECT account_id, metric_id, as_of, value_num, value_text, period_grain,"
               " seq_in_date, source_id, batch_id, ingested_at FROM v_state_current")
          == rows("SELECT * FROM b_v_state_current"))
    check("v_state_conflicts returns EXACTLY the pre-Slice-B row set",
          rows("SELECT account_id, metric_id, as_of, value_num, value_text, source_id, batch_id,"
               " precedence, sheet_modified FROM v_state_conflicts")
          == rows("SELECT * FROM b_v_state_conflicts"))
    check("the equal-authority disagreement is still surfaced (1 reported, not 0)",
          con.execute("SELECT COUNT(*) FROM v_state_conflicts").fetchone()[0] == 1)
    check("v_holding_current returns EXACTLY the pre-Slice-B row set",
          rows("SELECT account_id, security_id, as_of, shares, cost_basis, market_value, price,"
               " purchase_date, source_id, batch_id, ingested_at FROM v_holding_current")
          == rows("SELECT * FROM b_v_holding_current"))
    check("v_cash_flow is byte-identical to its pre-Slice-B definition",
          view_ddl(DDL, "v_cash_flow") == view_ddl(BASELINE, "v_cash_flow"))
    check("v_assumption_current is byte-identical to its pre-Slice-B definition",
          view_ddl(DDL, "v_assumption_current") == view_ddl(BASELINE, "v_assumption_current"))
    check("v_net_worth covers the same groups with the same component counts",
          rows("SELECT as_of, metric_id, period_grain, n_components FROM v_net_worth")
          == rows("SELECT as_of, metric_id, period_grain, n_components FROM b_v_net_worth"))
    check("the old n_error would have mislabelled this fixture (the fix is exercised, not decorative)",
          rows("SELECT as_of, metric_id, n_error FROM v_net_worth")
          != rows("SELECT as_of, metric_id, n_error FROM b_v_net_worth"))
    check("the old total summed the copy; the new one does not",
          con.execute("SELECT total FROM b_v_net_worth WHERE metric_id=1").fetchone()[0]
          != con.execute("SELECT total FROM v_net_worth WHERE metric_id=1").fetchone()[0])
    unchanged = [v for v in ("v_state_current", "v_state_conflicts", "v_net_worth",
                             "v_holding_current") if v in made]
    check("the comparison is non-vacuous: all four baselines were recreated", len(unchanged) == 4,
          f"made: {unchanged}")
    same = [v for v in unchanged if view_ddl(DDL, v) == view_ddl(BASELINE, v)]
    check("and those four views really did change", not same, f"identical to baseline: {same}")
    con.close()


# ================================================================ 9. the honest limits

def section_limits():
    print("\n-- 9. what Slice B could not do, stated rather than papered over")
    con = fresh(); seed(con)
    check("fact_event carries no presence column (ratified scope, v0.3 section 2)",
          "presence" not in cols_of(con, "fact_event"))
    check("so v_cash_flow has nothing to expose — the gap is structural, not an oversight",
          "presence" not in cols_of(con, "v_cash_flow"))
    check("cash flow stays queryable on the qualifiers it does have",
          {"quality", "is_informational", "txn_type", "raw_label"} <= set(cols_of(con, "v_cash_flow")))
    check("assumption_register carries no presence either (v_assumption_current untouched)",
          "presence" not in cols_of(con, "assumption_register"))
    hs = set(cols_of(con, "holding_state"))
    check("holding_state DOES carry the labels, so v_holding_current had to expose them",
          {"presence", "origin", "error_type"} <= hs
          and {"presence", "origin", "error_type"} <= set(cols_of(con, "v_holding_current")))
    check("the breakdown covers the whole presence vocabulary plus copy",
          set(COMPOSITION_COLS) == {"n_" + v for v in presence_vocab()} | {"n_copy"},
          f"vocab {presence_vocab()}")
    con.close()


def main():
    print("== Slice B view-contract battery ==")
    for section in (section_build, section_exposure, section_classification, section_copy,
                    section_error, section_partition, section_derivation, section_invariance,
                    section_limits):
        section()
    print(f"\n{PASS} passed, {FAIL} failed")
    if FAILURES:
        print("FAILURES:", *FAILURES, sep="\n  ")
    print("BATTERY COMPLETE")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
