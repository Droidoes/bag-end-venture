"""Direct Google Sheets reads — the preferred path for native Sheets.

Why this exists: exporting a native Google Sheet to xlsx (the first design)
introduced three avoidable defect classes, all of which cost this project real
diagnosis time on 2026-09-06:
  * ~1,000 blank padding rows per tab (openpyxl reports them as data),
  * chartsheet/pivot-cache tabs that crash or poison openpyxl,
  * year-less *text* dates that Excel re-infers to the wrong year on export —
    which made correct data look corrupt.

Reading values straight from the Sheets API returns typed cells (real date
serials, not display strings), no padding, and no chart tabs at all. Local
files are therefore CSVs named `<alias>__<tab>.csv`, which also makes
provenance unambiguous: a native Sheet never masquerades as an uploaded .xlsx.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from . import config
from .gws_client import GwsError, TOKEN_CACHE_HINT, get_file

SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_EPOCH = dt.date(1899, 12, 30)  # Excel/Sheets 1900 system serial origin


def _call(path: list[str], params: dict, attempts: int = 3) -> dict:
    """Invoke `gws sheets <path...> --params <json>`, retrying a 429 quota stop.

    The CLI nests sub-resources, so a values read is
    `sheets spreadsheets values get` — three tokens, not two. Flattening that
    into "spreadsheets.values" produces `unrecognized subcommand`.

    A workbook-wide scan can exceed the per-user read quota (60/min), which the
    API reports as 429 "Quota exceeded"; that is a transient stop, not a broken
    request, so it backs off and retries rather than aborting the scan.
    """
    last = ""
    for attempt in range(attempts):
        proc = subprocess.run(
            ["gws", "sheets", *path, "--params", json.dumps(params)],
            capture_output=True, text=True)
        text = proc.stdout
        start = text.find("{")
        if proc.returncode == 0 and start >= 0:
            return json.loads(text[start:])
        blob = proc.stdout + proc.stderr
        if "429" in blob or "Quota exceeded" in blob or "rateLimitExceeded" in blob:
            last = blob
            if attempt < attempts - 1:
                time.sleep(20 * (attempt + 1))
                continue
        hint = TOKEN_CACHE_HINT if "token directory" in blob else ""
        raise GwsError(f"gws sheets {' '.join(path)} failed:\n"
                       f"{proc.stdout[:300]}\n{proc.stderr[:300]}\n{hint}")
    raise GwsError(f"gws sheets {' '.join(path)} exhausted {attempts} attempts on "
                   f"quota:\n{last[:300]}")


def metadata(file_id: str) -> dict:
    """Tab inventory: title, sheetId, grid size, and hidden flag."""
    data = _call(["spreadsheets", "get"], {
        "spreadsheetId": file_id,
        "fields": "properties.title,sheets.properties",
    })
    tabs = []
    for s in data.get("sheets", []):
        p = s.get("properties", {})
        if p.get("sheetType", "GRID") != "GRID":
            continue  # chartsheet / BIEngine / folder — never data
        grid = p.get("gridProperties", {})
        tabs.append({
            "title": p.get("title", ""),
            "sheet_id": p.get("sheetId"),
            "rows": grid.get("rowCount", 0),
            "columns": grid.get("columnCount", 0),
            "hidden": bool(p.get("hidden", False)),
        })
    return {"title": data.get("properties", {}).get("title", ""), "tabs": tabs,
            "file_id": file_id}


def _typed(v):
    """Sheets UNFORMATTED_VALUE gives date/timestamp cells as serial numbers.
    Convert them to ISO so a year can never be re-inferred downstream."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 1 < v < 2958466 and float(v).is_integer() and 20000 <= v <= 80000:
            return (_EPOCH + dt.timedelta(days=int(v))).isoformat()
    return v


def read_tab(file_id: str, title: str, max_rows: int = 100000,
             max_cols: int = 200, formatted: bool = False) -> list[list]:
    """Read a whole tab as typed rows. Range-based read returns only the used
    range — no blank padding."""
    col_letter = ""
    n = max_cols
    while n:
        col_letter = chr(65 + (n - 1) % 26) + col_letter
        n = (n - 1) // 26
    params = {
        "spreadsheetId": file_id,
        "range": f"{title}!A1:{col_letter}{max_rows}",
        "valueRenderOption": "FORMATTED_VALUE" if formatted else "UNFORMATTED_VALUE",
        "dateTimeRenderOption": "SERIAL_NUMBER",
    }
    data = _call(["spreadsheets", "values", "get"], params)
    rows = data.get("values", [])
    if formatted:
        return [[("" if c is None else c) for c in r] for r in rows]
    return [[_typed(c) for c in r] for r in rows]


def _col_letter(n: int) -> str:
    """1-based column number -> A1 letter (27 -> AA)."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _a1(row0: int, col0: int) -> str:
    """0-based row/col index -> A1 address (0,0 -> A1)."""
    return f"{_col_letter(col0 + 1)}{row0 + 1}"


# A cell/range reference (J4, $A$4, AA12) or a quoted string, at a word boundary
# so function names like LOG10 are not mistaken for references.
_REF_OR_STRING = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"|(?<![A-Za-z])\$?[A-Z]{1,3}\$?\d+(?![A-Za-z0-9])")


def _ordinal_letters(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. Used for placeholders that contain no digits."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _letters_ordinal(s: str) -> int:
    """Inverse of _ordinal_letters."""
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


_PLACEHOLDER = re.compile(r"\x00([A-Z]+)\x00")


def _redact_formula(formula: str) -> str:
    """Mask numeric literals inside a formula, keeping references and strings.

    A constant-typed entry (`=4777.21+6289.94`) is a financial value wearing a
    formula, so structure-only reads must not carry it. References and quoted
    strings are protected first (with digit-free placeholders, so the masking pass
    cannot eat them), leaving `=SUM(F11:I11)` unchanged, `=A4+1` as `=A4+n` and
    `=4777.21+6289.94` as `=n+n`.
    """
    kept: list[str] = []

    def _protect(m: "re.Match[str]") -> str:
        kept.append(m.group(0))
        return f"\x00{_ordinal_letters(len(kept) - 1)}\x00"

    masked = _REF_OR_STRING.sub(_protect, formula)
    masked = re.sub(r"\d+(?:\.\d+)?", "n", masked)
    return _PLACEHOLDER.sub(lambda m: kept[_letters_ordinal(m.group(1))], masked)


def grid_structure(file_id: str, title: str, max_rows: int = 60,
                   max_cols: int = 30, with_values: bool = False) -> dict:
    """Native STRUCTURAL read: merges + entered-vs-effective cells (formulas).

    Why this exists: `values.get` (used by read_tab/dump_tab) returns values
    only, so a merged group band looks like a label in the anchor cell and a
    derived column looks like a plain number. Two 2026-09-10 survey legs then
    had to *infer* subtotal semantics and could not see that the column was a
    formula at all — the cause of an unresolved-header backlog. This keeps the
    read native (no xlsx export, source never modified) and adds the structure.

    Without `with_values` the payload is structure-only: formulas, effective
    cell *types*, number formats and merge ranges — no financial values.
    """
    col = _col_letter(max_cols)
    rng = f"'{title}'!A1:{col}{max_rows}"
    data = _call(["spreadsheets", "get"], {
        "spreadsheetId": file_id,
        "ranges": [rng],
        "includeGridData": True,
        # NOTE: numberFormat is NOT a CellData field — it lives under
        # userEnteredFormat/effectiveFormat. Naming it directly makes the API
        # reject the whole request with a bare "invalid argument" (400).
        "fields": ("properties.title,sheets(properties.title,merges,"
                   "data(startRow,startColumn,"
                   "rowData(values(userEnteredValue,effectiveValue,"
                   "userEnteredFormat(numberFormat)))))"),
    })
    sheet = next((s for s in data.get("sheets", [])
                  if s.get("properties", {}).get("title") == title), None)
    if sheet is None:
        raise GwsError(f"grid_structure: no grid tab titled {title!r} in {file_id}")

    merges = [f"{_a1(m.get('startRowIndex', 0), m.get('startColumnIndex', 0))}:"
              f"{_a1(m.get('endRowIndex', 1) - 1, m.get('endColumnIndex', 1) - 1)}"
              for m in sheet.get("merges", [])]

    cells = []
    for grid in sheet.get("data", []):
        r0 = grid.get("startRow", 0)
        c0 = grid.get("startColumn", 0)
        for i, row in enumerate(grid.get("rowData", [])):
            for j, cell in enumerate(row.get("values", [])):
                entered = cell.get("userEnteredValue") or {}
                effective = cell.get("effectiveValue") or {}
                if not entered and not effective:
                    continue          # empty cell — never emit padding
                rec = {"a1": _a1(r0 + i, c0 + j)}
                if "formulaValue" in entered:
                    rec["kind"] = "formula"
                    raw = entered["formulaValue"]
                    rec["formula"] = raw if with_values else _redact_formula(raw)
                else:
                    rec["kind"] = "literal"
                if effective:
                    rec["effective_type"] = next(iter(effective))
                nf = (((cell.get("userEnteredFormat") or {}).get("numberFormat")) or {}).get("type")
                if nf:
                    rec["format"] = nf
                if with_values:
                    rec["effective"] = effective
                    if rec["kind"] == "literal":
                        rec["entered"] = entered
                cells.append(rec)

    return {
        "spreadsheet": data.get("properties", {}).get("title", ""),
        "tab": title,
        "range": rng,
        "merges": merges,
        "nonempty_cells": len(cells),
        "formula_cells": [c["a1"] for c in cells if c["kind"] == "formula"],
        "values_included": bool(with_values),
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# v0.3 §3 structural snapshot (P1) — the artifact the loader will ingest.
# Contract: docs/superpowers/plans/2026-09-12-structural-prefetch-v0.3.md §3/§4.
# Values are included (the artifact IS the ingest input); artifacts live in
# private/ only. Read-only on the Sheets API.
# ---------------------------------------------------------------------------

# Number-format types under which a serial number is really a date/time. This
# is the gate for _typed_value below: without it, _typed would convert any
# integer in [20000, 80000] — e.g. a measured 45123 dollar amount — into a
# phantom ISO date.
_DATELIKE_NUMFMT = frozenset({"DATE", "TIME", "DATE_TIME"})


def _typed_value(raw, numfmt_type):
    """Apply the existing `_typed` serial→date conversion deliberately — only
    when the cell's number format says DATE/TIME/DATE_TIME.

    The serial→date hazard (v0.3 §8 P1 gate: "`_typed` serial→date not
    reproduced"): `_typed` converts ANY integer serial in [20000, 80000] to an
    ISO date, because values-only reads cannot know the format. Applied
    blindly to this artifact a measured 45123 becomes a fake 2023-07-01, so
    the conversion fires only behind the format gate; every other number keeps
    its raw serial and typed-value parity can be proved downstream against
    numfmt_pattern. Known residual limit (flagged, not silently "fixed"):
    `_typed` only converts integer serials, so a DATE_TIME cell with a
    fractional part (e.g. 45000.5) stays a raw serial — the loader must not
    re-infer a date from it either.
    """
    if numfmt_type in _DATELIKE_NUMFMT:
        return _typed(raw)
    return raw


_ERROR_TOKEN = re.compile(r"#[A-Z0-9][A-Z0-9!/]*[!?]?")


def _error_token(err: dict) -> str:
    """Display token (#NAME?, #DIV/0!) from an API ErrorValue object.

    The API carries an enum in `type` (ERROR_TYPE_NAME, …) and the human token
    inside `message`; the artifact wants the token the sheet displays. Falls
    back to the raw enum when the message carries no #TOKEN.
    """
    m = _ERROR_TOKEN.search(err.get("message") or "")
    return m.group(0) if m else (err.get("type") or "ERROR")


def _numfmt(cell: dict) -> tuple:
    """(type, pattern) for a cell: userEnteredFormat.numberFormat first, then
    effectiveFormat.numberFormat (row/column-inherited formats — a whole date
    column, say — live only in effectiveFormat); either element may be None.
    Callers emit the pair whenever either side is known, so numfmt_pattern is
    never silently missing on a formatted cell (v0.3 §3 hard rule)."""
    u = ((cell.get("userEnteredFormat") or {}).get("numberFormat")) or {}
    e = ((cell.get("effectiveFormat") or {}).get("numberFormat")) or {}
    if not u and not e:
        return None, None
    return (u.get("type") or e.get("type"), u.get("pattern") or e.get("pattern"))


def _effective_scalar(eff: dict):
    """Typed scalar out of an ExtendedValue: number/string/bool; errorValue or
    absence -> None (kind/error_type carry that separately). An empty-string
    result arrives as stringValue "" and is preserved — that is the §4
    "formula → empty string" state, distinct from value null."""
    for key in ("numberValue", "stringValue", "boolValue"):
        if key in eff:
            return eff[key]
    return None


def _classify(cell: dict) -> str:
    """Total classifier for one CellData -> artifact kind (v0.3 §4 step 3).

    Ordered and total: formula → error | formula; entered error (defensive)
    → error; an effective value with NOTHING entered is a spill candidate
    (spill_of resolved by the caller's neighbour scan); anything else entered
    → literal. Format-only / empty cells never reach here.
    """
    entered = cell.get("userEnteredValue") or {}
    eff = cell.get("effectiveValue") or {}
    if "formulaValue" in entered:
        return "error" if ("errorValue" in eff or "errorValue" in entered) else "formula"
    if "errorValue" in entered or "errorValue" in eff:
        return "error"          # defensive: an error with no formula entered
    if not entered and eff:
        return "spill"          # nothing entered, yet it carries a value
    return "literal"


def _assemble(meta: dict, sheet: dict, *, alias: str, file_id: str,
              with_notes: bool, max_rows: int, max_cols: int,
              drive_modified: str, fetched_at: str) -> dict:
    """Pure v0.3 §3 artifact builder — no I/O, no network.

    snapshot() fetches (metadata + one grid read + a Drive modifiedTime probe)
    and delegates here. `.scratch/p1/snapshot_tests.py` drives this directly
    with synthetic payloads so the P1 gate runs with no Drive access.

    Merge semantics (v0.3 §4 steps 1–2): merges are resolved first; a shadow
    cell inherits its anchor's full record (kind, formula, error, numfmt AND
    value — the merged display) plus `merge_shadow_of`, so a shadow is never
    emitted as a blank and the loader never has to infer the inheritance. A
    merge whose anchor carries no content contributes only rectangle columns.
    """
    title = sheet.get("properties", {}).get("title", "")
    tab_meta = next((t for t in meta.get("tabs", []) if t.get("title") == title), None)
    # sheet_id comes from metadata() — never invented here.
    sheet_id = tab_meta.get("sheet_id") if tab_meta else None
    tab_extent = ({"rows": tab_meta.get("rows", 0), "cols": tab_meta.get("columns", 0)}
                  if tab_meta else {"rows": 0, "cols": 0})

    # (1) resolve merges: A1 strings for the payload, a shadow->anchor index,
    # and every column a merge touches (a merged header "carries a header" for
    # each column it spans even though only the anchor holds content).
    merges: list[str] = []
    shadow_of: dict[tuple[int, int], tuple[int, int]] = {}
    merge_cols: set[int] = set()
    for m in sheet.get("merges", []):
        r0, c0 = m.get("startRowIndex", 0), m.get("startColumnIndex", 0)
        r1 = m.get("endRowIndex", 1) - 1
        c1 = m.get("endColumnIndex", 1) - 1
        merges.append(f"{_a1(r0, c0)}:{_a1(r1, c1)}")
        merge_cols.update(range(c0, c1 + 1))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if (r, c) != (r0, c0):
                    shadow_of[(r, c)] = (r0, c0)

    # Cell index over the returned grid (all GridData blocks; the API chunks
    # large ranges). Empty CellData {} never enters the index.
    idx: dict[tuple[int, int], dict] = {}
    for grid in sheet.get("data", []):
        r0, c0 = grid.get("startRow", 0), grid.get("startColumn", 0)
        for i, row in enumerate(grid.get("rowData", [])):
            for j, cell in enumerate(row.get("values") or []):
                if cell:
                    idx[(r0 + i, c0 + j)] = cell

    def _content(cell: dict) -> bool:
        # Content = something entered or an effective value. Format-only
        # CellData (inherited column formats on empty cells) and note-only
        # cells are NOT content: counting inherited formats would let styling
        # fake a full-grid read, and notes never extend bounds or rectangle.
        return bool(cell.get("userEnteredValue")) or bool(cell.get("effectiveValue"))

    content = {pos for pos, cell in idx.items() if _content(cell)}

    def _note_fields(cell: dict, rec: dict) -> None:
        # with_notes=False must emit NOTHING note-related — the field mask in
        # snapshot() never even requests `note`; this gate is belt-and-braces.
        # with_notes=True still never carries raw text: has_note /
        # note_is_formula and, for formula notes, a _redact_formula mask.
        if not with_notes:
            return
        note = cell.get("note")
        if not note:
            return
        entry = {"has_note": True, "note_is_formula": note.startswith("=")}
        if entry["note_is_formula"]:
            entry["formula_masked"] = _redact_formula(note)
        rec["note"] = entry

    records: dict[tuple[int, int], dict] = {}

    # (3) classify every content cell.
    for (r, c) in content:
        cell = idx[(r, c)]
        kind = _classify(cell)
        entered = cell.get("userEnteredValue") or {}
        rec = {"a1": _a1(r, c), "kind": kind}
        if "formulaValue" in entered:
            # Values are included in the artifact (it IS the ingest input), so
            # the real formula is carried unredacted; redaction is for
            # structure-only reads (grid_structure) and note text.
            rec["formula"] = entered["formulaValue"]
        if kind in ("formula", "error"):
            err = ((cell.get("effectiveValue") or {}).get("errorValue")
                   or entered.get("errorValue"))
            rec["error_type"] = _error_token(err) if err else None
        elif kind == "spill":
            # Array results grow right/down from the anchor, so the anchor is
            # somewhere left or above: walk outward through contiguous spill
            # cells (effective value, nothing entered) until a formula anchor
            # turns up — the immediate neighbour is only the anchor for the
            # FIRST cell of a column/row spill. Left-first is the deterministic
            # tie-break. No formula anchor reachable -> the extent is
            # indeterminate: spill_of stays null and the loader quarantines
            # the cell (v0.3 §3: indeterminate spill refuses).
            anchor = None
            for dr, dc in ((0, -1), (-1, 0)):        # left, then up
                r2, c2 = r, c
                while True:
                    r2, c2 = r2 + dr, c2 + dc
                    ncell = idx.get((r2, c2))
                    if ncell is None:
                        break
                    nentered = ncell.get("userEnteredValue") or {}
                    if "formulaValue" in nentered:
                        anchor = (r2, c2)
                        break
                    if not nentered and ncell.get("effectiveValue"):
                        continue                     # another spill cell — keep chasing
                    break                            # a literal/format-only cell ends the run
                if anchor:
                    break
            rec["spill_of"] = _a1(*anchor) if anchor else None
        nf_type, nf_pattern = _numfmt(cell)
        if nf_type is not None or nf_pattern is not None:
            rec["numfmt_type"], rec["numfmt_pattern"] = nf_type, nf_pattern
        rec["value"] = _typed_value(_effective_scalar(cell.get("effectiveValue") or {}), nf_type)
        _note_fields(cell, rec)
        records[(r, c)] = rec

    # Merge shadows (after content, so a content cell always wins its own
    # position): inherit the anchor's record wholesale + merge_shadow_of. The
    # anchor's note metadata (if any) is inherited with everything else — the
    # merged display shows it; notes never enter fact rows either way.
    for (r, c), (ar, ac) in shadow_of.items():
        if (r, c) in records or (ar, ac) not in records:
            continue   # content wins its position; empty anchors inherit nothing
        rec = dict(records[(ar, ac)])
        rec["a1"] = _a1(r, c)
        rec["merge_shadow_of"] = _a1(ar, ac)
        records[(r, c)] = rec

    # returned_bounds: the actual max row/col that CARRIED a cell — entered or
    # effective value, or a merge shadow. Explicit blanks are emitted from the
    # rectangle below (they are not returned by the API), and format-only
    # CellData is not "carrying a cell", so neither can inflate the bounds.
    carried = [pos for pos, rec in records.items() if rec["kind"] != "blank"]
    returned_bounds = ({"rows": max(r for r, _ in carried) + 1,
                        "cols": max(c for _, c in carried) + 1}
                       if carried else {"rows": 0, "cols": 0})

    # (2) the ingest rectangle. P1 has no allow-list access, so the writer
    # derives a deliberate SUPERSET: rows from (topmost content row + 1) to
    # the last content row, columns = content columns ∪ merge-covered columns.
    # Wide is the safe direction: extra blanks above/beside the loader's
    # declared rectangle are inert, but a MISSING blank is exactly the
    # absence-inference this feature exists to kill. The loader's declared
    # rectangle must be checked to sit inside this one (flagged, not faked).
    rect = None
    if content:
        first_row = min(r for r, _ in content) + 1
        last_row = max(r for r, _ in content)
        rect_cols = sorted({c for _, c in content} | merge_cols)
        rect = {
            "first_row": first_row + 1,      # 1-based
            "last_row": last_row + 1,
            "columns": [_col_letter(c + 1) for c in rect_cols],
            "derived": True,
            "derivation": ("writer-derived superset (P1 has no allow-list): first "
                           "content row + 1 .. last content row, across content "
                           "columns and merge-covered columns; the loader's "
                           "declared rectangle supersedes and must fit inside"),
        }
        # Explicit blanks — a blank inside the rectangle is a CELL, never an
        # absence. Outside it, a blank stays absent (§3 hard rule).
        for r in range(first_row, last_row + 1):
            for c in rect_cols:
                if (r, c) in records:
                    continue
                rec = {"a1": _a1(r, c), "kind": "blank"}
                cell = idx.get((r, c))
                if cell:
                    nf_type, nf_pattern = _numfmt(cell)
                    if nf_type is not None or nf_pattern is not None:
                        rec["numfmt_type"], rec["numfmt_pattern"] = nf_type, nf_pattern
                    _note_fields(cell, rec)   # a note-only cell is a blank + note metadata
                rec["value"] = None
                records[(r, c)] = rec

    cells = [records[pos] for pos in sorted(records)]

    # truncated (v0.3 §3 hard rule — a truncated artifact is refused, never
    # partially loaded): True when the returned data would exceed the requested
    # window (defensive; the API clamps) OR the requested window is smaller
    # than the tab's full extent from metadata().
    truncated = bool(
        returned_bounds["rows"] > max_rows or returned_bounds["cols"] > max_cols
        or max_rows < tab_extent["rows"] or max_cols < tab_extent["cols"])

    # Deterministic hash over the canonical JSON of merges+cells only —
    # fetched_at / drive_modified must not churn it, or every refetch of an
    # unchanged tab would look like a new artifact.
    canonical = json.dumps({"merges": merges, "cells": cells}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    return {
        "artifact_version": 1,
        "alias": alias,
        "tab": title,
        "spreadsheet": meta.get("title", ""),
        "drive_id": file_id,
        "sheet_id": sheet_id,
        "requested_range": f"'{title}'!A1:{_col_letter(max_cols)}{max_rows}",
        "returned_bounds": returned_bounds,
        "tab_extent": tab_extent,
        "truncated": truncated,
        # drive_modified may be "" when the Drive files.get probe fails or is
        # unavailable (scope/quota). §6 treats file modifiedTime as a coarse
        # re-fetch hint only, so "" must read as UNKNOWN — never as unmodified.
        "drive_modified": drive_modified,
        "fetched_at": fetched_at,
        "artifact_sha256": hashlib.sha256(canonical).hexdigest(),
        "merges": merges,
        "ingest_rectangle": rect,
        # Additive vs §3: records whether note metadata was requested, so a
        # note-less artifact is distinguishable from a no-notes-sheet artifact.
        "with_notes": bool(with_notes),
        "cells": cells,
    }


def snapshot(file_id: str, title: str, *, with_notes: bool = False,
             max_rows: int = 100000, max_cols: int = 200) -> dict:
    """v0.3 §3 structural snapshot of one grid tab — the loader's ingest input.

    One metadata() read (sheet_id, tab_extent — never invented) + one grid read
    (merges, entered/effective values, number formats, values included) + one
    Drive files.get probe for modifiedTime. Read-only on the API; the artifact
    lands in private/raw/sheets/ via `bagend.py sheets snapshot`.

    with_notes=False (default) emits NOTHING note-related — the grid request
    omits the `note` field entirely, so raw note text never crosses the wire.
    with_notes=True still never carries raw text: has_note / note_is_formula
    and a _redact_formula-masked formula only.

    grid_structure is deliberately NOT reused: its structure-only payload
    redacts formulas and lacks effectiveValue detail, effectiveFormat and
    sheet_id, all of which the artifact requires. Shared helpers (_a1,
    _col_letter, _typed, _redact_formula), metadata() and _call are reused.
    """
    meta = metadata(file_id)
    if not any(t["title"] == title for t in meta["tabs"]):
        raise GwsError(f"snapshot: no grid tab titled {title!r} in {file_id}; have: "
                       + ", ".join(t["title"] for t in meta["tabs"]))
    data = _call(["spreadsheets", "get"], {
        "spreadsheetId": file_id,
        "ranges": [f"'{title}'!A1:{_col_letter(max_cols)}{max_rows}"],
        "includeGridData": True,
        # NOTE (carried from grid_structure): numberFormat is NOT a CellData
        # field — it lives under userEnteredFormat/effectiveFormat. Naming it
        # directly makes the API reject the whole request with a bare 400.
        "fields": ("properties.title,sheets(properties.title,merges,"
                   "data(startRow,startColumn,"
                   "rowData(values(userEnteredValue,effectiveValue,"
                   "userEnteredFormat(numberFormat),effectiveFormat(numberFormat)"
                   + (",note" if with_notes else "") + "))))"),
    })
    sheet = next((s for s in data.get("sheets", [])
                  if s.get("properties", {}).get("title") == title), None)
    if sheet is None:
        raise GwsError(f"snapshot: response carried no grid data for tab {title!r}")
    # Alias: reverse-lookup the pinned registry (a filename is never identity);
    # fall back to the same title slug `sheets dump` derives for unknown IDs.
    alias = next((a for a, fid in config.DRIVE_SHEETS.items() if fid == file_id),
                 re.sub(r"[^A-Za-z0-9]+", "_", meta.get("title", "")).strip("_"))
    try:
        drive_modified = get_file(file_id).get("modifiedTime", "")
    except GwsError:
        drive_modified = ""   # unavailable — see the envelope comment in _assemble
    return _assemble(meta, sheet, alias=alias, file_id=file_id,
                     with_notes=with_notes, max_rows=max_rows, max_cols=max_cols,
                     drive_modified=drive_modified,
                     fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


def scan_errors(file_id: str, max_rows: int = 120, max_cols: int = 30) -> dict:
    """Every grid tab holding error cells, with the formulas that produce them.

    The xlsx -> Google-Sheets migration leaves Microsoft-Finance formulas
    (`_FV`, `_xlfn…`) behind, and those evaluate to `#NAME?`/`#VALUE!`. A
    values-only read shows an error string per cell; this reports which tab,
    which columns, which rows and which formulas, so the owner can repair a
    workbook in one pass. Structure-only: literals are redacted (see
    `_redact_formula`), so no financial values leave the sheet.
    """
    meta = metadata(file_id)
    flagged = []
    failed = []
    for t in meta["tabs"]:
        try:
            grid = grid_structure(file_id, t["title"], max_rows=max_rows, max_cols=max_cols)
        except GwsError as exc:
            failed.append({"tab": t["title"], "error": str(exc).splitlines()[0][:160]})
            continue
        errs = [c for c in grid["cells"] if c.get("effective_type") == "errorValue"]
        if not errs:
            continue
        by_col: dict[str, int] = {}
        rows = []
        formulas: list[str] = []
        for c in errs:
            col = re.match(r"[A-Z]+", c["a1"]).group(0)
            by_col[col] = by_col.get(col, 0) + 1
            rows.append(int(re.sub(r"\D", "", c["a1"])))
            f = c.get("formula", "(literal)")
            if f not in formulas:
                formulas.append(f)
        flagged.append({
            "tab": t["title"],
            "sheet_id": t["sheet_id"],
            "error_cells": len(errs),
            "columns": dict(sorted(by_col.items())),
            "row_range": [min(rows), max(rows)],
            "formulas": formulas[:3],
        })
    return {"spreadsheet": meta["title"], "file_id": file_id,
            "tabs_scanned": len(meta["tabs"]), "tabs_with_errors": flagged,
            "tabs_failed": failed}


def dump_tab(file_id: str, title: str, out_path: Path) -> Path:
    """Write one tab to CSV (typed values; blank padding absent by construction)."""
    rows = read_tab(file_id, title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width = max((len(r) for r in rows), default=0)
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        for r in rows:
            w.writerow(list(r) + [""] * (width - len(r)))
    return out_path
