"""Structure inspection: what's inside a source file, without mining values.

The survey layer — tab names, header position, real row counts, date coverage,
and layout anomalies (preamble rows, footer prose blocks, EOF sentinels) — used
to design schemas before any ingestion. Never prints cell values except the
header row.

Design notes (2026-09-06, after two survey legs filed defect reports):
- Date coverage is computed over the FULL data range. An earlier version sampled
  the first 50 rows, which silently under-reported last-dates on longer files.
- The header is *scored*, not assumed. Financial exports routinely carry
  preamble lines ("Plan name", "Date Range") above the real header, so treating
  the first non-blank row as the header produced garbage columns.
- Rows that survive the header but hold no value in any detected date column,
  trailing the last dated row, are reported as `undated_tail_rows` (sentinels,
  footer prose) instead of being counted as data.
"""

from __future__ import annotations

import csv
from datetime import datetime, date
from pathlib import Path

import openpyxl

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y",
                 "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def as_date(value):
    """Return a comparable datetime for date-typed or date-like values, else None."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _row_blank(row) -> bool:
    return row is None or all(_blank(c) for c in row)


def _looks_like_header(row) -> float:
    """Score a candidate header row in [0,1].

    A header row's populated cells are *labels*. Any numeric or date-typed cell
    is a disqualifier, not a demerit: such a row is data wearing a label's
    clothes. (A negative test proved the earlier, gentler rule scored a real
    data row at 0.73 and ingested it silently.) This also leaves genuinely
    header-less tabs — bare-integer year keys in `Stats` — UNRESOLVED instead of
    inventing column names from them, which is the safe answer: those tabs need
    an explicit layout entry, not a guess.
    """
    cells = [c for c in row if not _blank(c)]
    if not cells:
        return 0.0
    nonlabel = sum(1 for c in cells
                   if isinstance(c, (int, float, bool, datetime, date)) or as_date(c))
    if nonlabel:
        return round(0.05 * (1 - nonlabel / len(cells)), 3)
    texts = [str(c).strip() for c in cells]
    distinct = len(set(t.lower() for t in texts))
    fill = len(cells) / max(len(row), 1)
    diversity = distinct / max(len(cells), 1)
    return round(0.45 + fill * 0.3 + diversity * 0.25, 3)


def find_header_index(rows, explicit: int | None = None, look: int = 20,
                      min_confidence: float = 0.45):
    """Return (1-based header row index, confidence). Confidence below
    `min_confidence` means the tool refuses to pretend it knows — the caller
    must pass an explicit header row. Guessing a numeric year as a column name
    is how a bad schema gets authored with false confidence."""
    if explicit:
        # An explicit row is still *validated*: a wrong header row silently turns
        # a data value into a column name (observed: a date became a "column"),
        # which is worse than no answer at all.
        score = _looks_like_header(rows[explicit - 1]) if 0 < explicit <= len(rows) else 0.0
        return explicit, round(score, 3)
    best, best_score = 1, -1.0
    for i, row in enumerate(rows[:look], start=1):
        if _row_blank(row):
            continue
        s = _looks_like_header(row)
        if s > best_score:
            best, best_score = i, s
    return best, round(max(best_score, 0.0), 3)


def _col_stats(header, data_rows, max_cols: int = 40) -> list[dict]:
    """Per-column population and date coverage. `data_rows` must be pre-filtered
    to populated rows: blank padding would dilute nonnull_share and hide the
    date column entirely (this is what made a 14-row sheet look like 999)."""
    n = len(data_rows)
    stats = []
    for i, name in enumerate(header[:max_cols]):
        nn = dr = 0
        lo = hi = None
        for r in data_rows:
            v = r[i] if i < len(r) else None
            if _blank(v):
                continue
            nn += 1
            d = as_date(v)
            if d:
                dr += 1
                lo = d if lo is None or d < lo else lo
                hi = d if hi is None or d > hi else hi
        stats.append({
            "column": name,
            "clean_column": " ".join(str(name).split()).upper(),
            "nonnull_share": round(nn / n, 3) if n else 0.0,
            "date_share": round(dr / nn, 3) if nn else 0.0,
            "date_min": lo.strftime("%Y-%m-%d") if lo else "",
            "date_max": hi.strftime("%Y-%m-%d") if hi else "",
        })
    return stats


def _primary_date_index(stats: list[dict]):
    """Index of the column that is both highly populated and highly date-like."""
    cands = [(i, s) for i, s in enumerate(stats)
             if s["date_share"] >= 0.5 and s["nonnull_share"] >= 0.5]
    if not cands:
        return None
    return max(cands, key=lambda t: (t[1]["date_share"], t[1]["nonnull_share"]))[0]


def _summarize(header, rows_after_header, sheet_name):
    """Split rows into data vs trailing non-dated block (sentinels/footers)."""
    populated = [r for r in rows_after_header if not _row_blank(r)]
    stats_probe = _col_stats(header, populated, max_cols=len(header))
    pidx = _primary_date_index(stats_probe)

    if pidx is None:
        # No reliable date column. A row with a single populated cell is a
        # label/sentinel/footer marker, not a record (this is what caught the
        # 1999 "***END OF FILE***" row, whose file has zero real transactions).
        def _is_record(r):
            return sum(1 for c in r if not _blank(c)) >= 2
        data = [r for r in populated if _is_record(r)]
        undated_tail = len(populated) - len(data)
    else:
        # A cell that is populated but not a date (e.g. "***END OF FILE***" in
        # the date column) is NOT a dated row. Populated != dated.
        def _dated(r):
            v = r[pidx] if pidx < len(r) else None
            return as_date(v) is not None
        dated = [i for i, r in enumerate(populated) if _dated(r)]
        last = max(dated) if dated else -1
        data = [r for i, r in enumerate(populated) if i <= last]
        undated_tail = len(populated) - len(data)

    stats = _col_stats(header, data, max_cols=len(header))
    coverage = [(s["date_min"], s["date_max"]) for s in stats if s["date_max"]]
    pcol = "" if pidx is None else (stats_probe[pidx]["column"] or f"(col {pidx + 1})")
    return {
        "sheet": sheet_name,
        "n_columns": len(header),
        "header": [str(h) for h in header],
        "primary_date_column": pcol or "unclear",
        "data_rows": len(data),
        "undated_tail_rows": undated_tail,
        "date_coverage_min": min((c[0] for c in coverage), default=""),
        "date_coverage_max": max((c[1] for c in coverage), default=""),
        "column_stats": stats,
    }


def inspect_xlsx(path: Path, header_row: int | None = None) -> dict:
    """Tab-by-tab structure of an xlsx/xls file: headers, real rows, date coverage."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    result = {"file": str(path), "sheets": [], "notes": []}
    for sheet in wb.sheetnames:
        # Chartsheet / non-grid tabs have no cells: record, never crash (3 of the
        # 7 spending files carry chart tabs, which took down the first version).
        try:
            rows = [r for r in wb[sheet].iter_rows(values_only=True)]
        except (AttributeError, TypeError, NotImplementedError):
            result["sheets"].append({"sheet": sheet, "non_tabular": True, "data_rows": 0,
                                     "n_columns": 0, "header": [], "primary_date_column": "",
                                     "undated_tail_rows": 0, "date_coverage_min": "",
                                     "date_coverage_max": "", "column_stats": []})
            result["notes"].append(f"{sheet}: non-tabular tab (chart/drawing) — skipped")
            continue
        if not rows:
            result["sheets"].append({"sheet": sheet, "data_rows": 0, "n_columns": 0,
                                     "header": [], "primary_date_column": "",
                                     "undated_tail_rows": 0, "date_coverage_min": "",
                                     "date_coverage_max": "", "column_stats": []})
            continue
        lead_blanks = 0
        for r in rows:
            if _row_blank(r):
                lead_blanks += 1
            else:
                break
        if lead_blanks >= len(rows):
            result["sheets"].append({"sheet": sheet, "data_rows": 0, "n_columns": 0,
                                     "header": [], "primary_date_column": "",
                                     "undated_tail_rows": 0, "date_coverage_min": "",
                                     "date_coverage_max": "", "column_stats": []})
            result["notes"].append(f"{sheet}: no populated rows (blank grid) — no data")
            continue
        # `header_row` is a SHEET row; the scorer sees a blank-stripped slice, so
        # translate once, here, or every explicit header lands one row off.
        hidx, conf = find_header_index(
            rows[lead_blanks:],
            explicit=(header_row - lead_blanks) if header_row else None)
        abs_header = min(lead_blanks + hidx, len(rows))
        header = ["" if _blank(c) else str(c).strip() for c in rows[abs_header - 1]]
        if hidx != 1:
            preamble = [str(rows[i][0]).strip()[:40] for i in range(lead_blanks, abs_header - 1)
                        if not _row_blank(rows[i]) and rows[i][0] is not None]
            result["notes"].append(
                f"{sheet}: header at row {abs_header} (not row 1); preamble lines: {preamble[:4]}")
        sheet_summary = _summarize(header, rows[abs_header:], sheet)
        sheet_summary["header_row"] = abs_header
        sheet_summary["header_confidence"] = conf
        if conf < 0.45:
            sheet_summary["header_unresolved"] = True
            result["notes"].append(
                f"{sheet}: ⚠ HEADER UNRESOLVED (confidence {conf}) — column names are likely "
                f"year/number keys, not labels. Pass an explicit --header-row; do NOT "
                f"design a schema from this tab's auto-header.")
        result["sheets"].append(sheet_summary)
    wb.close()
    return result


def inspect_csv(path: Path, header_row: int | None = None) -> dict:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = [tuple(r) for r in csv.reader(fh)]
    if not rows:
        return {"file": str(path), "sheets": [], "notes": ["empty file"]}
    hidx, conf = find_header_index(rows, explicit=header_row)
    header = [str(c).strip() for c in rows[hidx - 1]]
    notes = [f"csv: header at row {hidx}"] if hidx != 1 else []
    if conf < 0.45:
        notes.append("csv: ⚠ HEADER UNRESOLVED (confidence "
                     f"{conf}) — pass an explicit --header-row")
    summary = _summarize(header, rows[hidx:], "csv")
    summary["header_row"] = hidx
    summary["header_confidence"] = conf
    return {"file": str(path), "sheets": [summary], "notes": notes}


def inspect_any(path: Path, header_row: int | None = None) -> dict:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return inspect_xlsx(path, header_row=header_row)
    if suffix == ".csv":
        return inspect_csv(path, header_row=header_row)
    raise ValueError(f"unsupported for inspection: {path.suffix}")


def render_markdown(report: dict) -> str:
    lines = [f"# Structure — {report['file']}", ""]
    for note in report.get("notes", []):
        lines.append(f"> **layout note** {note}")
    if report.get("notes"):
        lines.append("")
    for s in report["sheets"]:
        lines.append(f"## {s['sheet']} — {s['data_rows']} data rows, "
                     f"{s['n_columns']} columns")
        lines.append(f"- primary date column: `{s.get('primary_date_column', '')}`  "
                     f"coverage: {s.get('date_coverage_min') or '—'} → {s.get('date_coverage_max') or '—'}")
        if s.get("undated_tail_rows"):
            lines.append(f"- ⚠ {s['undated_tail_rows']} undated trailing row(s) — "
                         "sentinel/footer block, excluded from data_rows")
        if s["header"]:
            lines.append("")
            lines.append("| column | filled | dates? | min | max |")
            lines.append("|---|---|---|---|---|")
            for cs in s["column_stats"]:
                dates = f"{int(cs['date_share'] * 100)}%" if cs["date_share"] else "—"
                filled = f"{int(cs['nonnull_share'] * 100)}%"
                flag = "" if cs["column"] == cs["clean_column"] else " ⚠ws"
                lines.append(f"| {cs['column']}{flag} | {filled} | {dates} "
                             f"| {cs['date_min'] or '—'} | {cs['date_max'] or '—'} |")
        lines.append("")
    return "\n".join(lines)
