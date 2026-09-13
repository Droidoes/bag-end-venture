#!/usr/bin/env python3
"""P0 loader write-path smoke (companion to schema_parity.py). Synthetic temp CSV
+ temp stores only — never touches private/. Proves: row origin/presence written
into fact_state; the v0.2.5 hash recipe (presence+origin) is live on the write
path; the dedupe probe still recognises unchanged content; blank cells are skipped
(CSV path cannot mint zero_from_blank — that needs the P1 rectangle); the derived
delta post-pass writes presence='estimated' + origin='derived'; src_column carries
the column-grain origin default; an illegal (origin, presence) pair raises
LoadError at load time instead of inserting."""
import sqlite3, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from bagend import loader21

DDL = (ROOT / "tools/schema/books.sql").read_text()

def make_store():
    con = sqlite3.connect(":memory:"); con.executescript(DDL)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
      INSERT INTO src_ref(alias,drive_id,source_kind,read_path,precedence,role) VALUES ('smoke','d','drive-file','files.get alt=media',1,'raw');
      INSERT INTO src_tab(tab_id,source_id,tab,role,dedupe_rule,row_order) VALUES (1,1,'SmokeTab','raw','none','unsorted');
      INSERT INTO dim_account VALUES (1,'ACCT_A','probe-institution','other','Joe','unsettled',NULL);
      INSERT INTO dim_metric VALUES (1,'M1',0,0,'unknown','USD',NULL,NULL);
      INSERT INTO dim_metric VALUES (2,'M2',0,0,'unknown','USD',NULL,NULL);
      INSERT INTO dim_metric VALUES (3,'M3',0,0,'unknown','USD',NULL,NULL);
      INSERT INTO dim_metric VALUES (4,'TOTAL_ASSETS',0,0,'asset','USD',NULL,NULL);
    """)
    return con

ALL_COLS = [{"col": "ColA", "account": "ACCT_A", "metric": "M1", "origin": "entered"},
            {"col": "ColB", "account": "ACCT_A", "metric": "M2"},
            {"col": "AssetsTotal", "account": "ACCT_A", "metric": "TOTAL_ASSETS"},
            {"col": "ColC", "account": "ACCT_A", "metric": "M3", "mode": "derive_from_delta"}]
spec = {"alias": "smoke", "tab": "SmokeTab", "drive_id": "d", "source_kind": "drive-file",
        "read_path": "files.get alt=media", "header_row": 1, "local": None, "columns": ALL_COLS}
acct_ids = {"ACCT_A": 1}; metric_ids = {"M1": 1, "M2": 2, "M3": 3, "TOTAL_ASSETS": 4}

def main():
    with tempfile.TemporaryDirectory() as td:
        csv_p = Path(td) / "smoke.csv"
        csv_p.write_text("Date,ColA,ColB,AssetsTotal,Total Assets\n"
                         "2026-01-31,10.5,,10.5,100.0\n"
                         "2026-02-28,20.0,30.0,50.0,60.0\n")
        spec["local"] = str(csv_p)

        # 1) first load: measured rows (explicit + default origin), one skipped
        #    blank, two derived-delta rows estimated/derived.
        con = make_store(); loader21.assert_schema(con)
        with loader21.Batch(con, note="smoke1") as b:
            n, _ = loader21.load_state_spine(con, b, spec, acct_ids, metric_ids)
        rows = con.execute("SELECT metric_id,value_num,presence,origin,content_hash FROM fact_state ORDER BY state_id").fetchall()
        print("rows:", n)
        for r in rows: print("  ", r)
        assert n == 7, f"expected 7 rows, got {n}"
        assert sum(r[2] == "measured" for r in rows) == 5 and sum(r[2] == "estimated" for r in rows) == 2
        assert sum(r[3] == "derived" for r in rows) == 2 and sum(r[3] == "entered" for r in rows) == 5
        assert any(r[0] == 3 and r[1] == 89.5 and r[2] == "estimated" and r[3] == "derived" for r in rows), "delta 89.5 missing"
        assert any(r[0] == 3 and abs(r[1] - 10.0) < 1e-9 for r in rows), "delta 10.0 missing"
        h_ref = loader21.state_content_hash(1, 1, "2026-01-31", 1, 10.5, "measured", "entered")
        assert rows[0][4] == h_ref, "hash on write path != v0.2.5 recipe"

        # 2) dedupe probe: re-ingest the measured rows only -> zero new rows
        no_derived = {**spec, "columns": [c for c in ALL_COLS if c.get("mode") != "derive_from_delta"]}
        with loader21.Batch(con, note="smoke2") as b2:
            n2, _ = loader21.load_state_spine(con, b2, no_derived, acct_ids, metric_ids)
        print("re-ingest rows:", n2)
        assert n2 == 0, "presence/origin-aware hash broke the identical-content probe"

        # 3) column-grain default: src_column.origin('ColB')='copy' flows onto rows
        #    (legal copy+measured) and changes their hash.
        con.execute("INSERT INTO src_column(tab_id,col_index,header_text,origin) VALUES (1,2,'ColB','copy')")
        with loader21.Batch(con, note="smoke3") as b3:
            loader21.supersede_tab(con, b3.batch_id, 1, ["fact_state"])
            n3, _ = loader21.load_state_spine(con, b3, spec, acct_ids, metric_ids)
        got = con.execute("SELECT DISTINCT presence,origin FROM fact_state WHERE metric_id=2 AND superseded_by_batch_id IS NULL").fetchall()
        cur = con.execute("SELECT content_hash FROM fact_state WHERE metric_id=2 AND superseded_by_batch_id IS NULL").fetchone()[0]
        print("ColB current:", got, "rows:", n3)
        assert got == [("measured", "copy")]
        assert cur != loader21.state_content_hash(1, 2, "2026-02-28", 1, 30.0, "measured", "entered"), \
            "origin is not inside the hash"

        # 4) a genuinely illegal resolved pair must RAISE at load time, not insert.
        #    origin='key' carries NO presence (a key cell is row addressing, not a
        #    fact), so ('key','measured') is illegal on every side.
        con2 = make_store()
        con2.execute("INSERT INTO src_column(tab_id,col_index,header_text,origin) VALUES (1,2,'ColB','key')")
        try:
            with loader21.Batch(con2, note="smoke4") as b4:
                loader21.load_state_spine(con2, b4, no_derived, acct_ids, metric_ids)
            print("FAIL: illegal pair was not refused"); return 1
        except loader21.LoadError as e:
            print("illegal pair refused:", str(e)[:130])

        # 5) CORRECTED SEMANTICS (COS, 2026-09-12): external_links membership is
        #    supposed to OVERRIDE kind (v0.3 §4), so ('external','measured') is now
        #    a LEGAL pair and must no longer raise. KNOWN GAP, asserted here so it
        #    cannot be forgotten: the loader does NOT yet APPLY that precedence --
        #    origin still comes from the cell classification, so a declared-external
        #    column holding literals lands as ('entered','measured'). Enforcing the
        #    override needs the allow-list join, which is P2 work.
        con3 = make_store()
        con3.execute("INSERT INTO src_column(tab_id,col_index,header_text,origin) VALUES (1,2,'ColB','external')")
        try:
            with loader21.Batch(con3, note="smoke5") as b5:
                loader21.load_state_spine(con3, b5, no_derived, acct_ids, metric_ids)
        except loader21.LoadError as e:
            print("FAIL: external x measured wrongly refused:", str(e)[:120]); return 1
        rows = con3.execute("SELECT DISTINCT origin, presence FROM fact_state").fetchall()
        if not any(o == "external" for o, _ in rows):
            print("FAIL: column-grain precedence not applied - declared-external column "
                  f"produced no external rows: {rows}"); return 1
        print("external x measured legal, and column-grain precedence IS applied:", rows)
    print("LOADER SMOKE OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
