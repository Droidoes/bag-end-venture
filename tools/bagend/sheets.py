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
import subprocess
from pathlib import Path

from . import config
from .gws_client import GwsError, TOKEN_CACHE_HINT

SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_EPOCH = dt.date(1899, 12, 30)  # Excel/Sheets 1900 system serial origin


def _call(path: list[str], params: dict) -> dict:
    """Invoke `gws sheets <path...> --params <json>`.

    The CLI nests sub-resources, so a values read is
    `sheets spreadsheets values get` — three tokens, not two. Flattening that
    into "spreadsheets.values" produces `unrecognized subcommand`.
    """
    proc = subprocess.run(
        ["gws", "sheets", *path, "--params", json.dumps(params)],
        capture_output=True, text=True)
    text = proc.stdout
    start = text.find("{")
    if proc.returncode != 0 or start < 0:
        hint = TOKEN_CACHE_HINT if "token directory" in (proc.stdout + proc.stderr) else ""
        raise GwsError(f"gws sheets {' '.join(path)} failed:\n"
                       f"{proc.stdout[:300]}\n{proc.stderr[:300]}\n{hint}")
    return json.loads(text[start:])


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
