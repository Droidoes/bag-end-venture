"""Catalog: the map of what exists.

Two catalog sources, merged into one view:
1. `catalog drive` — recursive census of a Drive folder tree (every file).
2. `catalog registry` — the owner's my-data-records.json (sheet names -> IDs).

The catalog TSV is metadata only (paths, names, mime types, sizes) and is
safe to keep under private/; nothing in it is a financial figure.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .gws_client import walk_tree


def write_drive_census(root_alias: str, out_path: Path) -> tuple[Path, int]:
    from .gws_client import resolve
    root_id = resolve(root_alias)
    rows = walk_tree(root_id, root_name=f"My Info/{root_alias}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["path", "name", "mime_type", "size", "drive_id", "census_date"])
        stamp = datetime.now(timezone.utc).date().isoformat()
        for f in rows:
            w.writerow([f.path, f.name, f.mime_type, f.size, f.id, stamp])
    return out_path, len(rows)


def load_registry(json_path: Path) -> list[dict]:
    """Flatten my-data-records.json into catalog rows."""
    records = json.loads(json_path.read_text())
    rows = []
    for r in records:
        gid = ""
        url = r.get("url", "")
        if "/d/" in url:
            gid = url.split("/d/")[1].split("/")[0]
        rows.append({
            "name": r.get("name", ""),
            "drive_id": gid,
            "local_path_xlsx": r.get("urlExcel", "").replace("ms-excel:ofe|u|file:///", "C:/"),
            "category": "registry",
        })
    return rows


def merge_registry_into(catalog_tsv: Path, registry_json: Path) -> int:
    """Append registry-only entries (marked category=registry) to the census TSV."""
    rows = read_catalog(catalog_tsv)
    existing_ids = {r["drive_id"] for r in rows if r.get("drive_id")}
    added = 0
    for r in load_registry(registry_json):
        if r["drive_id"] and r["drive_id"] not in existing_ids:
            rows.append({
                "path": "registry", "name": r["name"], "mime_type": "registry",
                "size": "", "drive_id": r["drive_id"], "census_date": "",
            })
            added += 1
    with open(catalog_tsv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CATALOG_FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    return added


CATALOG_FIELDS = ["path", "name", "mime_type", "size", "drive_id", "census_date"]


def read_catalog(catalog_tsv: Path) -> list[dict]:
    """Read the catalog TSV, normalizing legacy headerless/short-header files."""
    with open(catalog_tsv, newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        return []
    if rows[0][:2] == ["path", "name"]:
        header = rows[0]
        data = rows[1:]
    else:
        header, data = CATALOG_FIELDS, rows  # legacy headerless census
    out = []
    for r in data:
        row = dict(zip(CATALOG_FIELDS, r))
        row["mime_type"] = row.get("mime_type") or ""
        out.append(row)
    return out


def find_in_catalog(catalog_tsv: Path, needle: str) -> list[dict]:
    """Case-insensitive substring match on name or path."""
    needle = needle.lower()
    return [
        row for row in read_catalog(catalog_tsv)
        if needle in (row.get("name") or "").lower()
        or needle in (row.get("path") or "").lower()
    ]
