#!/usr/bin/env python3
"""Bag End data toolkit — one consistent entrypoint for Drive + SQLite work.

Usage:
  python3 tools/bagend.py <command> [args]

Commands:
  catalog drive [--root investment]            Census a Drive folder tree -> private/catalog.tsv
  catalog merge-registry                       Add my-data-records.json entries into the census
  catalog find <needle>                        Search the census for a file/folder
  fetch <alias|drive-id> [--name NAME]         Download/export a Drive file into private/raw/
  inspect <local-path> [--md]                  Structure survey of an xlsx/csv (tabs, headers, dates)
  ingest xlsx <path> <sheet> <table> [--skiprows N]
                                               Ingest one xlsx tab into private/books.db
  ingest csv <path> <table>                    Ingest a csv into private/books.db
  query "<sql>"                                Run SQL against private/books.db

Conventions: see tools/README.md. Data stays in private/ (gitignored).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bagend import catalog, config, gws_client, ingest as ingest_mod, inspect as inspect_mod, loader21


def cmd_catalog(args: argparse.Namespace) -> None:
    if args.catalog_cmd == "drive":
        path, n = catalog.write_drive_census(args.root, config.CATALOG_TSV)
        print(f"census complete: {n} files -> {path}")
    elif args.catalog_cmd == "merge-registry":
        if not config.REGISTRY_JSON.exists():
            sys.exit(f"registry not found at {config.REGISTRY_JSON} — copy it from "
                     "C:/Users/fangq/Documents/My Info/Misc/Homepage-DB/Tools/ first")
        added = catalog.merge_registry_into(config.CATALOG_TSV, config.REGISTRY_JSON)
        print(f"registry merge: {added} entries added to {config.CATALOG_TSV}")
    elif args.catalog_cmd == "find":
        for row in catalog.find_in_catalog(config.CATALOG_TSV, args.needle):
            print(f"{row.get('path','')}/{row.get('name','')}\t"
                  f"{row.get('mime_type','')}\t{row.get('drive_id','')}")


def _rel(p: Path) -> str:
    """Repo-relative label for display/provenance; absolute fallback otherwise."""
    p = p.resolve()
    try:
        return str(p.relative_to(config.REPO_ROOT))
    except ValueError:
        return str(p)


def _record_provenance(dest: Path, file_id: str, meta: dict, method: str) -> None:
    """Append one provenance row: which Drive object, which kind, how obtained.

    Without this, an exported native Sheet lands on disk as `<name>.xlsx` and is
    indistinguishable from an uploaded xlsx of the same name — which made a survey
    leg report a *deleted mirror's* filename as though it were the live source.
    """
    log_path = config.RAW_DIR / "_provenance.tsv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new = not log_path.exists()
    with open(log_path, "a", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        if new:
            w.writerow(["local_path", "drive_id", "drive_name", "drive_mime",
                        "source_kind", "obtained_via", "drive_modified", "fetched_at"])
        is_native = meta["mimeType"].startswith("application/vnd.google-apps.")
        w.writerow([_rel(dest), file_id, meta["name"],
                    meta["mimeType"], "native-google-sheet" if is_native else "drive-file",
                    method, meta.get("modifiedTime", ""),
                    datetime.now(timezone.utc).isoformat(timespec="seconds")])


def cmd_sheets(args: argparse.Namespace) -> None:
    """Direct Sheets reads — preferred over xlsx export for native Sheets."""
    from bagend import sheets as sheets_mod
    file_id = gws_client.resolve(args.source)
    if args.sheets_cmd == "tabs":
        meta = sheets_mod.metadata(file_id)
        print(f"{meta['title']}  ({len(meta['tabs'])} grid tabs; charts/BI tabs excluded)")
        for t in meta["tabs"]:
            flag = " [HIDDEN]" if t["hidden"] else ""
            print(f"  {t['title']:34s} {t['rows']:6d}r x {t['columns']:3d}c{flag}")
    elif args.sheets_cmd == "dump":
        dest_dir = Path(args.out).resolve() if args.out else config.RAW_DIR / "sheets"
        meta = sheets_mod.metadata(file_id)
        alias = args.alias or re.sub(r"[^A-Za-z0-9]+", "_", meta["title"]).strip("_")
        targets = [t for t in meta["tabs"] if (not args.tab or t["title"] == args.tab)]
        if args.tab and not targets:
            sys.exit(f"no grid tab named {args.tab!r}; have: "
                     + ", ".join(t["title"] for t in meta["tabs"]))
        for t in targets:
            safe_tab = re.sub(r"[^A-Za-z0-9]+", "_", t["title"]).strip("_")
            out = dest_dir / f"{alias}__{safe_tab}.csv"
            sheets_mod.dump_tab(file_id, t["title"], out)
            rows = sum(1 for _ in open(out)) if out.exists() else 0
            print(f"  dumped {t['title']:30s} -> {_rel(out)} ({rows} lines)")
            _record_provenance(out, file_id, {"name": meta["title"],
                                              "mimeType": "application/vnd.google-apps.spreadsheet",
                                              "modifiedTime": ""}, "sheets.values.get")


def cmd_fetch(args: argparse.Namespace) -> None:
    file_id = gws_client.resolve(args.source)
    meta = gws_client.get_file(file_id)
    dest_name = args.name or meta["name"]
    dest = config.RAW_DIR / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if meta["mimeType"] == "application/vnd.google-apps.spreadsheet":
        # GUARD: never convert a native Sheet to xlsx for analysis. Export injects
        # ~1,000 blank padding rows per tab, crashes on chart/pivot-cache tabs, and
        # re-infers the YEAR on year-less text dates — on 2026-09-06 that produced
        # three false "source defect" reports and made correct data look corrupt.
        if not getattr(args, "allow_xlsx_export", False):
            sys.exit(
                f"{meta['name']!r} is a NATIVE GOOGLE SHEET — refusing to export it to xlsx.\n"
                f"Use the native read path instead:\n"
                f"  python3 tools/bagend.py sheets tabs {args.source}\n"
                f"  python3 tools/bagend.py sheets dump {args.source} [--tab NAME]\n"
                f"(typed CSV, used range only — no padding, no year re-inference)\n"
                f"If you truly need the workbook, re-run with --allow-xlsx-export.")
        out = gws_client.export_sheet(file_id, dest.with_suffix(".xlsx"))
        _record_provenance(out, file_id, meta, "files.export")
        print(f"exported native Sheet -> {out}")
    else:
        out = gws_client.download_file(file_id, dest)
        _record_provenance(out, file_id, meta, "files.get alt=media")
        print(f"downloaded -> {out}")


def cmd_inspect(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if not path.exists():
        sys.exit(f"not found: {path} (fetch it first with `bagend.py fetch`)")
    report = inspect_mod.inspect_any(path, header_row=getattr(args, "header_row", None))
    unresolved = [s["sheet"] for s in report["sheets"] if s.get("header_unresolved")]
    if unresolved:
        print(f"WARNING: header unresolved on {len(unresolved)} tab(s): "
              f"{', '.join(unresolved)} — pass --header-row before trusting these columns",
              file=sys.stderr)
    if args.md:
        print(inspect_mod.render_markdown(report))
    else:
        print(json.dumps(report, indent=2, default=str))


def cmd_ingest(args: argparse.Namespace) -> None:
    conn = ingest_mod.connect()
    try:
        if args.ingest_cmd == "xlsx":
            n = ingest_mod.ingest_xlsx_sheet(
                conn, Path(args.path), args.sheet, args.table,
                header_row=args.header_row, note=args.note)
        else:
            n = ingest_mod.ingest_csv(conn, Path(args.path), args.table, note=args.note)
        print(f"ingested {n} rows into {args.table}")
    finally:
        conn.close()


def cmd_query(args: argparse.Namespace) -> None:
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(args.sql).fetchall()
        if not rows:
            print("(no rows)")
            return
        print("\t".join(rows[0].keys()))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r))
    finally:
        conn.close()


def cmd_export(args: argparse.Namespace) -> None:
    if args.export_cmd == "finpage":
        import sqlite3
        from bagend import finpage
        con = sqlite3.connect(config.DB_PATH)
        con.execute("PRAGMA foreign_keys=ON")
        loader21.assert_schema(con)
        payload = finpage.build_payload(con)
        con.close()
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / "finpage.json"
        target.write_text(json.dumps(payload, indent=1, default=str))
        n_tax = len(payload["pages"]["retirement"]["tax"])
        n_series = len(payload["pages"]["retirement"]["networth"]["as_ofs"])
        print(f"finpage payload -> {target} ({n_series} net-worth points, {n_tax} tax years)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="bagend", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog")
    cat_sub = p_cat.add_subparsers(dest="catalog_cmd", required=True)
    cat_drive = cat_sub.add_parser("drive")
    cat_drive.add_argument("--root", default="investment")
    cat_sub.add_parser("merge-registry")
    cat_find = cat_sub.add_parser("find")
    cat_find.add_argument("needle")

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("source", help="alias (config.py) or raw Drive file ID")
    p_fetch.add_argument("--name", help="destination filename under private/raw/")
    p_fetch.add_argument("--allow-xlsx-export", action="store_true", dest="allow_xlsx_export",
                       help="escape hatch: export a native Sheet to xlsx (discouraged; see README)")

    p_sh = sub.add_parser("sheets", help="direct Google Sheets reads (preferred for native Sheets)")
    sh_sub = p_sh.add_subparsers(dest="sheets_cmd", required=True)
    sh_tabs = sh_sub.add_parser("tabs")
    sh_tabs.add_argument("source")
    sh_dump = sh_sub.add_parser("dump")
    sh_dump.add_argument("source")
    sh_dump.add_argument("--tab", help="single tab title (default: all grid tabs)")
    sh_dump.add_argument("--alias", help="short alias used to name the CSVs")
    sh_dump.add_argument("--out", help="destination dir (default private/raw/sheets/)")

    p_ins = sub.add_parser("inspect")
    p_ins.add_argument("path")
    p_ins.add_argument("--md", action="store_true", help="markdown output")
    p_ins.add_argument("--header-row", type=int, default=None, dest="header_row",
                       help="explicit 1-based header row when detection is unresolved")

    p_ing = sub.add_parser("ingest")
    ing_sub = p_ing.add_subparsers(dest="ingest_cmd", required=True)
    ing_x = ing_sub.add_parser("xlsx")
    ing_x.add_argument("path")
    ing_x.add_argument("sheet")
    ing_x.add_argument("table")
    ing_x.add_argument("--header-row", type=int, default=None, dest="header_row",
                       help="explicit 1-based header row (layout config)")
    ing_x.add_argument("--note")
    ing_c = ing_sub.add_parser("csv")
    ing_c.add_argument("path")
    ing_c.add_argument("table")
    ing_c.add_argument("--note")

    p_q = sub.add_parser("query")
    p_q.add_argument("sql")

    p_ex = sub.add_parser("export", help="emit local data bundles for the financial page")
    ex_sub = p_ex.add_subparsers(dest="export_cmd", required=True)
    ex_fin = ex_sub.add_parser("finpage")
    ex_fin.add_argument("--out", default="private/export",
                        help="destination dir (default private/export; Homepage-DB/BagEnd is the deploy target)")

    args = parser.parse_args()
    {"catalog": cmd_catalog, "fetch": cmd_fetch, "sheets": cmd_sheets,
     "inspect": cmd_inspect,
     "ingest": cmd_ingest, "query": cmd_query, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
