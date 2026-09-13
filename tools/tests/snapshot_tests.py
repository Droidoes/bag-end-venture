#!/usr/bin/env python3
"""P1 gate — OFFLINE classifier battery for the v0.3 §3 snapshot artifact.

No network, no Drive, no gws: drives bagend.sheets._assemble with synthetic
CellData / spreadsheets.get payloads (and, for one end-to-end case, patches
_call/metadata/get_file so the real snapshot() fetch path runs without any
network). Assertions are mapped to the v0.3 §4 classifier table and the §3
schema hard rules. Prints PASS/FAIL per case and a final BATTERY COMPLETE.

Contract: docs/superpowers/plans/2026-09-12-structural-prefetch-v0.3.md
Run: python3 tools/tests/snapshot_tests.py
"""
import copy
import hashlib
import json
import re
import socket
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

# Paranoid offline guard: any attempt to open a network connection fails the
# battery loudly instead of silently reaching for Drive.
def _offline(*_a, **_k):
    raise AssertionError("network attempted during the offline battery")

socket.create_connection = _offline
socket.getaddrinfo = _offline

from bagend import config, sheets                     # noqa: E402
from bagend.gws_client import GwsError                # noqa: E402

TAB = "Net-Worth Data"
FILE_ID = "1SYNTHETIC-DRIVE-ID-00000"
PASS = FAIL = 0
FAILURES: list[str] = []
ALL_KINDS_SEEN: set[str] = set()


def check(case, label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {case} :: {label}")
    else:
        FAIL += 1
        line = f"{case} :: {label}" + (f" — {detail}" if detail else "")
        FAILURES.append(line)
        print(f"  FAIL  {case} :: {label}" + (f" — {detail}" if detail else ""))


def banner(case, note=""):
    print(f"\n== {case}" + (f" — {note}" if note else ""))


def meta(rows=329, cols=19):
    return {"title": "Stats", "file_id": FILE_ID,
            "tabs": [{"title": TAB, "sheet_id": 4242, "rows": rows,
                      "columns": cols, "hidden": False}]}


def cell_data(**kw):
    return kw


def sheet_payload(cells, merges=None, rows=8, cols=6, title=TAB):
    """cells: {(r0, c0): CellData} -> one GridData block (startRow/startColumn 0)."""
    grid_rows = []
    for r in range(rows):
        grid_rows.append({"values": [cells.get((r, c), {}) for c in range(cols)]})
    return {"properties": {"title": title}, "merges": merges or [],
            "data": [{"startRow": 0, "startColumn": 0, "rowData": grid_rows}]}


def assemble(cells, merges=None, with_notes=False, extent=(329, 19),
             grid_rows=8, grid_cols=6, max_rows=100000, max_cols=200,
             drive_modified="2026-09-11T10:00:00Z",
             fetched_at="2026-09-12T10:00:00Z"):
    payload = sheets._assemble(
        meta(*extent), sheet_payload(cells, merges, grid_rows, grid_cols),
        alias="stats", file_id=FILE_ID, with_notes=with_notes,
        max_rows=max_rows, max_cols=max_cols, drive_modified=drive_modified,
        fetched_at=fetched_at)
    for c in payload["cells"]:
        ALL_KINDS_SEEN.add(c["kind"])
    return payload


def by_a1(payload, a1):
    return next((c for c in payload["cells"] if c["a1"] == a1), None)


def rc(a1):
    letters = re.match(r"[A-Z]+", a1).group(0)
    return int(re.sub(r"\D", "", a1)), sheets._letters_ordinal(letters) + 1


# ---------------------------------------------------------------------------
banner("formula", "§4: aggregate over a span → derived/estimated (artifact: kind=formula + real formula + typed value)")
cells = {
    (0, 0): cell_data(userEnteredValue={"stringValue": "net worth"},
                      effectiveValue={"stringValue": "net worth"}),
    (4, 7): cell_data(userEnteredValue={"formulaValue": "=SUM(H6:H50)"},
                      effectiveValue={"numberValue": 123.4},
                      userEnteredFormat={"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}),
}
p = assemble(cells, grid_rows=6, grid_cols=8)
h5 = by_a1(p, "H5")
check("formula", "kind=formula", bool(h5) and h5["kind"] == "formula", repr(h5))
check("formula", "real (unredacted) formula carried", bool(h5) and h5.get("formula") == "=SUM(H6:H50)")
check("formula", "error_type present and null on a clean formula",
      bool(h5) and "error_type" in h5 and h5["error_type"] is None)
check("formula", "numfmt_type=NUMBER", bool(h5) and h5.get("numfmt_type") == "NUMBER")
check("formula", "numfmt_pattern mandatory: #,##0", bool(h5) and h5.get("numfmt_pattern") == "#,##0")
check("formula", "typed value 123.4", bool(h5) and h5.get("value") == 123.4)
check("formula", "with_notes=False emits NOTHING note-related", '"note"' not in json.dumps(p))

# ---------------------------------------------------------------------------
banner("literal", "§4: typed literal → measured; §8 P1 gate: _typed serial→date gated on number format")
cells = {
    (0, 0): cell_data(userEnteredValue={"numberValue": 46023},
                      effectiveValue={"numberValue": 46023},
                      userEnteredFormat={"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}),
    (0, 1): cell_data(userEnteredValue={"numberValue": 45123},
                      effectiveValue={"numberValue": 45123},
                      effectiveFormat={"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}),
}
p = assemble(cells, grid_rows=1, grid_cols=2)
a1c, b1 = by_a1(p, "A1"), by_a1(p, "B1")
check("literal", "kind=literal for both", bool(a1c and b1) and a1c["kind"] == "literal" and b1["kind"] == "literal")
check("literal", "date serial 46023 → 2026-01-01 under DATE format",
      bool(a1c) and a1c.get("value") == "2026-01-01", repr(a1c))
check("literal", "numfmt_type=DATE / numfmt_pattern=yyyy-mm-dd",
      bool(a1c) and a1c.get("numfmt_type") == "DATE" and a1c.get("numfmt_pattern") == "yyyy-mm-dd")
check("literal", "HAZARD GUARD: plain 45123 under NUMBER format stays 45123, never a fake date",
      bool(b1) and b1.get("value") == 45123, repr(b1))
check("literal", "userEnteredFormat missing → effectiveFormat fallback for numfmt",
      bool(b1) and b1.get("numfmt_type") == "NUMBER" and b1.get("numfmt_pattern") == "#,##0.00")

# ---------------------------------------------------------------------------
banner("error", "§4: formula → error → presence 'error' (artifact: kind=error, error_type kept, formula retained)")
cells = {
    (3, 2): cell_data(userEnteredValue={"formulaValue": "=_FV(0.05,30,-500)"},
                      effectiveValue={"errorValue": {"type": "ERROR_TYPE_NAME",
                                                     "message": "#NAME? Unknown range name: _FV"}}),
}
p = assemble(cells, grid_rows=4, grid_cols=3)
c4 = by_a1(p, "C4")
check("error", "kind=error", bool(c4) and c4["kind"] == "error", repr(c4))
check("error", "error_type token #NAME? from the message", bool(c4) and c4.get("error_type") == "#NAME?")
check("error", "formula retained for diagnosis", bool(c4) and c4.get("formula") == "=_FV(0.05,30,-500)")
check("error", "value null", bool(c4) and c4.get("value") is None)
check("error", "enum fallback when the message carries no token",
      sheets._error_token({"type": "ERROR_TYPE_REF", "message": ""}) == "ERROR_TYPE_REF")
check("error", "#DIV/0! token survives extraction",
      sheets._error_token({"type": "ERROR_TYPE_DIVIDE_BY_ZERO", "message": "#DIV/0!"}) == "#DIV/0!")
check("error", "empty-string formula result is value='' (§4 'formula → empty string'), not null",
      sheets._effective_scalar({"stringValue": ""}) == "")

# ---------------------------------------------------------------------------
banner("spill", "§4: array spill inherits spill_of; indeterminate extent → spill_of null (loader quarantines)")
cells = {
    (1, 4): cell_data(userEnteredValue={"formulaValue": "=SEQUENCE(3)"},
                      effectiveValue={"numberValue": 1}),          # E2 anchor
    (2, 4): cell_data(effectiveValue={"numberValue": 2}),          # E3 spill
    (3, 4): cell_data(effectiveValue={"numberValue": 3}),          # E4 spill
    (8, 6): cell_data(effectiveValue={"stringValue": "orphan"}),   # G9: no formula neighbour
    (4, 4): cell_data(userEnteredValue={"stringValue": "x"},
                      effectiveValue={"stringValue": "x"}),        # E5 literal breaks the chain
    (5, 4): cell_data(effectiveValue={"numberValue": 9}),          # E6 spill, chain broken
}
p = assemble(cells, grid_rows=9, grid_cols=7)
e3, e4, g9 = by_a1(p, "E3"), by_a1(p, "E4"), by_a1(p, "G9")
check("spill", "E3 kind=spill spill_of=E2", bool(e3) and e3["kind"] == "spill" and e3.get("spill_of") == "E2", repr(e3))
check("spill", "E4 kind=spill spill_of=E2 (chased through E3)", bool(e4) and e4["kind"] == "spill" and e4.get("spill_of") == "E2")
check("spill", "spill cell carries its effective value", bool(e3) and e3.get("value") == 2)
check("spill", "anchor itself stays kind=formula", (by_a1(p, "E2") or {}).get("kind") == "formula")
check("spill", "chain broken by a literal → spill_of=null, never mis-attributed",
      (by_a1(p, "E6") or {}).get("kind") == "spill" and (by_a1(p, "E6") or {}).get("spill_of") is None,
      repr(by_a1(p, "E6")))
check("spill", "no formula neighbour → kind=spill with spill_of=null (quarantine signal)",
      bool(g9) and g9["kind"] == "spill" and g9.get("spill_of") is None, repr(g9))

# ---------------------------------------------------------------------------
banner("blank", "§4: in-rectangle blank → zero_from_blank; §3: blanks emitted explicitly, rectangle exposed")
cells = {
    (0, 0): cell_data(userEnteredValue={"stringValue": "Date"}),
    (0, 1): cell_data(userEnteredValue={"stringValue": "Income"}),
    (0, 2): cell_data(userEnteredValue={"stringValue": "Notes"}),
    (1, 0): cell_data(userEnteredValue={"numberValue": 46023}, effectiveValue={"numberValue": 46023}),
    (1, 2): cell_data(userEnteredValue={"stringValue": "salary"}, effectiveValue={"stringValue": "salary"}),
    (2, 0): cell_data(userEnteredValue={"numberValue": 46054}, effectiveValue={"numberValue": 46054}),
    # (1,1)=B2, (2,1)=B3, (2,2)=C3 stay empty -> explicit blanks
    (5, 6): cell_data(userEnteredValue={"stringValue": "stray"}, effectiveValue={"stringValue": "stray"}),
}
p = assemble(cells, grid_rows=6, grid_cols=7)
b2, b3, c3, g6 = by_a1(p, "B2"), by_a1(p, "B3"), by_a1(p, "C3"), by_a1(p, "G6")
rect = p["ingest_rectangle"]
check("blank", "B2 emitted as kind=blank (first data row, empty income)", bool(b2) and b2["kind"] == "blank", repr(b2))
check("blank", "B3 emitted as kind=blank", bool(b3) and b3["kind"] == "blank")
check("blank", "C3 emitted as kind=blank", bool(c3) and c3["kind"] == "blank")
check("blank", "blanks carry explicit value=null", bool(b2 and b3 and c3) and
      b2["value"] is None and b3["value"] is None and c3["value"] is None)
check("blank", "content cell in the rectangle is never a blank", bool(g6) and g6["kind"] == "literal")
check("blank", "rectangle first_row=2 (row after the topmost content row)",
      bool(rect) and rect["first_row"] == 2, repr(rect))
check("blank", "rectangle last_row=6 (last row that has any cell)", bool(rect) and rect["last_row"] == 6)
check("blank", "rectangle columns = content columns (A,B,C) ∪ stray (G)",
      bool(rect) and set(rect["columns"]) == {"A", "B", "C", "G"}, repr(rect))
check("blank", "rectangle flagged as writer-derived", bool(rect) and rect["derived"] is True)

# ---------------------------------------------------------------------------
banner("coverage", "§3: blanks inside the rectangle are cells; blanks outside it are absent — never inferred")
cells = {
    (0, 0): cell_data(userEnteredValue={"stringValue": "h1"}),
    (0, 1): cell_data(userEnteredValue={"stringValue": "h2"}),
    (1, 0): cell_data(userEnteredValue={"numberValue": 1}, effectiveValue={"numberValue": 1}),
    (3, 0): cell_data(userEnteredValue={"numberValue": 2}, effectiveValue={"numberValue": 2}),
    (3, 1): cell_data(userEnteredValue={"numberValue": 3}, effectiveValue={"numberValue": 3}),
}
p = assemble(cells, grid_rows=4, grid_cols=6)
emitted_cols = {re.match(r"[A-Z]+", c["a1"]).group(0) for c in p["cells"]}
emitted_rows = {int(re.sub(r"\D", "", c["a1"])) for c in p["cells"]}
check("coverage", "columns with no content anywhere (C–F) get no cells at all", emitted_cols <= {"A", "B"}, repr(sorted(emitted_cols)))
check("coverage", "rows beyond the last content row get no cells", max(emitted_rows) <= 4, repr(sorted(emitted_rows)))
gap = by_a1(p, "B3")   # row gap INSIDE the rectangle (0-based row 2 is empty)
check("coverage", "a gap row inside the rectangle still gets explicit blanks", bool(gap) and gap["kind"] == "blank", repr(gap))

# ---------------------------------------------------------------------------
banner("merged-header", "§4: merge shadow inherits anchor — merge-shadow ≠ blank")
merges = [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 3}]  # B1:C1
cells = {
    (0, 1): cell_data(userEnteredValue={"stringValue": "Income"}, effectiveValue={"stringValue": "Income"}),
    (0, 3): cell_data(userEnteredValue={"stringValue": "Date"}),
    (1, 3): cell_data(userEnteredValue={"numberValue": 46023}, effectiveValue={"numberValue": 46023}),
}
p = assemble(cells, merges=merges, grid_rows=3, grid_cols=5)
c1 = by_a1(p, "C1")
check("merged-header", "merges carried as A1 strings", p["merges"] == ["B1:C1"], repr(p["merges"]))
check("merged-header", "shadow C1 emitted explicitly", c1 is not None)
check("merged-header", "shadow is NOT a blank", bool(c1) and c1["kind"] != "blank")
check("merged-header", "shadow carries merge_shadow_of=B1", bool(c1) and c1.get("merge_shadow_of") == "B1")
check("merged-header", "shadow inherits anchor kind + value", bool(c1) and c1["kind"] == "literal" and c1.get("value") == "Income")
b1c = by_a1(p, "B1")
check("merged-header", "anchor record unchanged (no marker noise)", bool(b1c) and b1c["kind"] == "literal" and "merge_shadow_of" not in b1c)
check("merged-header", "merge-covered column C enters the rectangle", "C" in p["ingest_rectangle"]["columns"])
check("merged-header", "returned_bounds include the shadow column (D → 4 cols)",
      p["returned_bounds"] == {"rows": 2, "cols": 4}, repr(p["returned_bounds"]))

# ---------------------------------------------------------------------------
banner("notes", "D-3: opt-in only; masked formula, never raw note text")
NOTE_FORMULA = "=4777.21+6289.94"
NOTE_TEXT = "reconciled with January statement"
cells = {
    (0, 0): cell_data(userEnteredValue={"numberValue": 123.4}, effectiveValue={"numberValue": 123.4}, note=NOTE_FORMULA),
    (0, 1): cell_data(userEnteredValue={"numberValue": 7}, effectiveValue={"numberValue": 7}, note=NOTE_TEXT),
    (1, 0): cell_data(note="psst"),                                   # note-only cell
    (1, 1): cell_data(userEnteredValue={"numberValue": 8}, effectiveValue={"numberValue": 8}),
}
p_off = assemble(cells, with_notes=False, grid_rows=2, grid_cols=2)
p_on = assemble(cells, with_notes=True, grid_rows=2, grid_cols=2)
# NB: match the quoted KEY "note" — the bare substring would false-trip on the
# envelope's additive "with_notes" flag.
check("notes", "with_notes=False (default) emits NOTHING note-related", '"note"' not in json.dumps(p_off))
check("notes", "envelope records the opt-in state", p_on["with_notes"] is True and p_off["with_notes"] is False)
a1n, b1n, a2n = by_a1(p_on, "A1"), by_a1(p_on, "B1"), by_a1(p_on, "A2")
check("notes", "formula-note cell: has_note=true", bool(a1n) and a1n.get("note", {}).get("has_note") is True)
check("notes", "note_is_formula detected", bool(a1n) and a1n.get("note", {}).get("note_is_formula") is True)
check("notes", "formula masked via _redact_formula → =n+n", bool(a1n) and a1n["note"].get("formula_masked") == "=n+n")
check("notes", "raw formula-note text absent from the whole payload", NOTE_FORMULA not in json.dumps(p_on))
check("notes", "plain note: has_note=true, note_is_formula=false, no text field",
      bool(b1n) and b1n.get("note") == {"has_note": True, "note_is_formula": False})
check("notes", "raw plain-note text absent from the whole payload", NOTE_TEXT not in json.dumps(p_on))
check("notes", "a note-only cell inside the rectangle is a blank + note metadata",
      bool(a2n) and a2n["kind"] == "blank" and a2n.get("note", {}).get("has_note") is True, repr(a2n))

# ---------------------------------------------------------------------------
banner("two-zeros", "§9: a measured zero and a zero_from_blank must stay distinguishable")
cells = {
    (0, 0): cell_data(userEnteredValue={"stringValue": "a"}),
    (0, 1): cell_data(userEnteredValue={"stringValue": "b"}),
    (1, 0): cell_data(userEnteredValue={"numberValue": 0}, effectiveValue={"numberValue": 0}),
    # (1,1) stays empty -> explicit blank
}
p = assemble(cells, grid_rows=2, grid_cols=2)
a2, b2 = by_a1(p, "A2"), by_a1(p, "B2")
check("two-zeros", "measured zero: kind=literal value 0", bool(a2) and a2["kind"] == "literal" and a2["value"] == 0)
check("two-zeros", "the other zero: kind=blank value null", bool(b2) and b2["kind"] == "blank" and b2["value"] is None)
check("two-zeros", "the two zeros carry different kinds", a2["kind"] != b2["kind"])

# ---------------------------------------------------------------------------
banner("envelope", "§3: identity fields, truncation math, deterministic hash")
cells = {(0, 0): cell_data(userEnteredValue={"numberValue": 1}, effectiveValue={"numberValue": 1})}
p_full = assemble(cells, grid_rows=1, grid_cols=1)
check("envelope", "artifact_version=1", p_full["artifact_version"] == 1)
check("envelope", "alias/tab/spreadsheet carried", (p_full["alias"], p_full["tab"], p_full["spreadsheet"]) == ("stats", TAB, "Stats"))
check("envelope", "drive_id + sheet_id from metadata (never invented)",
      p_full["drive_id"] == FILE_ID and p_full["sheet_id"] == 4242)
check("envelope", "requested_range matches §3 shape …!A1:GR100000",
      p_full["requested_range"] == f"'{TAB}'!A1:GR100000", p_full["requested_range"])
check("envelope", "returned_bounds = actual content extent", p_full["returned_bounds"] == {"rows": 1, "cols": 1}, repr(p_full["returned_bounds"]))
check("envelope", "tab_extent from metadata gridProperties", p_full["tab_extent"] == {"rows": 329, "cols": 19})
check("envelope", "not truncated with the default window", p_full["truncated"] is False)
check("envelope", "truncated when the window is smaller than tab_extent (rows)",
      assemble(cells, grid_rows=1, grid_cols=1, max_rows=100)["truncated"] is True)
check("envelope", "truncated when the window is smaller than tab_extent (cols)",
      assemble(cells, grid_rows=1, grid_cols=1, max_cols=10)["truncated"] is True)
p_over = assemble({(2, 0): cells[(0, 0)]}, grid_rows=3, grid_cols=1, max_rows=1)
check("envelope", "truncated when returned data would exceed the request", p_over["truncated"] is True)
check("envelope", "fetched_at / drive_modified carried",
      p_full["fetched_at"] == "2026-09-12T10:00:00Z" and p_full["drive_modified"] == "2026-09-11T10:00:00Z")
p_later = assemble(cells, grid_rows=1, grid_cols=1,
                   fetched_at="2099-01-01T00:00:00Z", drive_modified="")
check("envelope", "hash covers merges+cells only — timestamps excluded",
      p_later["artifact_sha256"] == p_full["artifact_sha256"])
canonical = json.dumps({"merges": p_full["merges"], "cells": p_full["cells"]},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
check("envelope", "artifact_sha256 = sha256(canonical JSON of merges+cells)",
      p_full["artifact_sha256"] == hashlib.sha256(canonical).hexdigest())
cells2 = dict(cells)
cells2[(0, 0)] = cell_data(userEnteredValue={"numberValue": 2}, effectiveValue={"numberValue": 2})
check("envelope", "any cell change moves the hash",
      assemble(cells2, grid_rows=1, grid_cols=1)["artifact_sha256"] != p_full["artifact_sha256"])
p_empty = assemble({}, grid_rows=2, grid_cols=2)
check("envelope", "empty tab: rectangle null, zero bounds, nothing emitted",
      p_empty["ingest_rectangle"] is None and p_empty["returned_bounds"] == {"rows": 0, "cols": 0}
      and p_empty["cells"] == [])

# ---------------------------------------------------------------------------
banner("kitchen-sink", "one payload with every §4 state: totality, ordering, determinism")
mrg = [{"startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 1, "endColumnIndex": 3}]  # B2:C2
ks = {
    (0, 0): cell_data(userEnteredValue={"stringValue": "Net-Worth"}, effectiveValue={"stringValue": "Net-Worth"}),
    (1, 0): cell_data(userEnteredValue={"stringValue": "Date"}),
    (1, 1): cell_data(userEnteredValue={"stringValue": "Income"}, effectiveValue={"stringValue": "Income"}),  # merge anchor
    (1, 3): cell_data(userEnteredValue={"stringValue": "Notes"}),
    (2, 0): cell_data(userEnteredValue={"numberValue": 46023}, effectiveValue={"numberValue": 46023},
                      userEnteredFormat={"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}),
    (2, 1): cell_data(userEnteredValue={"formulaValue": "=SUM(B3:B50)"}, effectiveValue={"numberValue": 123.4},
                      userEnteredFormat={"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}),
    (2, 3): cell_data(userEnteredValue={"formulaValue": "=_FV(0.05,30,-500)"},
                      effectiveValue={"errorValue": {"type": "ERROR_TYPE_NAME", "message": "#NAME?"}}),
    (3, 0): cell_data(userEnteredValue={"numberValue": 46054}, effectiveValue={"numberValue": 46054},
                      userEnteredFormat={"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}),
    (3, 1): cell_data(userEnteredValue={"numberValue": 45123}, effectiveValue={"numberValue": 45123},
                      userEnteredFormat={"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}),
    (3, 3): cell_data(userEnteredValue={"formulaValue": "=SEQUENCE(2)"}, effectiveValue={"numberValue": 1}),
    (4, 3): cell_data(effectiveValue={"numberValue": 2}),   # D5 spill of D4
    (4, 5): cell_data(userEnteredValue={"stringValue": "memo"}, effectiveValue={"stringValue": "memo"},
                      note="check against statement"),
}
p1 = assemble(ks, merges=mrg, with_notes=True, grid_rows=5, grid_cols=6)
kinds = {c["kind"] for c in p1["cells"]}
check("kitchen-sink", "all five kinds present (totality over states)",
      kinds == {"literal", "formula", "error", "spill", "blank"}, repr(kinds))
keys = [rc(c["a1"]) for c in p1["cells"]]
check("kitchen-sink", "cells emitted once, in row-major order",
      keys == sorted(keys) and len(keys) == len(set(keys)))
check("kitchen-sink", "two runs produce identical cells (deterministic)",
      p1["cells"] == assemble(copy.deepcopy(ks), merges=copy.deepcopy(mrg), with_notes=True,
                              grid_rows=5, grid_cols=6)["cells"])
check("kitchen-sink", "merged shadow C2 = literal 'Income' via B2",
      (by_a1(p1, "C2") or {}).get("merge_shadow_of") == "B2" and (by_a1(p1, "C2") or {}).get("value") == "Income")
check("kitchen-sink", "C3 under the merge is a blank, not a shadow", (by_a1(p1, "C3") or {}).get("kind") == "blank")
check("kitchen-sink", "date cell typed to ISO; plain number NOT converted",
      (by_a1(p1, "A3") or {}).get("value") == "2026-01-01" and (by_a1(p1, "B4") or {}).get("value") == 45123)
check("kitchen-sink", "formula cell: kind/value/error_type triple",
      (by_a1(p1, "B3") or {}).get("kind") == "formula" and (by_a1(p1, "B3") or {}).get("value") == 123.4
      and (by_a1(p1, "B3") or {}).get("error_type") is None)
check("kitchen-sink", "error cell: kind=error + token", (by_a1(p1, "D3") or {}).get("kind") == "error"
      and (by_a1(p1, "D3") or {}).get("error_type") == "#NAME?")
check("kitchen-sink", "spill D5 → D4 with value", (by_a1(p1, "D5") or {}).get("spill_of") == "D4"
      and (by_a1(p1, "D5") or {}).get("value") == 2)
check("kitchen-sink", "note cell F5 has masked metadata only",
      (by_a1(p1, "F5") or {}).get("note") == {"has_note": True, "note_is_formula": False}
      and "check against statement" not in json.dumps(p1))

# ---------------------------------------------------------------------------
banner("snapshot-e2e", "end-to-end snapshot() with _call/metadata/get_file patched — still zero network")
calls = []

def fake_call(path, params, attempts=3):
    calls.append((list(path), dict(params)))
    grid = sheet_payload({
        (0, 1): cell_data(userEnteredValue={"stringValue": "Income"},
                          effectiveValue={"stringValue": "Income"},
                          note="=4777.21+6289.94"),
        (1, 0): cell_data(userEnteredValue={"numberValue": 46023},
                          effectiveValue={"numberValue": 46023},
                          userEnteredFormat={"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}),
    }, merges=[{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 1, "endColumnIndex": 3}],
        rows=2, cols=4)
    return {"properties": {"title": "Stats"}, "sheets": [grid]}   # response envelope

orig_call, orig_meta, orig_get = sheets._call, sheets.metadata, sheets.get_file
sheets._call, sheets.metadata = fake_call, lambda fid: meta()
sheets.get_file = lambda fid: {"modifiedTime": "2026-09-11T08:00:00Z"}
try:
    stats_id = config.DRIVE_SHEETS["stats"]          # alias reverse-lookup source
    p = sheets.snapshot(stats_id, TAB)
    check("snapshot-e2e", "alias reverse-resolved from the pinned registry", p["alias"] == "stats", p["alias"])
    check("snapshot-e2e", "one spreadsheets.get with includeGridData",
          calls and calls[0][0] == ["spreadsheets", "get"] and calls[0][1]["includeGridData"] is True)
    check("snapshot-e2e", "requested range A1:GR100000",
          calls and calls[0][1]["ranges"] == [f"'{TAB}'!A1:GR100000"], repr(calls[0][1]["ranges"]))
    check("snapshot-e2e", "default field mask omits `note` entirely",
          "note" not in calls[0][1]["fields"], calls[0][1]["fields"])
    check("snapshot-e2e", "no note metadata in the payload even though the fixture carried one",
          '"note"' not in json.dumps(p))   # quoted key: 'with_notes' would false-trip a bare substring
    p_notes = sheets.snapshot(stats_id, TAB, with_notes=True)
    check("snapshot-e2e", "with_notes=True requests the note field", "note" in calls[-1][1]["fields"])
    check("snapshot-e2e", "with_notes=True still masks the formula, never raw text",
          (by_a1(p_notes, "B1") or {}).get("note", {}).get("formula_masked") == "=n+n"
          and "=4777.21+6289.94" not in json.dumps(p_notes))
    check("snapshot-e2e", "sheet_id and drive_modified from the probes",
          p["sheet_id"] == 4242 and p["drive_modified"] == "2026-09-11T08:00:00Z")
    check("snapshot-e2e", "merges resolved end-to-end", p["merges"] == ["B1:C1"])
    check("snapshot-e2e", "shadow C1 present via the real fetch path",
          (by_a1(p, "C1") or {}).get("merge_shadow_of") == "B1")
    sheets.get_file = lambda fid: (_ for _ in ()).throw(GwsError("files.get failed"))
    p_nofile = sheets.snapshot(stats_id, TAB)
    check("snapshot-e2e", "Drive probe failure → drive_modified='' (unknown, not unmodified)",
          p_nofile["drive_modified"] == "")
    try:
        sheets.snapshot(stats_id, "No Such Tab")
        check("snapshot-e2e", "unknown tab refused", False)
    except GwsError:
        check("snapshot-e2e", "unknown tab refused", True)
finally:
    sheets._call, sheets.metadata, sheets.get_file = orig_call, orig_meta, orig_get

# ---------------------------------------------------------------------------
print(f"\n-- legality: kinds seen across every payload: {sorted(ALL_KINDS_SEEN)}")
check("totality", "every emitted kind is a legal artifact kind",
      ALL_KINDS_SEEN <= {"literal", "formula", "error", "spill", "blank"}, repr(ALL_KINDS_SEEN))

print(f"\n{'=' * 60}")
print(f"BATTERY COMPLETE — {PASS} passed, {FAIL} failed")
for line in FAILURES:
    print(f"  !! {line}")
sys.exit(1 if FAIL else 0)
