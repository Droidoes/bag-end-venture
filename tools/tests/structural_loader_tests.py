#!/usr/bin/env python3
"""P2 gate — structural reader battery (blueprint v0.3 §4 classifier + §5 store
contract; v0.2.1 §E4 shape assertions, §D3 allow-list join/quarantine).

Offline and synthetic only: hand-built artifact dicts + in-memory SQLite, no
Drive, no private/ books, no owner values. Proves the reader classifies every
§4 state, refuses an orphan allow-list pair, refuses truncated/short coverage,
quarantines a shifted frame, materialises in-rectangle blanks, writes src_column
column-grain derivation, and leaves a VISIBLE partial batch on quarantine.

Run from the repo root:
    python3 tools/tests/structural_loader_tests.py
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


# E5b: the tab entry declares what each COLUMN IS — letter is the join key, the label
# is the assertion, the role is the src_column.role vocabulary. No metric_id here:
# metric binding lives in SPEC below (v0.3 §D-4).
ALLOW = {"sources": {"synthsrc": {"tabs": {
    "Synth Tab": {"header_row": 1, "first_data_row": 2, "key_column": "A", "role": "raw",
                  "columns": {
                      "A": {"expected_label": "Date", "role": "key"},
                      "B": {"expected_label": "Alpha", "role": "value"},
                      "C": {"expected_label": "Beta", "role": "derived"},
                      "D": {"expected_label": "Total", "role": "derived"},
                  }},
}}}}

SPEC = {
    "alias": "synthsrc:main", "drive_id": "drv-synth", "source_kind": "native-google-sheet",
    "read_path": "sheets.values.get", "precedence": 100, "role": "raw", "tab": "Synth Tab",
    "header_state": "confirmed", "header_row": 1, "dedupe_rule": "disjoint_by_key",
    "row_order": "ascending-date", "grain": "month-end", "family": "state",
    "columns": [
        {"col": "Date", "role": "as_of"},
        {"col": "Alpha", "account": "ACCT_A", "metric": "MA"},
        {"col": "Beta", "account": "ACCT_B", "metric": "MB"},
    ],
    "skip_columns": ["Total"],
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
     "scope_flag": None, "methodology": ""},
]


def artifact(cells, *, truncated=False, bounds=None, rect=None, merges=None, tab="Synth Tab"):
    return {
        "artifact_version": 1, "alias": "synthsrc", "tab": tab, "spreadsheet": "Synth",
        "drive_id": "drv-synth", "sheet_id": 7,
        "requested_range": f"'{tab}'!A1:Z100000",
        "returned_bounds": bounds or {"rows": 4, "cols": 4},
        "tab_extent": {"rows": 100, "cols": 10}, "truncated": truncated,
        "drive_modified": "2026-01-01T00:00:00Z", "fetched_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": "0" * 64, "merges": merges or [],
        "ingest_rectangle": rect or {"first_row": 2, "last_row": 3,
                                     "columns": ["A", "B", "C", "D"], "derived": True},
        "with_notes": False, "cells": cells,
    }


def base_cells():
    return [
        cell("A1", value="Date"), cell("B1", value="Alpha"),
        cell("C1", value="Beta"), cell("D1", value="Total"),
        cell("A2", value="2026-01-31"), cell("B2", value=10),
        cell("C2", kind="formula", value=20, formula="=B2*2"),
        cell("D2", kind="formula", value=30, formula="=SUM(B2:C2)"),
        cell("A3", value="2026-02-28"),
        cell("C3", kind="formula", value=0, formula="=B3*2"),
        cell("D3", kind="formula", value=0, formula="=SUM(B3:C3)"),
    ]


def ctx_for(cells, external=None, derived=None, layout=None):
    idx = {c["a1"]: c for c in cells}
    return L._CellCtx(idx, set(external or []), set(derived or []), layout or {}, SPEC)


def main() -> int:
    print("== P2 structural reader battery ==")

    # ---------------- §4 classifier table
    print("\n-- v0.3 §4 classifier")
    c = ctx_for([])
    r = L.classify_cell(cell("A1", value=5), 0, c)
    check("typed literal -> entered/measured",
          (r["origin"], r["presence"], r["value_num"]) == ("entered", "measured", 5.0), r)
    r = L.classify_cell(cell("A1", kind="blank"), 0, c)
    check("in-rectangle blank -> entered/zero_from_blank, materialised 0",
          (r["origin"], r["presence"], r["value_num"]) == ("entered", "zero_from_blank", 0.0), r)
    r = L.classify_cell(cell("A1", kind="formula", value=3, formula="=1+2"), 0, c)
    check("all-literal formula -> entered/measured/constant",
          (r["origin"], r["presence"], r["derivation"]) == ("entered", "measured", "constant"), r)
    r = L.classify_cell(cell("A1", kind="formula", value=9, formula="=B2+1"), 0, c)
    check("deterministic arithmetic -> derived/estimated/deterministic",
          (r["origin"], r["presence"], r["derivation"]) == ("derived", "estimated", "deterministic"), r)
    r = L.classify_cell(cell("A1", kind="formula", value=9, formula="=SUM(B2:C2)"), 0, c)
    check("aggregate over a span -> derived/{aggregate}",
          r["derivation"] == "aggregate", r)
    r = L.classify_cell(cell("A1", kind="formula", value=9, formula="=VLOOKUP(B2,B2:C2,2,0)"), 0, c)
    check("lookup -> derived/{projection}",
          r["derivation"] == "projection", r)
    derived_cells = [cell("B2", kind="formula", value=1, formula="=1+1"),
                     cell("A1", kind="formula", value=2, formula="=B2+1")]
    r = L.classify_cell(derived_cells[1], 0, ctx_for(derived_cells))
    check("depends on another derived cell -> {...chain}",
          r["derivation"] == "chain,deterministic", r)
    ext_cells = [cell("A1", kind="formula", value=1, formula="='Other Tab'!B2")]
    r = L.classify_cell(ext_cells[0], 0, ctx_for(ext_cells))
    check("cross-sheet reference -> external/estimated",
          (r["origin"], r["presence"]) == ("external", "estimated"), r)
    imp = [cell("A1", kind="formula", value=1, formula='=IFERROR(IMPORTRANGE("k","s"),0)')]
    r = L.classify_cell(imp[0], 0, ctx_for(imp))
    check("IMPORTRANGE -> external", r["origin"] == "external", r)
    copy_cells = [cell("B2", value=4), cell("A1", kind="formula", value=4, formula="=B2")]
    r = L.classify_cell(copy_cells[1], 0, ctx_for(copy_cells))
    check("pure reference -> copy, presence inherited (measured)",
          (r["origin"], r["presence"], r["copy_of"]) == ("copy", "measured", "B2"), r)
    copy_der = [cell("C2", value=1),
                cell("B2", kind="formula", value=4, formula="=C2+3"),
                cell("A1", kind="formula", value=4, formula="=B2")]
    r = L.classify_cell(copy_der[2], 0, ctx_for(copy_der))
    check("copy of a derived cell never raises trust",
          (r["origin"], r["presence"]) == ("copy", "estimated"), r)
    r = L.classify_cell(cell("A1", kind="error", error_type="#REF!"), 0, c)
    check("error -> derived/error with token",
          (r["origin"], r["presence"], r["value_text"]) == ("derived", "error", "#REF!"), r)
    r = L.classify_cell(cell("A1", kind="formula", value="", formula='=""'), 0, c)
    check("formula -> empty string is skipped, not ingested",
          r["skip_reason"] == "formula-empty-string", r)
    ext_col = ctx_for([cell("A1", value=7)], external=["A"])
    r = L.classify_cell(cell("A1", value=7), 0, ext_col)
    check("external_links membership overrides kind (literal -> external/measured)",
          (r["origin"], r["presence"]) == ("external", "measured"), r)
    try:
        L.classify_cell(cell("A1", kind="formula", value=1, formula="={1;2}"), 0, c)
        check("unparseable formula quarantines", False, "no Quarantine raised")
    except L.Quarantine as q:
        check("unparseable formula quarantines", q.rule == "unparseable-formula", q.rule)

    # ---------------- merges
    print("\n-- merges (E3) and spills (§3/§4)")
    anchor = cell("A1", value=3)
    shadow = cell("B1", kind="literal", value=3, merge_shadow_of="A1")
    r = L.classify_cell(shadow, 1, ctx_for([anchor, shadow]))
    check("merge shadow inherits the anchor (never a blank)",
          (r["origin"], r["presence"], r["value_num"]) == ("entered", "measured", 3.0), r)
    try:
        L.classify_cell(cell("B1", kind="blank", merge_shadow_of="A1"), 1,
                        ctx_for([cell("A1", kind="blank"), cell("B1", kind="blank",
                                                               merge_shadow_of="A1")]))
        check("merge shadow of a blank quarantines", False, "no Quarantine")
    except L.Quarantine as q:
        check("merge shadow of a blank quarantines", q.rule == "merge-shadow-of-blank", q.rule)
    spill_cells = [cell("A1", kind="formula", value=9, formula="=SUM(B1:B2)"),
                   cell("A2", kind="spill", value=9, spill_of="A1")]
    r = L.classify_cell(spill_cells[1], 0, ctx_for(spill_cells))
    check("array spill inherits spill_of anchor",
          (r["origin"], r["presence"], r["spill_of"]) == ("derived", "estimated", "A1"), r)
    try:
        L.classify_cell(cell("A2", kind="spill", value=9, spill_of=None), 0, ctx_for([]))
        check("indeterminate spill refuses", False, "no Quarantine")
    except L.Quarantine as q:
        check("indeterminate spill refuses", q.rule == "indeterminate-spill", q.rule)

    # ---------------- allow-list join (§D3)
    print("\n-- allow-list join (E4/D3)")
    src, tabk, entry = L.allow_list_entry(ALLOW, "synthsrc", "Synth_Tab", "t")
    check("filename-style spelling joins the declared tab",
          (src, tabk) == ("synthsrc", "Synth Tab"), (src, tabk))
    try:
        L.allow_list_entry(ALLOW, "synthsrc", "No Such Tab", "synthsrc:x")
        check("orphan (alias, tab) refuses, naming the pair", False, "no LoadError")
    except L.LoadError as e:
        check("orphan (alias, tab) refuses, naming the pair",
              "No Such Tab" in str(e) and "synthsrc" in str(e), str(e))
    try:
        L.allow_list_entry(ALLOW, "ghostsrc", "Synth Tab", "ghostsrc:x")
        check("orphan alias refuses", False, "no LoadError")
    except L.LoadError:
        check("orphan alias refuses", True)

    # ---------------- coverage + shape
    print("\n-- coverage (§3) and shape (E4)")
    art = artifact(base_cells())
    rect = L.declared_rectangle(SPEC, ALLOW["sources"]["synthsrc"]["tabs"]["Synth Tab"], art)
    L.assert_artifact_coverage(art, rect, "t")
    check("coverage accepted when bounds cover the rectangle", True)
    try:
        L.assert_artifact_coverage(artifact(base_cells(), truncated=True), rect, "t")
        check("truncated artifact refuses", False, "no LoadError")
    except L.LoadError:
        check("truncated artifact refuses", True)
    try:
        L.assert_artifact_coverage(artifact(base_cells(), bounds={"rows": 2, "cols": 4}), rect, "t")
        check("returned bounds short of the rectangle refuse", False, "no LoadError")
    except L.LoadError:
        check("returned bounds short of the rectangle refuse", True)
    L.assert_shape(art, rect, ALLOW["sources"]["synthsrc"]["tabs"]["Synth Tab"], SPEC)
    check("declared header labels + live first_data_row pass shape", True)

    bad_hdr = [cell("B1", value="Renamed") if c["a1"] == "B1" else c for c in base_cells()]
    try:
        L.assert_shape(artifact(bad_hdr), L.declared_rectangle(
            SPEC, ALLOW["sources"]["synthsrc"]["tabs"]["Synth Tab"], artifact(bad_hdr)),
            ALLOW["sources"]["synthsrc"]["tabs"]["Synth Tab"], SPEC)
        check("header label mismatch quarantines", False, "no Quarantine")
    except L.Quarantine as q:
        check("header label mismatch quarantines",
              q.rule in ("shape-mismatch", "header-label-missing"), q.rule)

    # skip_rows must not sit on a live key row
    skip_layout = {"header_row": 1, "group_row": 1, "first_data_row": 2, "skip_rows": [1],
                   "key_column": "A", "columns": ALLOW["sources"]["synthsrc"]["tabs"]
                   ["Synth Tab"]["columns"]}
    spec_skip = {**SPEC, "header_row": 1}
    try:
        L.assert_shape(artifact(base_cells()), L.declared_rectangle(
            spec_skip, skip_layout, artifact(base_cells())), skip_layout, spec_skip)
        check("skip_rows on a live key row quarantines", False, "no Quarantine")
    except L.Quarantine as q:
        check("skip_rows on a live key row quarantines", q.rule == "shape-mismatch", q.rule)

    # declared merges must be present
    merge_layout = {**ALLOW["sources"]["synthsrc"]["tabs"]["Synth Tab"], "merges": ["A1:B1"]}
    try:
        L.assert_shape(artifact(base_cells()), L.declared_rectangle(
            SPEC, merge_layout, artifact(base_cells())), merge_layout, SPEC)
        check("declared merge absent quarantines", False, "no Quarantine")
    except L.Quarantine as q:
        check("declared merge absent quarantines", q.rule == "shape-mismatch", q.rule)

    # ---------------- end-to-end structural load
    print("\n-- end-to-end structural load (§5 store contract)")
    con = fresh()
    acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
    with tempfile.TemporaryDirectory() as td:
        ap = Path(td) / "art.json"
        ap.write_text(json.dumps(artifact(base_cells())))
        spec = {**SPEC, "artifact": str(ap)}
        with L.Batch(con, note="synth") as b:
            res = L.load_structural_spec(con, b, spec, ALLOW, acct_ids, metric_ids)
        check("structural load reports rows, not quarantined",
              res["rows"] == 4 and not res["quarantined"], res)
        rows = con.execute("""SELECT m.name, f.presence, f.origin, f.value_num
                              FROM fact_state f JOIN dim_metric m USING(metric_id)
                              ORDER BY f.as_of, m.name""").fetchall()
        check("literal row measured/entered",
              any(r[0] == "MA" and r[1] == "measured" and r[2] == "entered" and r[3] == 10.0
                  for r in rows), rows)
        check("in-rectangle blank materialised as zero_from_blank",
              any(r[0] == "MA" and r[1] == "zero_from_blank" and r[3] == 0.0 for r in rows), rows)
        check("formula row derived/estimated",
              any(r[0] == "MB" and r[1] == "estimated" and r[2] == "derived" for r in rows), rows)
        cols = con.execute("""SELECT header_text, role, origin, derivation_kind
                              FROM src_column ORDER BY col_index""").fetchall()
        check("src_column populated for every declared column",
              [r[0] for r in cols] == ["Date", "Alpha", "Beta", "Total"], cols)
        check("src_column key role + column-grain derivation",
              cols[0][1] == "key" and cols[2][1] == "derived"
              and cols[2][3] == "deterministic", cols)
        status = con.execute("SELECT status FROM load_batch").fetchone()[0]
        check("clean structural batch is 'complete'", status == "complete", status)

    # ---------------- quarantine is visible
    print("\n-- quarantine is visible (§7)")
    con2 = fresh()
    a2, m2 = L.ensure_dims(con2, DIMS, METRICS)
    with tempfile.TemporaryDirectory() as td:
        bad = [cell("B1", value="Renamed") if c["a1"] == "B1" else c for c in base_cells()]
        ap = Path(td) / "art.json"
        ap.write_text(json.dumps(artifact(bad)))
        spec = {**SPEC, "artifact": str(ap)}
        with L.Batch(con2, note="synth-q") as b:
            res = L.load_structural_spec(con2, b, spec, ALLOW, a2, m2)
        check("shape mismatch -> quarantined result", res.get("quarantined") is True, res)
        check("no fact rows written for a quarantined spec",
              con2.execute("SELECT COUNT(*) FROM fact_state").fetchone()[0] == 0)
        cov = con2.execute("SELECT status, note FROM coverage_calendar").fetchall()
        check("coverage_calendar records not-loaded + the rule",
              cov and all(r[0] == "not-loaded" and "quarantined:" in r[1]
                          for r in cov), cov)
        st = con2.execute("SELECT status FROM load_batch").fetchone()[0]
        check("quarantined batch status is 'partial'", st == "partial", st)

    # ---------------- legal-pair guard
    print("\n-- legal (origin, presence) pairs (§4/§5)")
    try:
        L.require_legal_pair("key", "measured", "t")
        check("illegal pair refused at load time", False, "no LoadError")
    except L.LoadError:
        check("illegal pair refused at load time", True)
    L.require_legal_pair("external", "measured", "t")
    check("external x measured is legal", True)

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAIL:
        for f in FAILURES:
            print(f"  FAILED: {f}")
        return 1
    print("BATTERY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
