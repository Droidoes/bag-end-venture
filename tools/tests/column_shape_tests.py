#!/usr/bin/env python3
"""E5b gate — the REAL per-column shape assertions (blueprint v0.3 §E4 + §E5b).

Why this battery exists: §E4's load-time shape assertions were VACUOUS for the first
wave — the allow-list declared no per-column expectation, so there was nothing to
check against and no way for the assertion to fail. A renamed header, a column
inserted into a mapped tab, or a duplicate header label stealing a metric would have
loaded the wrong figures into the wrong metrics SILENTLY (`.scratch/e5b/shift_probe.py`
demonstrates exactly that against the pre-change loader: `status=complete`, 1789 rows,
geometry one letter off). This file proves the opposite: the loader now refuses.

The contract it pins (see tools/manifests/layouts.schema.md §`columns`):

  * the allow-list tab entry declares `columns`, keyed by COLUMN LETTER (the join key),
    each an object {expected_label, role} (+ optional `note` as evidence);
  * `role` is the src_column.role vocabulary — value · key · derived · external ·
    copy · scratch. `metric_id` is NOT allowed here: metric binding lives in the
    curation spec (v0.3 §D-4), and a declaration carrying one refuses;
  * every column the curation spec maps (or skips) must be DECLARED, or the spec
    quarantines (`column-undeclared`) — an undeclared column is the vacuity this leg
    exists to end. A declared letter the spec does not name is still pinned (the
    geometry is checked either way);
  * the artifact's header cell at `{letter}{header_row}` must carry `expected_label`
    (`column-label-mismatch`) — `expected_label: null` means that letter must carry NO
    label (the unlabelled key-column case);
  * the column's OBSERVED character must be consistent with its declared role
    (`column-role-mismatch`): `key` ⟺ the row-addressing column, `value` entered-
    dominant, `derived` derivation-bearing (or its derivation STATED in curation as
    `mode: derive_from_delta`), `external` cross-sourced (sheet reference / IMPORT*
    function, or `external_links` membership), `copy` pure references, `scratch` no
    account/metric binding;
  * a column with NO observations in the rectangle contradicts nothing — absence is
    not a shape mismatch (a blank is DM-2026-01's business, never this one).

Malformed declarations (unknown role, non-letter key, missing expected_label, a
duplicate letter after case-folding, `metric_id` present, a non-object map) are
`LoadError`s: a broken allow-list is a curation bug, so the load stops rather than
quarantining a spec that was never describable.

Offline and synthetic only: hand-built artifact dicts + in-memory SQLite, no Drive,
no private/ books, no owner values. Fixture labels are Date/Alpha/Beta/Pull/Echo/
Total/Spare.

The E5b entry points are reached through `gate()`, so a loader WITHOUT the gate
reports FAIL on every assertion instead of crashing — that is what makes the
fail-before run against `git show HEAD:tools/bagend/loader21.py` countable. Nothing
here pins a version literal (tools/tests/README.md rule 2).

Run from the repo root:
    python3 tools/tests/column_shape_tests.py
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


def gate(name):
    """An E5b entry point, or None when the loader has no such gate (pre-change)."""
    return getattr(L, name, None)


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


def decl(label, role, **kw):
    """One allow-list column declaration. label=None means 'must carry NO label'."""
    d = {"expected_label": label, "role": role}
    d.update(kw)
    return d


# The clean synthetic frame — one column per role, nothing undeclared, nothing shifted.
#   A Date   key       row addressing            (mapped, role as_of)
#   B Alpha  value     typed literals            (mapped)
#   C Beta   derived   =B#*2   same-tab          (mapped)
#   D Pull   external  ='Other Tab'!B#           (mapped)
#   E Echo   copy      =B#     pure reference    (mapped)
#   F Total  derived   =SUM(B#:C#)               (SKIP column, declared anyway)
#   G Spare  value     typed literals            (declared, never named by the spec:
#                                                 the geometry pin beyond the labels)
CLEAN = {
    "A": ("Date", "key", "literal"),
    "B": ("Alpha", "value", "literal"),
    "C": ("Beta", "derived", "=B{r}*2"),
    "D": ("Pull", "external", "='Other Tab'!B{r}"),
    "E": ("Echo", "copy", "=B{r}"),
    "F": ("Total", "derived", "=SUM(B{r}:C{r})"),
    "G": ("Spare", "value", "literal"),
}
COLUMNS_CLEAN = {let: decl(lbl, role) for let, (lbl, role, _f) in CLEAN.items()}
LETTERS = tuple(CLEAN)                       # A..G
ROWS = (2, 3)


def layout(columns=COLUMNS_CLEAN, **kw):
    tab = {"header_row": 1, "first_data_row": 2, "key_column": "A", "role": "raw",
           "grain": "month-end"}
    if columns is not None:
        tab["columns"] = columns
    tab.update(kw)
    return tab


def allow(entry):
    return {"sources": {"synthsrc": {"tabs": {"Synth Tab": entry}}}}


SPEC = {
    "alias": "synthsrc:main", "drive_id": "drv-synth", "source_kind": "native-google-sheet",
    "read_path": "sheets.values.get", "precedence": 100, "role": "raw", "tab": "Synth Tab",
    "header_state": "confirmed", "header_row": 1, "dedupe_rule": "disjoint_by_key",
    "row_order": "ascending-date", "grain": "month-end", "family": "state",
    "columns": [
        {"col": "Date", "role": "as_of"},
        {"col": "Alpha", "account": "ACCT_A", "metric": "MA"},
        {"col": "Beta", "account": "ACCT_B", "metric": "MB"},
        {"col": "Pull", "account": "ACCT_C", "metric": "MC"},
        {"col": "Echo", "account": "ACCT_D", "metric": "MD"},
    ],
    "skip_columns": ["Total"],
}
DIMS = [{"code": c, "institution": "synthetic", "registration": "other", "entity": "Joe",
         "purpose": "unsettled", "notes": ""}
        for c in ("ACCT_A", "ACCT_B", "ACCT_C", "ACCT_D")]
METRICS = [{"name": m, "is_flow": 0, "is_year_relative": 0, "polarity": "unknown",
            "unit": "USD", "scope_flag": None, "methodology": ""}
           for m in ("MA", "MB", "MC", "MD")]
DATES = {"2": "2026-01-31", "3": "2026-02-28"}
NUMBERS = {"2": 10, "3": 20}


def base_cells(letters=LETTERS, drop_data=()):
    """The clean frame: header row + two live month-end rows. `drop_data` removes a
    column's DATA cells but keeps its header (the unpopulated-column case)."""
    cells = [cell(f"{let}1", value=CLEAN[let][0]) for let in letters]
    for r in ROWS:
        cells.append(cell(f"A{r}", value=DATES[str(r)]))
        for let in letters:
            if let in drop_data or let == "A":
                continue
            spec = CLEAN[let][2]
            if spec == "literal":
                cells.append(cell(f"{let}{r}", value=NUMBERS[str(r)]))
            else:
                cells.append(cell(f"{let}{r}", kind="formula", value=NUMBERS[str(r)],
                                  formula=spec.format(r=r)))
    return cells


def artifact(cells, columns=("A", "B", "C", "D", "E", "F", "G"), last_row=3):
    return {
        "artifact_version": 1, "alias": "synthsrc", "tab": "Synth Tab", "spreadsheet": "Synth",
        "drive_id": "drv-synth", "sheet_id": 7,
        "requested_range": "'Synth Tab'!A1:Z100000",
        "returned_bounds": {"rows": last_row,
                            "cols": max([L.col_index(c) for c in columns] or [0]) + 1},
        "tab_extent": {"rows": 100, "cols": 26}, "truncated": False,
        "drive_modified": "2026-01-01T00:00:00Z", "fetched_at": "2026-01-01T00:00:00Z",
        "artifact_sha256": "0" * 64, "merges": [],
        "ingest_rectangle": {"first_row": 2, "last_row": last_row,
                             "columns": list(columns), "derived": True},
        "with_notes": False, "cells": cells,
    }


def shift_right(cells, at="C", label="Ins"):
    """Insert a column AT `at`: every letter from there rightwards moves one, and the
    labels travel WITH their data — so a label-based resolution still finds them all.
    This is the shift a rename check cannot see."""
    start, out = L.col_index(at), []
    for c in cells:
        col, row = L._split_a1(c["a1"])
        ci = L.col_index(col)
        out.append({**c, "a1": f"{L.col_letters(ci + (1 if ci >= start else 0))}{row}"})
    out.append(cell(f"{at}1", value=label))
    return out


def shift_map(mapping, at="C"):
    """Re-key a letter-keyed mapping the way the frame moved."""
    start, out = L.col_index(at), {}
    for letter, v in mapping.items():
        ci = L.col_index(letter)
        out[L.col_letters(ci + (1 if ci >= start else 0))] = v
    return out


def dup_label(cells, at="B", label="Alpha"):
    """A column INSERTED at `at` whose header REPEATS a mapped label, pushing the real
    Alpha rightwards: the label-based join takes the FIRST hit, so without a geometry
    pin the metric is served from the wrong column."""
    out = shift_right(cells, at, label=label)
    for r in ROWS:
        out.append(cell(f"{at}{r}", value=99))
    return out


def run_gate(art, entry, spec=SPEC):
    rect = L.declared_rectangle(spec, entry, art)
    f = gate("assert_column_declarations")
    if f is None:
        raise AttributeError("loader21.assert_column_declarations does not exist")
    return f(art, rect, entry, spec)


def quarantine_of(art, entry, spec=SPEC):
    """The Quarantine the gate raises, None when it passes, AttributeError pre-change."""
    try:
        run_gate(art, entry, spec)
    except L.Quarantine as q:
        return q
    except AttributeError as e:
        return e
    return None


def load(con, art, entry, spec=SPEC):
    """End-to-end structural load. Returns (result, batch status, fact-row count)."""
    acct_ids, metric_ids = L.ensure_dims(con, DIMS, METRICS)
    with tempfile.TemporaryDirectory() as td:
        ap = Path(td) / "art.json"
        ap.write_text(json.dumps(art))
        with L.Batch(con, note="e5b") as b:
            res = L.load_structural_spec(con, b, {**spec, "artifact": str(ap)},
                                         allow(entry), acct_ids, metric_ids)
    status = con.execute("SELECT status FROM load_batch").fetchone()[0]
    facts = con.execute("SELECT COUNT(*) FROM fact_state").fetchone()[0]
    return res, status, facts


def with_role(letter, role):
    cols = {k: dict(v) for k, v in COLUMNS_CLEAN.items()}
    cols[letter] = decl(cols[letter]["expected_label"], role)
    return layout(cols)


def main() -> int:
    print("== E5b per-column shape battery ==")
    if gate("assert_column_declarations") is None:
        print("  NOTE  the loader under test has NO E5b gate — every assertion below must FAIL")

    # ------------------------------------------------ 1. declaration parsing
    print("\n-- declaration parsing (a broken allow-list stops the load)")
    f = gate("column_declarations")
    rect = L.declared_rectangle(SPEC, layout(), artifact(base_cells()))
    if f is None:
        check("loader21.column_declarations exists", False, "missing on this loader")
    else:
        got = f(layout(), SPEC)
        check("declarations resolve to the declared letters",
              {L.col_letters(ci) for ci in got} == set(COLUMNS_CLEAN), sorted(got))
        check("each declaration carries its label and role",
              all(g["role"] and "expected_label" in g for g in got.values()), got)
        for bad, why in (
            ({"A": decl("Date", "measure")}, "role outside the src_column vocabulary"),
            ({"A": {"role": "key"}}, "expected_label absent"),
            ({"A": {"expected_label": "Date", "roles": "key"}}, "role misspelled"),
            ({"A": decl(7, "key")}, "expected_label neither a string nor null"),
            ({"1": decl("Date", "key")}, "key is not a column letter"),
            ({"A": "key"}, "a bare string is not an object"),
            ({"A": dict(COLUMNS_CLEAN["A"], metric_id="TOTAL_ASSETS")},
             "metric_id is not an allow-list field"),
            ({"A": decl("Date", "key"), "a": decl("Alpha", "value")},
             "two keys folding to one letter"),
        ):
            try:
                f(layout(columns=bad), SPEC)
                check(f"malformed declaration refuses ({why})", False, "no LoadError")
            except L.LoadError:
                check(f"malformed declaration refuses ({why})", True)
            except Exception as e:
                check(f"malformed declaration refuses ({why})", False,
                      f"{type(e).__name__}: {e}")
        try:
            f(layout(columns="nope"), SPEC)
            check("a non-object columns map refuses", False, "no LoadError")
        except L.LoadError:
            check("a non-object columns map refuses", True)

    # ------------------------------------------------ 2. the good frame still loads
    print("\n-- the clean frame loads (pre-existing behaviour, kept green)")
    try:
        rep = run_gate(artifact(base_cells()), layout())
        check("the clean declared frame passes the gate", True)
        check("the gate reports every declared column once",
              isinstance(rep, dict) and len(rep.get("declared") or []) == len(COLUMNS_CLEAN),
              (rep or {}).get("declared"))
        check("the report names each column's letter, role and observed character",
              all({"letters", "role", "observed", "declared_label"} <= set(d)
                  for d in rep["declared"]), (rep or {}).get("declared"))
        check("the report counts kinds and never a value",
              all({"literal", "derived", "external", "copy", "blank", "populated"}
                  <= set(d["observed"]) for d in rep["declared"]), rep["declared"][:1])
        check("the report carries the bijection's key column",
              rep.get("key_column") == "A" and rep.get("header_row") == 1, rep)
    except Exception as e:
        check("the clean declared frame passes the gate", False, f"{type(e).__name__}: {e}")
    con = fresh()
    res, status, facts = load(con, artifact(base_cells()), layout())
    check("clean structural load is not quarantined", not res.get("quarantined"), res)
    check("clean load writes fact rows (the gate does not block the good frame)",
          facts > 0, facts)
    check("clean batch status is 'complete'", status == "complete", status)
    check("the load result carries the E5b report", bool(res.get("column_shape")), sorted(res))

    # ------------------------------------------------ 3. NEGATIVE: renamed header
    print("\n-- NEGATIVE: a renamed header at the expected column")
    renamed = [cell("G1", value="Spare (renamed)") if c["a1"] == "G1" else c
             for c in base_cells()]
    q = quarantine_of(artifact(renamed), layout())
    check("a renamed header is REFUSED by the geometry pin",
          isinstance(q, L.Quarantine) and q.rule == "column-label-mismatch",
          f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")
    check("the refusal names the letter, the row and both labels",
          isinstance(q, L.Quarantine) and "G1" in q.detail and "Spare" in q.detail
          and "renamed" in q.detail, getattr(q, "detail", ""))
    con = fresh()
    res, status, facts = load(con, artifact(renamed), layout())
    check("renamed header -> the spec quarantines", res.get("quarantined") is True, res)
    check("renamed header -> NOT ONE fact row written", facts == 0, facts)
    check("renamed header -> src_column untouched",
          con.execute("SELECT COUNT(*) FROM src_column").fetchone()[0] == 0)
    check("renamed header -> load_batch.status='partial'", status == "partial", status)
    cov = con.execute("SELECT status, note FROM coverage_calendar").fetchall()
    check("renamed header -> coverage_calendar records not-loaded naming the rule",
          cov and all(r[0] == "not-loaded" and "column-label-mismatch" in (r[1] or "")
                      for r in cov), cov[:2])
    # and a renamed header on a column the curation spec names: refused, by either rule
    mapped_rename = [cell("B1", value="Alpha (renamed)") if c["a1"] == "B1" else c
                     for c in base_cells()]
    con = fresh()
    res, status, facts = load(con, artifact(mapped_rename), layout())
    check("a renamed MAPPED header is refused too (facts=0, batch partial)",
          res.get("quarantined") is True and facts == 0 and status == "partial",
          res.get("rule"))

    # ------------------------------------------------ 4. NEGATIVE: shifted frame
    print("\n-- NEGATIVE: a column inserted, shifting the frame right by one")
    sh_letters = tuple(L.col_letters(L.col_index(x) + (1 if L.col_index(x) >= 2 else 0))
                       for x in LETTERS)
    sh_art = artifact(shift_right(base_cells(), "C"), columns=("A", "B", "C") + sh_letters[2:],
                      last_row=3)
    q = quarantine_of(sh_art, layout())
    check("a shifted frame is REFUSED (not silently followed)",
          isinstance(q, L.Quarantine) and q.rule in ("column-label-mismatch",
                                                    "column-undeclared",
                                                    "column-role-mismatch"),
          f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")
    check("the refusal names the letters that moved",
          isinstance(q, L.Quarantine) and any(x in q.detail for x in ("D", "E", "F", "G")),
          getattr(q, "detail", ""))
    con = fresh()
    res, status, facts = load(con, sh_art, layout())
    check("shifted frame -> zero rows and a partial batch",
          res.get("quarantined") is True and facts == 0 and status == "partial",
          (res.get("rule"), facts, status))
    # the same frame, with the declarations moved to match it, loads again: the gate
    # pins the RATIFIED geometry, it does not freeze a fixture.
    con = fresh()
    ratified = dict(shift_map(COLUMNS_CLEAN, "C"))
    ratified["C"] = decl("Ins", "scratch")          # the inserted column, ratified
    res, status, facts = load(con, sh_art, layout(ratified))
    check("the same frame loads once the DECLARATIONS ratify it (geometry is re-ratified, "
          "never silently followed)",
          facts > 0 and not res.get("quarantined") and status == "complete", res)

    # ------------------------------------------------ 5. NEGATIVE: duplicate label
    print("\n-- NEGATIVE: a duplicate header label reaching for a mapped metric")
    dup_art = artifact(dup_label(base_cells(), "B"), columns=tuple("ABCDEFGH"))
    q = quarantine_of(dup_art, layout())
    check("a metric-stealing duplicate label is REFUSED",
          isinstance(q, L.Quarantine) and q.rule in ("column-label-mismatch",
                                                    "column-undeclared"),
          f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")
    con = fresh()
    res, status, facts = load(con, dup_art, layout())
    check("duplicate-label frame -> nothing loads", res.get("quarantined") is True
          and facts == 0, (res.get("rule"), facts))

    # ------------------------------------------------ 6. NEGATIVE: undeclared column
    print("\n-- NEGATIVE: an undeclared column (the vacuity, refused)")
    q = quarantine_of(artifact(base_cells()),
                      layout({k: v for k, v in COLUMNS_CLEAN.items() if k != "C"}))
    check("an undeclared MAPPED column refuses the load",
          isinstance(q, L.Quarantine) and q.rule == "column-undeclared"
          and "Beta" in getattr(q, "detail", ""),
          f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")
    q = quarantine_of(artifact(base_cells()), layout(columns=None))
    check("no `columns` map at all refuses (nothing-to-check-against is a finding)",
          isinstance(q, L.Quarantine) and q.rule == "column-undeclared",
          f"{type(q).__name__}:{getattr(q, 'rule', '')}")
    # the bijection is symmetric: a label the ARTIFACT carries and the layout does not
    # declare is refused even when no curation column binds it (a skipped column)
    q = quarantine_of(artifact(base_cells()),
                      layout({k: v for k, v in COLUMNS_CLEAN.items() if k != "F"}))
    check("an undeclared SKIPPED column is refused too (the frame must be ratified "
          "whole, not only the mapped part of it)",
          isinstance(q, L.Quarantine) and q.rule == "column-undeclared"
          and "Total" in getattr(q, "detail", ""),
          f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")
    # a letter that carries NO label (a spacer) needs no declaration: nothing to ratify
    spacer = artifact(base_cells() + [cell("H1", kind="blank"), cell("H2", kind="blank")],
                      columns=tuple("ABCDEFGH"))
    try:
        run_gate(spacer, layout())
        check("an unlabelled spacer column beyond the ratified band needs no declaration",
              True)
    except Exception as e:
        check("an unlabelled spacer column beyond the ratified band needs no declaration",
              False, f"{type(e).__name__}: {e}")

    # ------------------------------------------------ 7. NEGATIVE: role vs character
    print("\n-- NEGATIVE: the declared role contradicted by the artifact")
    for letter, role, why in (
        ("C", "value", "a wholly formula-derived column declared value"),
        ("B", "derived", "an all-literal column declared derived"),
        ("C", "external", "a same-tab derivation declared external"),
        ("B", "external", "an entered column declared external"),
        ("C", "copy", "an arithmetic derivation declared copy"),
        ("B", "key", "a non-addressing column declared key"),
        ("B", "scratch", "a metric-bound column declared scratch"),
        ("A", "value", "the row-addressing column declared value"),
    ):
        q = quarantine_of(artifact(base_cells()), with_role(letter, role))
        check(f"role contradiction refuses ({why})",
              isinstance(q, L.Quarantine) and q.rule == "column-role-mismatch",
              f"{type(q).__name__}:{getattr(q, 'rule', '')} {getattr(q, 'detail', '')}")

    # ------------------------------------------------ 8. stated derivations
    print("\n-- stated derivations (declare it, never infer it)")
    delta_spec = {k: v for k, v in SPEC.items() if k != "skip_columns"}
    delta_spec["columns"] = [{"col": "Date", "role": "as_of"},
                             {"col": "Alpha", "account": "ACCT_A", "metric": "MA",
                              "mode": "derive_from_delta"}]
    delta_art = artifact([cell("A1", value="Date"), cell("B1", value="Alpha"),
                          cell("A2", value="2026-01-31"), cell("B2", value=1997.5)],
                         columns=("A", "B"))
    delta_entry = layout({"A": decl("Date", "key"), "B": decl("Alpha", "derived")})
    try:
        run_gate(delta_art, delta_entry, delta_spec)
        check("a `derived` column whose derivation is STATED (derive_from_delta) passes", True)
    except Exception as e:
        check("a `derived` column whose derivation is STATED passes", False,
              f"{type(e).__name__}: {e}")
    plain_spec = dict(delta_spec)
    plain_spec["columns"] = [{"col": "Date", "role": "as_of"},
                             {"col": "Alpha", "account": "ACCT_A", "metric": "MA"}]
    try:
        run_gate(delta_art, delta_entry, plain_spec)
        check("a `derived` column with NO stated derivation refuses", False, "no Quarantine")
    except L.Quarantine as q:
        check("a `derived` column with NO stated derivation refuses",
              q.rule == "column-role-mismatch", q.rule)
    except Exception as e:
        check("a `derived` column with NO stated derivation refuses", False,
              f"{type(e).__name__}: {e}")

    ext_entry = layout({"A": decl("Date", "key"), "B": decl("Alpha", "external")},
                       external_links={"B": "Other Tab"})
    ext_spec = dict(SPEC, alias="synthsrc:ext", skip_columns=[])
    ext_spec["columns"] = [{"col": "Date", "role": "as_of"},
                           {"col": "Alpha", "account": "ACCT_A", "metric": "MA"}]
    ext_art = artifact([cell("A1", value="Date"), cell("B1", value="Alpha"),
                        cell("A2", value="2026-01-31"), cell("B2", value=5)],
                       columns=("A", "B"))
    try:
        run_gate(ext_art, ext_entry, ext_spec)
        check("`external_links` membership satisfies the `external` role "
              "(a declared-external column may carry measured literals)", True)
    except Exception as e:
        check("`external_links` membership satisfies the `external` role", False,
              f"{type(e).__name__}: {e}")

    # a GENERATED key spine (every key cell a formula, as the stats date column is) is
    # still a key: the role asserts ADDRESSING, never a cell kind. Had it demanded
    # entered values, the real first wave would refuse its own spine.
    gen_spec = dict(SPEC, alias="synthsrc:genkey", skip_columns=[])
    gen_spec["columns"] = [{"col": "Date", "role": "as_of"},
                           {"col": "Alpha", "account": "ACCT_A", "metric": "MA"}]
    gen_art = artifact([cell("A1", value="Date"), cell("B1", value="Alpha"),
                        cell("A2", kind="formula", value="2026-01-31",
                             formula="=EOMONTH(A1, 0)"), cell("B2", value=5),
                        cell("A3", kind="formula", value="2026-02-28",
                             formula="=EOMONTH(A2, 0)"), cell("B3", value=6)],
                       columns=("A", "B"))
    try:
        run_gate(gen_art, layout({"A": decl("Date", "key"), "B": decl("Alpha", "value")}),
                 gen_spec)
        check("a formula-generated key spine passes (key asserts addressing, not kind)",
              True)
    except Exception as e:
        check("a formula-generated key spine passes", False, f"{type(e).__name__}: {e}")
    # a spine with NO live key is refused too — by §E4's pre-existing first_data_row
    # check, not by a new one: the gate need not duplicate a check that already fires,
    # and asserting exactly which check fires is what keeps both honest.
    dead_art = artifact([cell("A1", value="Date"), cell("B1", value="Alpha"),
                         cell("B2", value=5)], columns=("A", "B"))
    con = fresh()
    res, status, facts = load(con, dead_art,
                              layout({"A": decl("Date", "key"), "B": decl("Alpha", "value")}),
                              gen_spec)
    check("a spine with no live key quarantines (rule shape-mismatch, zero rows)",
          res.get("quarantined") is True and res.get("rule") == "shape-mismatch"
          and facts == 0 and status == "partial",
          (res.get("rule"), facts, status))

    bare = artifact(base_cells(drop_data=("C",)))
    try:
        run_gate(bare, layout())
        check("an unpopulated mapped column contradicts nothing (absence ≠ mismatch)", True)
    except Exception as e:
        check("an unpopulated mapped column contradicts nothing", False,
              f"{type(e).__name__}: {e}")

    # ------------------------------------------------ 9. unlabelled key columns
    print("\n-- `expected_label: null` — that letter must carry NO label")
    unl_spec = dict(SPEC, alias="synthsrc:unl", skip_columns=[])
    unl_spec["columns"] = [{"col": "Alpha", "account": "ACCT_A", "metric": "MA"}]
    unl_entry = layout({"A": decl(None, "key"), "B": decl("Alpha", "value")})
    try:
        run_gate(artifact([cell("A1", kind="blank"), cell("B1", value="Alpha"),
                           cell("A2", value="2026-01-31"), cell("B2", value=5)],
                          columns=("A", "B")), unl_entry, unl_spec)
        check("an unlabelled key column passes while its header cell really is blank", True)
    except Exception as e:
        check("an unlabelled key column passes while the header cell is blank", False,
              f"{type(e).__name__}: {e}")
    try:
        run_gate(artifact([cell("A1", value="Sneaky"), cell("B1", value="Alpha"),
                           cell("A2", value="2026-01-31"), cell("B2", value=5)],
                          columns=("A", "B")), unl_entry, unl_spec)
        check("a label appearing where the layout declares NONE refuses", False,
              "no Quarantine")
    except L.Quarantine as q:
        check("a label appearing where the layout declares NONE refuses",
              q.rule == "column-label-mismatch", q.rule)
    except Exception as e:
        check("a label appearing where the layout declares NONE refuses", False,
              f"{type(e).__name__}: {e}")

    # ------------------------------------------------ 10. refusal routing (§7)
    print("\n-- every refusal follows the existing quarantine path (§7)")
    con = fresh()
    res, status, facts = load(con, artifact(base_cells()), with_role("D", "value"))
    check("a role mismatch quarantines the spec (never a partial load)",
          res.get("quarantined") is True and facts == 0, res)
    check("the result names the rule so the CLI can report it",
          res.get("rule") == "column-role-mismatch", res.get("rule"))
    note = con.execute("SELECT note FROM load_batch").fetchone()[0] or ""
    check("the batch note records the QUARANTINE with its rule",
          "QUARANTINE" in note and "column-role-mismatch" in note, note)
    check("load_batch.status is 'partial', not 'complete'", status == "partial", status)

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAIL:
        for fl in FAILURES:
            print(f"  FAILED: {fl}")
        return 1
    print("BATTERY COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
