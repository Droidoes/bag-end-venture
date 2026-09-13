#!/usr/bin/env python3
"""v0.2.6 — `src_column.role` is DECLARATIVE; the allow-list owns it.

COS ruling, 2026-09-12: `role` answers "what is this column FOR", not "what do its
cells look like". Before this version the loader computed the role from origin
precedence, so a column the allow-list declares `value` but whose cells merely happen
to be formula-heavy (stats D and E: entered literals still predominate, but a single
derived cell won the precedence) was recorded as `derived`. Two fields with one name
answering two questions is the defect; the fix is that the OBSERVATION lives in
`origin` / `derivation_kind` and the DECLARATION lives in `role`.

This battery pins that split, and pins it in the one shape where the two disagree:

  * section 1 (synthetic, in-memory, offline): a column declared `value` with two
    entered literals and one derived formula loads with role='value' AND
    origin='derived' AND derivation_kind='deterministic' — the declaration and the
    observation both survive, on the same src_column row. The pre-v0.2.6
    origin-precedence rule could only ever have produced 'derived' there, so a revert
    fails this file.
  * section 2 (real first wave, when the private artifacts are present): loads the
    curated wave into a FRESH temp store and asserts, for EVERY src_column row, that
    role equals the role its allow-list `columns` entry declares — including the two
    columns (D, E) the ruling named. SKIPs cleanly when private/ is absent. Counts,
    letters and labels only: no financial value is read or printed.

Run from the repo root:
    python3 tools/tests/declared_role_tests.py
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from tools.bagend import loader21 as L

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


def fresh():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    return con


# ---------------------------------------------------------------- synthetic fixture
def cell(a1, kind="literal", value=None, **kw):
    rec = {"a1": a1, "kind": kind, "value": value}
    rec.update(kw)
    return rec


# The D/E shape in miniature: B is DECLARED value (two entered literals + one
# derived formula -> entered still predominates, so the §E5b gate passes), but ANY
# derived cell wins the old origin precedence. C is declared derived. D is a
# declared skip column, declared `scratch` (no binding). A is the key.
DECL = {
    "A": {"expected_label": "Date", "role": "key"},
    "B": {"expected_label": "Steady", "role": "value"},
    "C": {"expected_label": "Summed", "role": "derived"},
    "D": {"expected_label": "Spare", "role": "scratch"},
}
LAYOUT = {"header_row": 1, "first_data_row": 2, "key_column": "A", "role": "raw",
          "columns": DECL}
ALLOW = {"sources": {"probesrc": {"tabs": {"Probe Tab": LAYOUT}}}}
SPEC = {
    "alias": "probesrc:main", "drive_id": "drv-probe", "source_kind": "native-google-sheet",
    "read_path": "sheets.values.get", "precedence": 100, "role": "raw", "tab": "Probe Tab",
    "header_state": "confirmed", "header_row": 1, "dedupe_rule": "disjoint_by_key",
    "row_order": "ascending-date", "grain": "month-end", "family": "state",
    "columns": [
        {"col": "Date", "role": "as_of"},
        {"col": "Steady", "account": "ACCT_A", "metric": "MA"},
        {"col": "Summed", "account": "ACCT_B", "metric": "MB"},
    ],
    "skip_columns": ["Spare"],
}
DIMS = [
    {"code": "ACCT_A", "institution": "synthetic", "registration": "other", "entity": "Joe",
     "purpose": "unsettled", "notes": ""},
    {"code": "ACCT_B", "institution": "synthetic", "registration": "other", "entity": "Joe",
     "purpose": "unsettled", "notes": ""},
]
METRICS = [
    {"name": "MA", "is_flow": 0, "is_year_relative": 0, "polarity": "unknown", "unit": "USD",
     "scope_flag": None, "methodology": ""},
    {"name": "MB", "is_flow": 0, "is_year_relative": 0, "polarity": "unknown", "unit": "USD",
     "scope_flag": None, "methodology": "synthetic"},
]


def artifact():
    cells = [
        cell("A1", value="Date"), cell("B1", value="Steady"),
        cell("C1", value="Summed"), cell("D1", value="Spare"),
        cell("A2", value="2026-01-31"), cell("B2", value=10),
        cell("C2", kind="formula", value=10, formula="=SUM(B2:B2)"), cell("D2", value=7),
        cell("A3", value="2026-02-28"), cell("B3", value=11),
        cell("C3", kind="formula", value=22, formula="=B3*2"), cell("D3", value=8),
        # the derived cell in a column DECLARED value — the whole point
        cell("A4", value="2026-03-31"),
        cell("B4", kind="formula", value=12, formula="=B3+1"),
        cell("C4", kind="formula", value=12, formula="=SUM(B4:B4)"), cell("D4", value=9),
    ]
    return {
        "artifact_version": 1, "alias": "probesrc", "tab": "Probe Tab", "spreadsheet": "Probe",
        "drive_id": "drv-probe", "sheet_id": 3,
        "requested_range": "'Probe Tab'!A1:Z100000",
        "returned_bounds": {"rows": 5, "cols": 4},
        "tab_extent": {"rows": 50, "cols": 8}, "truncated": False,
        "drive_modified": "2026-01-01T00:00:00Z", "fetched_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": "0" * 64, "merges": [],
        "ingest_rectangle": {"first_row": 2, "last_row": 4,
                             "columns": ["A", "B", "C", "D"], "derived": True},
        "with_notes": False, "cells": cells,
    }


def load_synthetic():
    con = fresh()
    acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
    with tempfile.TemporaryDirectory() as td:
        ap = Path(td) / "probe.json"
        ap.write_text(json.dumps(artifact()))
        spec = {**SPEC, "artifact": str(ap)}
        with L.Batch(con, note="role-probe") as b:
            res = L.load_structural_spec(con, b, spec, ALLOW, acct_ids, metric_ids)
    return con, res


def declared_roles():
    return {ci: d["role"] for ci, d in L.column_declarations(LAYOUT, SPEC).items()}


def main() -> int:
    print("== v0.2.6 declared-role battery ==")

    # ---------------- section 1: the split, on the D/E shape
    print("\n-- 1. role is the DECLARATION, origin is the OBSERVATION (the D/E shape)")
    con, res = load_synthetic()
    check("the synthetic frame loads (no quarantine)", not res.get("quarantined"), res)

    decls = declared_roles()
    rows = con.execute("""SELECT col_index, role, origin, derivation_kind
                          FROM src_column ORDER BY col_index""").fetchall()
    check("every resolved column is written", len(rows) == len(decls), rows)

    mismatch = [r for r in rows if r[1] != decls.get(r[0])]
    check("EVERY mapped/declared column's role equals its allow-list declaration",
          not mismatch, [(L.col_letters(r[0]), r[1], decls.get(r[0])) for r in mismatch])

    by_ci = {r[0]: r for r in rows}
    b_role, b_origin, b_kind = by_ci[1][1], by_ci[1][2], by_ci[1][3]
    check("the declared `value` column records role='value'", b_role == "value",
          f"role={b_role!r}")
    check("...while its observed origin is 'derived' (the two disagree BY DESIGN)",
          b_origin == "derived", f"origin={b_origin!r}")
    check("...and the observation is not lost: derivation_kind='deterministic'",
          b_kind == "deterministic", f"derivation_kind={b_kind!r}")
    check("NON-VACUOUS: the pre-v0.2.6 origin-precedence rule would have said 'derived' "
          "for exactly this row", b_origin == "derived" and b_role == "value")
    check("control: the declared `derived` column records 'derived'",
          by_ci[2][1] == "derived" and by_ci[2][2] == "derived", by_ci[2])
    check("control: the declared skip column records 'scratch'",
          by_ci[3][1] == "scratch", by_ci[3])
    check("the row-grain observation survives too: the formula cell in a `value` column "
          "is still estimated/derived in fact_state",
          con.execute("""SELECT presence, origin FROM fact_state WHERE metric_id=
                         (SELECT metric_id FROM dim_metric WHERE name='MA')
                         ORDER BY as_of DESC LIMIT 1""").fetchone() == ("estimated", "derived"))
    check("and its literal neighbours are still measured/entered",
          con.execute("""SELECT COUNT(*) FROM fact_state WHERE metric_id=
                         (SELECT metric_id FROM dim_metric WHERE name='MA')
                         AND presence='measured' AND origin='entered'""").fetchone()[0] == 2)
    check("the store stamps the loader's schema version",
          con.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()[0]
          == L.SCHEMA_VERSION, L.SCHEMA_VERSION)
    con.close()

    # ---------------- section 2: the real first wave (guarded, SKIP when private/ absent)
    print("\n-- 2. the real first wave: every src_column.role == its declaration")
    layouts_p = Path("private/layouts/layouts.json")
    curation_p = Path("private/curation/v021_wave1.json")
    artifacts = [Path("private/raw/sheets/stats__Net_Worth_Data.json"),
                 Path("private/raw/sheets/ss-earning__Official_Data.json")]
    if not (layouts_p.exists() and curation_p.exists() and all(p.exists() for p in artifacts)):
        print("  SKIP  private layouts/curation/artifacts not present — "
              "synthetic section 1 above still gates the behaviour")
    else:
        allow = L.load_allow_list(layouts_p)
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "role-probe.db"
            con = sqlite3.connect(db)
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript(DDL)
            res = L.run_wave1(curation_p, con, structural=True)
            quarantined = sorted(k for k, v in res.items()
                                 if isinstance(v, dict) and v.get("quarantined"))
            check("the real first wave loads with no quarantine", not quarantined, quarantined)
            real = con.execute("""SELECT s.alias, t.tab, c.col_index, c.role
                                  FROM src_column c
                                  JOIN src_tab t ON t.tab_id = c.tab_id
                                  JOIN src_ref s ON s.source_id = t.source_id
                                  ORDER BY s.alias, t.tab, c.col_index""").fetchall()
            check("the real wave wrote src_column rows", len(real) > 0, len(real))
            bad = []
            for alias, tab, ci, role in real:
                _sk, _tk, entry = L.allow_list_entry(allow, alias.split(":", 1)[0], tab,
                                                     "role-probe")
                want = L.column_declarations(entry, {"alias": alias})[ci]["role"]
                if role != want:
                    bad.append((alias, L.col_letters(ci), role, want))
            check("EVERY real mapped column's role equals its allow-list declaration",
                  not bad, bad)
            # the two columns the ruling named
            stats = {ci: role for alias, tab, ci, role in real
                     if alias.startswith("stats:")}
            check("stats D and E (the divergence the ruling named) now record 'value'",
                  stats.get(3) == "value" and stats.get(4) == "value",
                  {L.col_letters(ci): stats.get(ci) for ci in (3, 4)})
            con.close()

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAILURES:
        print("FAILURES:", *FAILURES, sep="\n  ")
    print("BATTERY COMPLETE")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
