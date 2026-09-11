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
import json
import re
import subprocess
import time
from pathlib import Path

from . import config
from .gws_client import GwsError, TOKEN_CACHE_HINT

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
