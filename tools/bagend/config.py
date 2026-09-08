"""Bag End toolkit configuration.

Paths are relative to the repo root (one level above tools/).
Drive folder/file IDs are pinned here so scripts never hard-code IDs.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PRIVATE_DIR = REPO_ROOT / "private"          # gitignored — may contain numbers
RAW_DIR = PRIVATE_DIR / "raw"                # downloaded/exported source files
CATALOG_TSV = PRIVATE_DIR / "catalog.tsv"    # Drive census output
DB_PATH = PRIVATE_DIR / "books.db"           # the SQLite store

# Registry exported from the owner's Homepage-DB (maps sheet names -> Drive IDs).
REGISTRY_JSON = REPO_ROOT / "private" / "my-data-records.json"

# Named Drive locations. IDs verified 2026-09-06 by ID-qualified parent chains.
#
# Two same-named trees exist and must never be confused:
#   My Drive/My Info/...                          -> LIVE tree (native Google Sheets
#                                                   + xlsx). This is the source of truth.
#   Computers/My Computer/Documents/My Info/...    -> Windows PC backup mirror; holds no
#                                                   native Sheets and may lag the live tree.
DRIVE_FOLDERS = {
    "my-info": "1rDCxJgYoIaYV44jRYUz98j77CCu3mC_x",       # My Drive/My Info
    "investment": "1oRvlVVvXo6oHwaLV1NgoqbpFXzKatkCa",     # My Drive/My Info/Investment (LIVE)
    "tax-records": "15IeIehmPb84IRYUEohLZhMYd64r7Q3xH",    # My Drive/My Info/Tax Records (LIVE)
    # Reference only — never a source of truth, never ingested:
    "investment-pc-backup": "1jFsDqydi1YziamghfWcPw-GcTI2rMpKg",
}

# Out-of-scope locations (owner rulings):
#   * the tax-prep app's own working folder under the PC backup — app scratch,
#     not an archive; the archive for humans lives in My Info/Tax Records.
#   * TD "alina" account (third party) — never ingested into Bag End.
# Paths are matched case-insensitively against the walk-relative folder path.
EXCLUDE_PATH_PATTERNS = [
    "td statements/alina",
]

# Well-known spreadsheet IDs (seeded from my-data-records.json, Sep 2026).
DRIVE_SHEETS = {
    "books": "1kjsXQql1wFibxcuouY_lhhXYZ8tjxoiBoIVrmV8Wmqk",
    "stats": "1HU250_7Si21YDVwJVwb4HV5tnj0TPKg9S_DLuoRNSXQ",
    "summary": "1YIOyZzcoQYMN3mC_WoiAzeGtQfK2mXNRS0BkOGNpfQU",
    "ss-earning": "19aaU3NaPRahyexQtAPvYJDYmPFUkOXEwqIHsZjfL0WI",
    "trading-2026": "1bI3iYKv-DjCpXzkEWZdjjcl91hIERIq9Mi80d-FPd1A",
    "trading-2025": "1XfcbJMy5mm96mcNcjBCfCI9O51gRfprozziEc1YR6I4",
    "trading-2024": "1vwnMTY4jrt98j7hxtSVyh7FbWOSWQQrdJtKEEmz_QNI",
    "trading-2023": "1fifoBc2WZ_GYkleVgztQ_rW7s3nHGrMTUq3IBtrx4po",
    "trading-2022": "1gl3MqwCGxVUtOdzY1XJSSRHQ7BSpYKV_ujyh_zjPDfs",
    "trading-2021": "1qu7oKFiws8ku8k0UlKaOkJHrHtfnOgAnDug4hhkafwI",
    "trading-2020": "1LbYzPdee5tg4EMX9XvKiKbKwcctZL5HnuaDQKu0quzQ",
    "trading-2019": "1gKShpuwZds4rkyGnsPJ6jmCirGuxzZO72wcOqfRaizs",
    "pnl-records": "1ai2HwNkbILVDrpGMM5XrR3hMr4FGjR3SWhh40zdKaMU",
}

READ_PATH_NOTE = "native Sheets are read via sheets.py, never exported to xlsx"

SHEET_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_EXPORT_MIME = "text/csv"
