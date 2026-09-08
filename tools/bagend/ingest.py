"""Ingestion: source files -> private/books.db with enforced provenance.

Conventions (do not bypass — the schema enforces what AGENTS.md promises):
- Every ingested row carries source_path, drive_id, and ingested_at.
- The raw file is fetched to private/raw/ first; ingestion reads from disk,
  so a row can always be traced back to the exact bytes it came from.
- Ingestion is append-only: re-ingesting the same source adds rows stamped
  with a new ingested_at; nothing is silently updated or deleted.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    # Foreign keys are PER-CONNECTION in SQLite: a PRAGMA inside the DDL only
    # applies to whichever connection executes the schema. Without this line every
    # tool connection runs with lineage checks OFF — which would make R1 ("every row
    # carries provenance") a comment rather than a constraint. Verified 2026-09-06:
    # a plain connection reported PRAGMA foreign_keys = 0.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _ingest_log (
            ingested_at TEXT NOT NULL,
            table_name  TEXT NOT NULL,
            source_path TEXT NOT NULL,
            drive_id    TEXT,
            n_rows      INTEGER NOT NULL,
            sheet       TEXT,
            note        TEXT
        )
    """)
    return conn


def ingest_dataframe(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    table: str,
    source_path: str,
    drive_id: str = "",
    sheet: str = "",
    note: str = "",
) -> int:
    """Write one dataframe into `table` with provenance columns attached."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = df.copy()
    out["_source_path"] = source_path
    out["_drive_id"] = drive_id
    out["_ingested_at"] = stamp
    if sheet:
        out["_sheet"] = sheet
    n = len(out)
    out.to_sql(table, conn, if_exists="append", index=False)
    conn.execute(
        "INSERT INTO _ingest_log (ingested_at, table_name, source_path, drive_id,"
        " n_rows, sheet, note) VALUES (?,?,?,?,?,?,?)",
        (stamp, table, source_path, drive_id, n, sheet or None, note or None),
    )
    conn.commit()
    return n


def _source_label(path: Path) -> str:
    """Repo-relative label for provenance; falls back to the absolute path."""
    path = path.resolve()
    try:
        return str(path.relative_to(config.REPO_ROOT))
    except ValueError:
        return str(path)


PROVENANCE_TSV = config.RAW_DIR / "_provenance.tsv"


def assert_not_exported_native(xlsx_path: Path) -> None:
    """Refuse to ingest a local file that provenance says was an xlsx *export* of a
    native Google Sheet. Those exports carry padding rows and year-re-inferred
    dates, so ingesting one would put fabricated structure into the store."""
    if not PROVENANCE_TSV.exists():
        return
    import csv as _csv
    rel = _source_label(xlsx_path)
    with open(PROVENANCE_TSV, newline="") as fh:
        for row in _csv.DictReader(fh, delimiter="\t"):
            if row.get("local_path") == rel and row.get("obtained_via") == "files.export" \
               and row.get("source_kind") == "native-google-sheet":
                raise ValueError(
                    f"{rel} is an xlsx EXPORT of a native Google Sheet "
                    f"({row.get('drive_name')!r}). Refusing to ingest: exports inject "
                    f"padding rows and re-infer years. Re-read it natively:\n"
                    f"  python3 tools/bagend.py sheets dump <alias>\n"
                    f"then ingest the CSV with `ingest csv`.")


def ingest_xlsx_sheet(
    conn: sqlite3.Connection,
    xlsx_path: Path,
    sheet: str,
    table: str,
    drive_id: str = "",
    header_row: int | None = None,
    note: str = "",
) -> int:
    """Ingest one tab, layout-aware.

    Every survey leg returned the same unanimous finding: header position varies
    (r1/r4/r5/r6/r14+wrapped), sentinel and footer blocks trail the data, and
    blank export padding inflates row counts. So this resolves the header
    explicitly, refuses to ingest a guessed header, de-duplicates repeated labels
    (e.g. 'Bond & Cash Balance' appears 4x in one tab), and drops the
    post-data tail instead of persisting it as a record.
    """
    import openpyxl
    from .inspect import as_date, find_header_index, _row_blank

    assert_not_exported_native(xlsx_path)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = [r for r in ws.iter_rows(values_only=True)]
    wb.close()
    if not rows:
        return 0
    lead_blanks = 0
    for r in rows:
        if _row_blank(r):
            lead_blanks += 1
        else:
            break
    if lead_blanks >= len(rows):
        return 0

    hidx, conf = find_header_index(
        rows[lead_blanks:],
        explicit=(header_row - lead_blanks) if header_row else None)
    if conf < 0.45:
        raise ValueError(
            f"{xlsx_path.name}!{sheet}: header unresolved (confidence {conf}"
            + (", explicit --header-row rejected as non-header-like"
               if header_row else ", no --header-row given")
            + "). Refusing to ingest guessed or invalid column names.")
    abs_header = lead_blanks + hidx
    raw_header = rows[abs_header - 1]
    width = max(len(r) for r in rows[abs_header - 1:])

    header = []
    for i in range(width):
        v = raw_header[i] if i < len(raw_header) else None
        header.append(" ".join(str(v).split()).upper()
                      if v is not None and str(v).strip() else f"COL_{i + 1}")
    seen: dict[str, int] = {}
    columns = []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        columns.append(h if seen[h] == 1 else f"{h}__{seen[h]}")

    data = [r for r in rows[abs_header:] if not _row_blank(r)]
    pidx = None
    for i in range(width):
        vals = [r[i] for r in data if i < len(r) and r[i] is not None and str(r[i]).strip() != ""]
        if not vals:
            continue
        dated = [v for v in vals if as_date(v)]
        if len(dated) / len(vals) >= 0.5 and len(vals) / len(data) >= 0.5:
            pidx = i
            break
    dropped = 0
    if pidx is not None:
        last = max((i for i, r in enumerate(data)
                    if pidx < len(r) and as_date(r[pidx]) is not None), default=-1)
        dropped = len(data) - (last + 1)
        data = data[: last + 1]

    frame = pd.DataFrame(
        [[r[i] if i < len(r) else None for i in range(width)] for r in data],
        columns=columns)
    n = ingest_dataframe(
        conn, frame, table,
        source_path=_source_label(xlsx_path), drive_id=drive_id, sheet=sheet,
        note=(f"{note} ".strip() + f"| header_row={abs_header} conf={conf}"
              f" | tail_dropped={dropped}"))
    print(f"   header row {abs_header} (confidence {conf}), {dropped} trailing "
          f"sentinel/footer row(s) excluded")
    return n


def ingest_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    table: str,
    drive_id: str = "",
    note: str = "",
) -> int:
    df = pd.read_csv(csv_path)
    df = df.dropna(how="all")
    return ingest_dataframe(
        conn, df, table,
        source_path=_source_label(csv_path),
        drive_id=drive_id, sheet="csv", note=note,
    )
