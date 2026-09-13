#!/usr/bin/env python3
"""DM-2026-01 blank-semantics battery (tools/tests).

Offline and synthetic only: hand-built artifact dicts + in-memory SQLite, no
Drive, no private/ books, no owner values. Proves the per-column blank rule:

  * default `zero` -> an in-rectangle blank materialises a zero_from_blank row;
  * declared `not_applicable` -> NO row for that cell, counted per column;
  * the anchored-blank guard FAILS LOUDLY: a blank at an EXPECTED anchor period
    (December for an annual column on a month-end spine) is reported by column
    and period, left visible in the batch note and in coverage_calendar, and is
    the predicate the CLI turns into a non-zero exit — a guard that cannot
    fail is not a guard;
  * the only silence is a period deliberately declared coverage_calendar
    .expected=0 (itself a visible declaration);
  * `series_start` (owner confirmation in DM-2026-01): before the declared start
    a column contributes nothing — a blank is not a stated zero and not a
    missing observation — while AT/AFTER the start the anchored-blank guard is
    unchanged (the added negative test proves the guard is still non-vacuous);
  * the report-only `SERIES SHAPE` detector names a single-month column, its
    count and share, and whether blank_means is declared, without changing what
    loads;
  * malformed declarations (bad value, unresolvable label, blank_means on the
    ssa_earnings family, series_start on that family) refuse the load.

Run from the repo root:
    python3 tools/tests/blank_semantics_tests.py
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


# ---------------------------------------------------------------- fixtures
def cell(a1, kind="literal", value=None, **kw):
    rec = {"a1": a1, "kind": kind, "value": value}
    rec.update(kw)
    return rec


def allow(blank_means, series_start=None):
    tabs = {"Synth Tab": {"header_row": 1, "first_data_row": 2, "key_column": "A",
                          "role": "raw", "grain": "month-end"}}
    if blank_means is not None:
        tabs["Synth Tab"]["blank_means"] = blank_means
    if series_start is not None:
        tabs["Synth Tab"]["series_start"] = series_start
    return {"sources": {"synthsrc": {"tabs": tabs}}}


SPEC = {
    "alias": "synthsrc:main", "drive_id": "drv-synth", "source_kind": "native-google-sheet",
    "read_path": "sheets.values.get", "precedence": 100, "role": "raw", "tab": "Synth Tab",
    "header_state": "confirmed", "header_row": 1, "dedupe_rule": "disjoint_by_key",
    "row_order": "ascending-date", "grain": "month-end", "family": "state",
    "columns": [
        {"col": "Date", "role": "as_of"},
        {"col": "Alpha", "account": "ACCT_A", "metric": "MA"},
        {"col": "Beta", "account": "ACCT_B", "metric": "MB", "grain": "annual"},
    ],
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
     "scope_flag": None, "methodology": "synthetic annual metric on a month-end spine"},
]

# three live month-end rows; 2026-02 is absent from the source on purpose
ROWS = [("2026-01-31", 2), ("2026-03-31", 3), ("2026-12-31", 4)]


def artifact(alpha, beta, last_row=4):
    """alpha/beta: {row_index: value | None}; None -> an artifact blank cell."""
    cells = [cell("A1", value="Date"), cell("B1", value="Alpha"), cell("C1", value="Beta")]
    for (iso, r), av, bv in zip(ROWS, alpha, beta):
        cells.append(cell(f"A{r}", value=iso))
        if av is not None:
            cells.append(cell(f"B{r}", value=av))
        if bv is not None:
            cells.append(cell(f"C{r}", value=bv))
    return {
        "artifact_version": 1, "alias": "synthsrc", "tab": "Synth Tab",
        "spreadsheet": "Synth", "drive_id": "drv-synth", "sheet_id": 7,
        "requested_range": "'Synth Tab'!A1:Z100000",
        "returned_bounds": {"rows": 5, "cols": 3},
        "tab_extent": {"rows": 5, "cols": 3}, "truncated": False,
        "drive_modified": "2026-01-01T00:00:00Z", "fetched_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": "0" * 64, "merges": [],
        "ingest_rectangle": {"first_row": 2, "last_row": last_row,
                             "columns": ["A", "B", "C"], "derived": True},
        "with_notes": False, "cells": cells,
    }


def artifact_dates(dates, alpha, beta):
    """Like artifact(), but over an arbitrary date list (shape-detector fixtures)."""
    cells = [cell("A1", value="Date"), cell("B1", value="Alpha"), cell("C1", value="Beta")]
    for i, dt in enumerate(dates):
        r = 2 + i
        cells.append(cell(f"A{r}", value=dt))
        if alpha[i] is not None:
            cells.append(cell(f"B{r}", value=alpha[i]))
        if beta[i] is not None:
            cells.append(cell(f"C{r}", value=beta[i]))
    last = len(dates) + 1
    return {
        "artifact_version": 1, "alias": "synthsrc", "tab": "Synth Tab",
        "spreadsheet": "Synth", "drive_id": "drv-synth", "sheet_id": 7,
        "requested_range": "'Synth Tab'!A1:Z100000",
        "returned_bounds": {"rows": last, "cols": 3},
        "tab_extent": {"rows": last, "cols": 3}, "truncated": False,
        "drive_modified": "2026-01-01T00:00:00Z", "fetched_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": "0" * 64, "merges": [],
        "ingest_rectangle": {"first_row": 2, "last_row": last,
                             "columns": ["A", "B", "C"], "derived": True},
        "with_notes": False, "cells": cells,
    }


def run(con, art, allowdict):
    acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
    with tempfile.TemporaryDirectory() as td:
        ap = Path(td) / "art.json"
        ap.write_text(json.dumps(art))
        spec = {**SPEC, "artifact": str(ap)}
        with L.Batch(con, note="synthetic") as batch:
            res = L.load_structural_spec(con, batch, spec, allowdict, acct_ids, metric_ids)
    return res


def facts(con, metric, presence=None):
    q = ("SELECT f.as_of, f.presence FROM fact_state f JOIN dim_metric m "
         "ON m.metric_id=f.metric_id WHERE m.name=?")
    args = [metric]
    if presence:
        q += " AND f.presence=?"
        args.append(presence)
    return {(r[0], r[1]) for r in con.execute(q, args)}


def batch_note(con):
    return (con.execute("SELECT note FROM load_batch ORDER BY batch_id DESC LIMIT 1")
            .fetchone()[0] or "")


def main() -> int:
    print("== DM-2026-01 blank-semantics battery ==")

    print("\n-- default zero + declared not_applicable (non-anchor blanks)")
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, 7]), allow(
        {"Beta": {"value": "not_applicable", "note": "synthetic evidence"}}))
    check("load completes, not quarantined", res.get("quarantined") is False, res)
    check("no fact row for a not_applicable blank (non-anchor)",
          ("2026-01-31", "zero_from_blank") not in facts(con, "MB")
          and ("2026-01-31", "measured") not in facts(con, "MB"),
          sorted(facts(con, "MB")))
    check("default-zero blank materialises zero_from_blank",
          ("2026-01-31", "zero_from_blank") in facts(con, "MA"), sorted(facts(con, "MA")))
    check("populated December anchor writes measured rows",
          ("2026-12-31", "measured") in facts(con, "MA")
          and ("2026-12-31", "measured") in facts(con, "MB"), sorted(facts(con, "MB")))
    check("no anchored-blank findings when anchors are populated",
          res.get("anchored_blanks") == [], res.get("anchored_blanks"))
    zr = {c["label"]: c for c in (res.get("blank_report") or {}).get("columns", [])}
    check("per-column zero report present", set(zr) == {"Alpha", "Beta"}, zr)
    check("report: Alpha 1 zero materialised",
          zr.get("Alpha", {}).get("zeros") == 1, zr.get("Alpha"))
    check("report: Beta 1 not_applicable skip, 0 zeros",
          zr.get("Beta", {}).get("not_applicable") == 1
          and zr.get("Beta", {}).get("zeros") == 0, zr.get("Beta"))
    cov = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT period, status, expected FROM coverage_calendar")}
    check("coverage declares every month in the span expected",
          len(cov) == 12 and all(v[1] == 1 for v in cov.values()), cov)
    check("absent source month recorded absent-in-source, never zeroed",
          cov.get("2026-02", ("",))[0] == "absent-in-source", cov.get("2026-02"))

    print("\n-- NEGATIVE: blank at an EXPECTED anchor period fails loudly")
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, None]), allow(
        {"Beta": {"value": "not_applicable", "note": "synthetic evidence"}}))
    finds = res.get("anchored_blanks") or []
    check("anchored blank IS reported (the guard can fail)", len(finds) == 1, finds)
    check("finding names column, period and row",
          finds and finds[0]["column"] == "Beta" and finds[0]["period"] == "2026-12"
          and finds[0]["row"] == 4, finds)
    check("CLI exit predicate is non-empty (bagend.py turns this into exit 1)",
          bool(res.get("anchored_blanks")))
    check("no row written for the anchored blank — but loudly, not as hidden N/A",
          ("2026-12-31", "zero_from_blank") not in facts(con, "MB")
          and ("2026-12-31", "measured") not in facts(con, "MB"), sorted(facts(con, "MB")))
    check("the rest of the tab still loaded",
          ("2026-03-31", "measured") in facts(con, "MB"), sorted(facts(con, "MB")))
    check("batch note carries ANCHORED BLANK", "ANCHORED BLANK" in batch_note(con),
          batch_note(con))
    cov = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT period, status, expected FROM coverage_calendar")}
    check("anchor period stays visible as expected=1 in coverage_calendar",
          cov.get("2026-12", ("", 0))[1] == 1, cov.get("2026-12"))

    print("\n-- escape hatch: a period declared expected=0 stays silent, visibly")
    con = fresh()
    run(con, artifact([None, 1, 5], [None, 2, None]), allow(
        {"Beta": {"value": "not_applicable", "note": "synthetic evidence"}}))
    # first load registered src_ref + coverage; now declare the anchor NOT expected
    con.execute("UPDATE coverage_calendar SET expected=0 WHERE period='2026-12'")
    res = run(con, artifact([None, 1, 5], [None, 2, None]), allow(
        {"Beta": {"value": "not_applicable", "note": "synthetic evidence"}}))
    check("expected=0 anchor does NOT fire the guard",
          res.get("anchored_blanks") == [], res.get("anchored_blanks"))
    check("the declared-not-expected period keeps expected=0",
          con.execute("SELECT expected FROM coverage_calendar WHERE period='2026-12'")
          .fetchone()[0] == 0)

    print("\n-- declaration forms and refusals")
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, 7]),
              allow({"Beta": "not_applicable"}))
    check("plain string form accepted",
          ("2026-01-31", "zero_from_blank") not in facts(con, "MB")
          and res.get("anchored_blanks") == [])
    con = fresh()
    try:
        run(con, artifact([None, 1, 5], [None, 2, 7]), allow({"Beta": "sometimes"}))
        check("bad blank_means value refuses", False, "no LoadError")
    except L.LoadError as e:
        check("bad blank_means value refuses", "not one of" in str(e), str(e))
    con = fresh()
    try:
        run(con, artifact([None, 1, 5], [None, 2, 7]), allow({"Gamma": "not_applicable"}))
        check("declaration naming no resolvable column refuses", False, "no LoadError")
    except L.LoadError as e:
        check("declaration naming no resolvable column refuses",
              "no column of this spec resolves" in str(e), str(e))
    ssa_spec = {**SPEC, "alias": "synthsrc:ssa", "family": "ssa_earnings",
                "columns": [{"col": "Work Year", "role": "work_year"},
                            {"col": "Taxed A", "role": "ss_taxed"},
                            {"col": "Taxed B", "role": "medicare_taxed"}],
                "grain": "annual work year"}
    con = fresh()
    try:
        acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
        layout_ssa = (allow({"Taxed A": "not_applicable"})["sources"]["synthsrc"]
                      ["tabs"]["Synth Tab"])
        ssa_art = artifact([None], [None])
        ssa_art["cells"] = [cell("A1", value="Work Year"), cell("B1", value="Taxed A"),
                            cell("C1", value="Taxed B"), cell("A2", value=2001),
                            cell("B2", value=11)]
        ssa_art["ingest_rectangle"] = {"first_row": 2, "last_row": 2,
                                       "columns": ["A", "B", "C"], "derived": True}
        ssa_art["returned_bounds"] = {"rows": 3, "cols": 3}
        rect = L.declared_rectangle(ssa_spec, layout_ssa, ssa_art)
        with L.Batch(con, note="synthetic") as batch:
            L._load_ssa_earnings_structural(con, batch, ssa_spec, 1, layout_ssa,
                                            ssa_art, rect, acct_ids, metric_ids)
        check("blank_means on ssa_earnings refuses (row-grain presence family)",
              False, "no LoadError")
    except L.LoadError as e:
        check("blank_means on ssa_earnings refuses (row-grain presence family)",
              "not supported for the ssa_earnings family" in str(e), str(e))
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, 7]), allow(None))
    check("no blank_means at all -> everything defaults to zero",
          ("2026-01-31", "zero_from_blank") in facts(con, "MB"), sorted(facts(con, "MB")))

    print("\n-- series_start: where a column's series begins (DM-2026-01)")
    # Models the resolved S finding: a December BEFORE the declared start is
    # genuinely N/A, not a missing observation.
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, None]),
              allow({"Beta": {"value": "not_applicable", "note": "synthetic"}},
                    {"Beta": "2027-01"}))
    check("blank anchor BEFORE series_start is NOT a finding",
          res.get("anchored_blanks") == [], res.get("anchored_blanks"))
    check("blank anchor before series_start writes no row (N/A)",
          ("2026-12-31", "zero_from_blank") not in facts(con, "MB")
          and ("2026-12-31", "measured") not in facts(con, "MB"), sorted(facts(con, "MB")))
    zr = {c["label"]: c for c in (res.get("blank_report") or {}).get("columns", [])}
    check("report names the series_start and counts the pre-start skips",
          zr.get("Beta", {}).get("series_start") == "2027-01"
          and zr.get("Beta", {}).get("pre_start_skips") == 2, zr.get("Beta"))

    # A guard that cannot fail is not a guard: at/after the start, unchanged.
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, None]),
              allow({"Beta": {"value": "not_applicable", "note": "synthetic"}},
                    {"Beta": "2026-01"}))
    finds = res.get("anchored_blanks") or []
    check("blank anchor AT/AFTER series_start still fires (guard non-vacuous)",
          len(finds) == 1 and finds[0]["period"] == "2026-12", finds)
    check("post-start anchored blank keeps the CLI's non-zero exit predicate",
          bool(res.get("anchored_blanks")))
    check("the rest of the tab still loaded after a post-start finding",
          ("2026-03-31", "measured") in facts(con, "MB"), sorted(facts(con, "MB")))

    # object form accepted (value + evidence note), like blank_means
    con = fresh()
    res = run(con, artifact([None, 1, 5], [None, 2, 7]),
              allow({"Beta": {"value": "not_applicable", "note": "synthetic"}},
                    {"Beta": {"value": "2027-01", "note": "synthetic evidence"}}))
    zr = {c["label"]: c for c in (res.get("blank_report") or {}).get("columns", [])}
    check("object form of series_start accepted",
          res.get("anchored_blanks") == []
          and zr.get("Beta", {}).get("series_start") == "2027-01", zr.get("Beta"))

    # "a column contributes nothing before its start" for the default-zero rule too
    con = fresh()
    run(con, artifact([None, 1, None], [4, 5, 6]), allow(None, {"Alpha": "2026-03"}))
    check("a zero-default column writes nothing before its series_start",
          ("2026-01-31", "zero_from_blank") not in facts(con, "MA")
          and ("2026-01-31", "measured") not in facts(con, "MA"), sorted(facts(con, "MA")))
    check("a zero-default column still materialises a blank AT/AFTER its start",
          ("2026-12-31", "zero_from_blank") in facts(con, "MA"), sorted(facts(con, "MA")))

    print("\n-- series shape detector (report only, never a failure)")
    dec = [f"{y}-12-31" for y in range(2019, 2027)]     # 8 Decembers
    jan = [f"{y}-01-31" for y in range(2019, 2027)]     # 8 Januaries
    con = fresh()
    res = run(con, artifact_dates(dec + jan, [7] * 8 + [None] * 8, [8] * 8 + [None] * 8),
              allow({"Beta": {"value": "not_applicable", "note": "synthetic"}},
                    {"Beta": "2019-12"}))
    shapes = {s["label"]: s for s in (res.get("series_shapes") or [])}
    check("shape detector names single-month columns with >= 8 populated",
          set(shapes) == {"Alpha", "Beta"}, shapes)
    check("shape line carries count, share, month and declaration state",
          shapes.get("Beta", {}).get("populated") == 8
          and shapes["Beta"]["share_pct"] == 100 and shapes["Beta"]["month"] == 12
          and shapes["Beta"]["blank_means"] == "not_applicable", shapes.get("Beta"))
    check("shape line matches the documented example format",
          shapes.get("Beta", {}).get("line") ==
          ("SERIES SHAPE  Beta (C): 8 populated, 100% December -> annual-in-practice; "
           "blank_means declared not_applicable; series_start=2019-12"),
          shapes.get("Beta", {}).get("line"))
    check("an undeclared single-month column says so (still report only)",
          shapes.get("Alpha", {}).get("blank_means") == "zero"
          and "NOT declared" in shapes["Alpha"]["line"], shapes.get("Alpha", {}).get("line"))
    ma, mb = facts(con, "MA"), facts(con, "MB")
    check("shape detection does not change what is loaded (rules still apply)",
          sum(1 for r in ma if r[1] == "measured") == 8
          and sum(1 for r in ma if r[1] == "zero_from_blank") == 8
          and len(mb) == 8, (sorted(ma), sorted(mb)))
    con = fresh()
    res = run(con, artifact_dates(dec[:4] + jan[:4], [1] * 8, [2] * 8), allow(None))
    check("a column populated across several months produces no shape line",
          res.get("series_shapes") == [], res.get("series_shapes"))

    print("\n-- series_start declaration forms and refusals")
    con = fresh()
    try:
        run(con, artifact([None, 1, 5], [None, 2, 7]), allow(None, {"Beta": "1999-13"}))
        check("malformed series_start refuses", False, "no LoadError")
    except L.LoadError as e:
        check("malformed series_start refuses", "not a 'YYYY-MM' month" in str(e), str(e))
    con = fresh()
    try:
        run(con, artifact([None, 1, 5], [None, 2, 7]), allow(None, {"Gamma": "1999-12"}))
        check("series_start naming no resolvable column refuses", False, "no LoadError")
    except L.LoadError as e:
        check("series_start naming no resolvable column refuses",
              "no column of this spec resolves" in str(e), str(e))
    con = fresh()
    try:
        acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
        layout_ssa = allow(None, {"Taxed A": "1999-12"})["sources"]["synthsrc"]["tabs"]["Synth Tab"]
        ssa_spec = {**SPEC, "alias": "synthsrc:ssa", "family": "ssa_earnings",
                    "columns": [{"col": "Work Year", "role": "work_year"},
                                {"col": "Taxed A", "role": "ss_taxed"},
                                {"col": "Taxed B", "role": "medicare_taxed"}],
                    "grain": "annual work year"}
        ssa_art = artifact([None], [None])
        ssa_art["cells"] = [cell("A1", value="Work Year"), cell("B1", value="Taxed A"),
                            cell("C1", value="Taxed B"), cell("A2", value=2001),
                            cell("B2", value=11)]
        ssa_art["ingest_rectangle"] = {"first_row": 2, "last_row": 2,
                                       "columns": ["A", "B", "C"], "derived": True}
        ssa_art["returned_bounds"] = {"rows": 3, "cols": 3}
        rect = L.declared_rectangle(ssa_spec, layout_ssa, ssa_art)
        with L.Batch(con, note="synthetic") as batch:
            L._load_ssa_earnings_structural(con, batch, ssa_spec, 1, layout_ssa,
                                            ssa_art, rect, acct_ids, metric_ids)
        check("series_start on ssa_earnings refuses (no per-column row grain)",
              False, "no LoadError")
    except L.LoadError as e:
        check("series_start on ssa_earnings refuses (no per-column row grain)",
              "series_start is not supported for the ssa_earnings family" in str(e), str(e))

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAILURES:
        print("FAILURES:", *FAILURES, sep="\n  ")
    print("BATTERY COMPLETE")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
