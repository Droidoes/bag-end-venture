#!/usr/bin/env python3
"""The store gate splits: `mode="write"` stays exact, `mode="read"` takes the
whitelisted pre-migration versions and WARNs.

Why this exists (2026-09-13 live regression). `loader21.assert_schema` answered two
different questions with one answer, so when the schema was bumped to v0.2.6 the
owner's live dashboard stopped regenerating:

    $ python3 tools/bagend.py export finpage
    LoadError: store schema is 'v0.2.4', expected v0.2.6 — apply tools/schema/books.sql
               to a fresh store

The live store legitimately *remains* v0.2.4 and cannot be rebuilt yet: the shadow
holds only the first wave, so promoting it would drop cost basis, SSA, checking/card
and events. A consumer that only reads was being refused for a writer's reason.

The split, and what each side of it is allowed to assume, lives in
`loader21.READ_COMPATIBLE_SCHEMA_VERSIONS`. This battery pins it in both directions:

  1. a genuine v0.2.4 store (built from `old_books_v0.2.4.sql`) is REFUSED by write
     and ACCEPTED by read, with exactly one warning naming the version and the fact
     that the store is pre-migration;
  2. the current store is accepted by BOTH and the read path is SILENT;
  3. every member of the read set is read-accepted, and only the current one is
     write-accepted;
  4. an absurd or future version, an empty stamp and a missing stamp are refused by
     BOTH — the read set is a whitelist, not "anything except current";
  5. `foreign_keys` OFF is still refused in BOTH modes (read mode is not a licence
     to open an ungoverned connection);
  6. an unknown `mode` raises instead of quietly defaulting;
  7. the claim the whitelist makes is checked, not asserted: on the older store the
     surfaces the consumer requires (v_net_worth.as_of/metric_id/total) are PRESENT
     and the newer composition columns are simply ABSENT — so a reader must not
     require them, and a reader that does must fail at its own query;
  8. the actual regression, end to end at the CLI edge: `cmd_export("finpage")`
     against a v0.2.4-shaped file store builds a payload through `--db`, and the same
     call on an unrecognised store is refused.

Offline, synthetic, temp-dir only. Nothing here opens private/books.db, and NO
FINANCIAL VALUE IS READ OR PRINTED — only versions, column names, counts and shapes.

Run from the repo root:
    python3 tools/tests/schema_read_mode_tests.py
"""
import argparse
import contextlib
import importlib.util
import io
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
# Imported as `bagend.loader21`, the module object `tools/bagend.py` itself binds —
# not `tools.bagend.loader21`, which is a SECOND copy of the same file. A LoadError
# raised from one copy is not an instance of the other's class, and section 8 proves
# the CLI's exception, so the identity has to match.
from bagend import loader21 as L  # noqa: E402

DDL_NEW = Path("tools/schema/books.sql").read_text()
DDL_OLD = Path("tools/tests/old_books_v0.2.4.sql").read_text()
CURRENT = L.SCHEMA_VERSION
OLD = "v0.2.4"           # the live store's version: the subject of test, not a pin
PASS = FAIL = 0
FAILURES: list[str] = []


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def section(title):
    print(f"\n-- {title}")


def store(ddl: str, relabel: str | None = None) -> sqlite3.Connection:
    """An in-memory store from `ddl`, optionally re-stamped (the gate is being
    tested, so a stamp is a stamp: `relabel` never claims the DDL changed)."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(ddl)
    if relabel is not None:
        con.execute("UPDATE _schema_meta SET value=? WHERE key='schema_version'", (relabel,))
    return con


def naked() -> sqlite3.Connection:
    """A connection with foreign_keys OFF — the pragma SQLite defaults to off."""
    return sqlite3.connect(":memory:")


def run(fn, *a, **kw):
    """Return (result, raised, stderr_text) — the warning is part of the contract."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return fn(*a, **kw), None, err.getvalue()
    except Exception as exc:            # noqa: BLE001 — the raise IS the observation
        return None, exc, err.getvalue()


def refused(fn, *a, **kw):
    res, exc, err = run(fn, *a, **kw)
    return isinstance(exc, L.LoadError), (str(exc) if exc else ""), err


def accepted(fn, *a, **kw):
    res, exc, err = run(fn, *a, **kw)
    return exc is None, err


def cols(con, name) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({name})")]


def sh(*argv):
    """Run the REAL entrypoint (offline; only a temp --out and a temp --db)."""
    p = subprocess.run([sys.executable, "tools/bagend.py", *argv], cwd=".",
                       capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------- synthetic data
# The minimum a finpage payload needs: one additive TOTAL_ASSETS month, both SS
# claim ages, one holding. Values are placeholders — never read, never printed.
def populate(con, old: bool) -> None:
    con.execute("INSERT INTO load_batch(batch_id,started_at,status) "
                "VALUES (1,'2026-01-01T00:00:00','complete')")
    con.execute("INSERT INTO src_ref(source_id,alias,drive_id,source_kind,read_path,"
                "precedence,role) VALUES (1,'probe','drv','native-google-sheet',"
                "'sheets.values.get',1,'raw')")
    con.execute("INSERT INTO dim_account(account_id,code,institution,registration,"
                "entity,purpose) VALUES (1,'ACCT_X','synthetic','other','Joe','unsettled')")
    con.execute("INSERT INTO dim_metric(metric_id,name,is_flow,is_year_relative,"
                "polarity,unit) VALUES (1,'TOTAL_ASSETS',0,0,'asset','USD')")
    con.execute("INSERT INTO dim_security(security_id,ticker) VALUES (1,'AAA')")
    if old:
        # v0.2.4 fact_state carries NEITHER origin NOR error_type: a reader that
        # required them would be requiring a column that does not exist here.
        con.execute("""INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,
            seq_in_date,value_num,presence,period_grain,content_hash,source_id,
            batch_id,ingested_at) VALUES ('p|1',1,1,'2026-01-31',1,100.0,'measured',
            'month-end','h1',1,1,'2026-01-01T00:00:00')""")
    else:
        con.execute("""INSERT INTO fact_state(natural_key,account_id,metric_id,as_of,
            seq_in_date,value_num,presence,origin,period_grain,content_hash,source_id,
            batch_id,ingested_at) VALUES ('p|1',1,1,'2026-01-31',1,100.0,'measured',
            'entered','month-end','h1',1,1,'2026-01-01T00:00:00')""")
    for basis, amount in (("Age62", 1000.0), ("Age67", 1500.0)):
        con.execute("INSERT INTO ss_benefit_estimates(natural_key,work_year,claim_basis,"
                    "amount,unit,is_estimate,source_id,batch_id,ingested_at) "
                    "VALUES (?,2025,?,?,'monthly',1,1,1,'2026-01-01T00:00:00')",
                    (basis, basis, amount))
    con.execute("INSERT INTO holding_state(natural_key,account_id,security_id,as_of,"
                "market_value,source_id,batch_id,ingested_at) VALUES "
                "('h|1',1,1,'2026-01-31',25.0,1,1,'2026-01-01T00:00:00')")


def write_file_store(tmp: Path, name: str, ddl: str, old: bool) -> Path:
    """A FILE store (the CLI path opens by URI, so :memory: cannot serve it)."""
    path = tmp / name
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(ddl)
    populate(con, old)
    con.commit()
    con.close()
    return path


def main() -> int:
    print("== read-mode / write-mode store gate battery ==")
    check("the gate is keyword-split and defaults to the strict answer",
          "mode" in L.assert_schema.__code__.co_varnames
          and L.assert_schema.__kwdefaults__ == {"mode": "write"},
          L.assert_schema.__kwdefaults__)

    # ---------------------------------------------------------------- 1. pre-migration store
    section(f"1. a genuine {OLD} store: refused by write, accepted by read")
    old_store = store(DDL_OLD)
    check(f"the fixture really is a pre-migration stamp ({OLD})",
          old_store.execute("SELECT value FROM _schema_meta WHERE key='schema_version'"
                            ).fetchone()[0] == OLD)
    check(f"and really is not the current version (the bump is honest: {CURRENT} != {OLD})",
          OLD != CURRENT)
    ok_w, msg_w, _ = refused(L.assert_schema, old_store, mode="write")
    check("mode='write' REFUSES it", ok_w, msg_w)
    check("mode='write' keeps the pre-split message verbatim (the loader's error text "
          "did not change)",
          msg_w == f"store schema is {OLD!r}, expected {CURRENT} — apply "
                   f"tools/schema/books.sql to a fresh store", msg_w)
    ok_r, warn = accepted(L.assert_schema, old_store, mode="read")
    check("mode='read' ACCEPTS it", ok_r, warn)
    lines = [ln for ln in warn.splitlines() if ln.strip()]
    check("read mode says so exactly once", len(lines) == 1, lines)
    check("the warning names the store's version", OLD in (lines[0] if lines else ""), lines)
    check("the warning names the toolkit's version too", CURRENT in (lines[0] if lines else ""), lines)
    check("the warning says PRE-MIGRATION", "PRE-MIGRATION" in (lines[0] if lines else "").upper(), lines)
    check("the warning is a warning, not an error line",
          not (lines[0].lower().startswith("error") if lines else True), lines)
    check("the warning tells the operator where the justification lives",
          "READ_COMPATIBLE_SCHEMA_VERSIONS" in (lines[0] if lines else ""), lines)
    check("the default (no mode at all) is still the strict answer",
          refused(L.assert_schema, old_store)[0])
    check("...and a read consumer that forgets to say so is refused",
          refused(L.assert_schema, old_store)[1].startswith("store schema is"),
          refused(L.assert_schema, old_store)[1])

    # ---------------------------------------------------------------- 2. current store
    section(f"2. the current store ({CURRENT}): accepted by BOTH, and read is silent")
    new_store = store(DDL_NEW)
    ok_w, _, _ = refused(L.assert_schema, new_store, mode="write")
    check("mode='write' accepts the current store", not ok_w)
    ok_r, warn = accepted(L.assert_schema, new_store, mode="read")
    check("mode='read' accepts the current store", ok_r, warn)
    check("...and emits NO warning on a store that needs no caveat", warn == "", repr(warn))
    check("the current version is a member of the read set (a bump cannot orphan itself)",
          CURRENT in L.READ_COMPATIBLE_SCHEMA_VERSIONS)

    # ---------------------------------------------------------------- 3. set membership
    section("3. every member of the read set is read-accepted; only current is write-accepted")
    check("the read set is a frozenset (nobody appends to it at runtime)",
          isinstance(L.READ_COMPATIBLE_SCHEMA_VERSIONS, frozenset),
          type(L.READ_COMPATIBLE_SCHEMA_VERSIONS).__name__)
    for v in sorted(L.READ_COMPATIBLE_SCHEMA_VERSIONS):
        if v == CURRENT:
            continue        # the store on disk is the current one; covered in 2
        s = store(DDL_NEW, relabel=v)     # a GATE test: the stamp is the variable
        ok_r, warn = accepted(L.assert_schema, s, mode="read")
        check(f"member {v}: read-accepted", ok_r, warn)
        check(f"member {v}: read-accepted with a warning (it is not current)",
              bool(warn.strip()), repr(warn))
        ok_w, _, _ = refused(L.assert_schema, s, mode="write")
        check(f"member {v}: still write-REFUSED (older DDL must not be written)", ok_w)
        s.close()

    # ---------------------------------------------------------------- 4. whitelist, not "anything"
    section("4. the negative direction: an unrecognised store is refused by BOTH")
    for bogus in ("v0.0.1", "v9.9.9", "0.2.6", "", "v0.3.0", CURRENT + "-draft"):
        s = store(DDL_NEW, relabel=bogus)
        ok_w, msg_w, _ = refused(L.assert_schema, s, mode="write")
        ok_r, msg_r, _ = refused(L.assert_schema, s, mode="read")
        check(f"{bogus!r}: refused by write", ok_w, msg_w)
        check(f"{bogus!r}: refused by READ too (the read set is a whitelist)", ok_r, msg_r)
        check(f"{bogus!r}: the refusal says it is not in the READ-COMPATIBLE set",
              "READ-COMPATIBLE" in msg_r, msg_r)
        s.close()
    s = store(DDL_NEW)
    s.execute("DELETE FROM _schema_meta")
    ok_w, _, _ = refused(L.assert_schema, s, mode="write")
    ok_r, msg_r, _ = refused(L.assert_schema, s, mode="read")
    check("an unstamped store is refused by both modes (None is not a version)",
          ok_w and ok_r, msg_r)
    s.close()

    # ---------------------------------------------------------------- 5. FK still required
    section("5. read mode does NOT relax the other half of the guard")
    ok_w, msg_w, _ = refused(L.assert_schema, naked(), mode="write")
    ok_r, msg_r, _ = refused(L.assert_schema, naked(), mode="read")
    check("foreign_keys OFF refused in write mode", ok_w, msg_w)
    check("foreign_keys OFF refused in READ mode as well", ok_r, msg_r)
    check("...with the same message (no softening for readers)", msg_w == msg_r, (msg_w, msg_r))
    old_nofk = naked()
    old_nofk.executescript(DDL_OLD)
    ok_r, msg, _ = refused(L.assert_schema, old_nofk, mode="read")
    check("even a whitelisted version is refused on an FK-off connection", ok_r, msg)
    check("so the reader cannot be talked into a pre-migration store with a bad pragma",
          "foreign_keys" in msg, msg)
    old_nofk.close()

    # ---------------------------------------------------------------- 6. unknown mode
    section("6. an unknown mode raises rather than defaulting")
    for bad_mode in ("rea", "READ", "Write", None, ""):
        ok, msg, _ = refused(L.assert_schema, store(DDL_NEW), mode=bad_mode)
        check(f"mode={bad_mode!r} raises (a typo cannot silently pick a policy)", ok, msg)
        check(f"mode={bad_mode!r} names the two legal modes",
              "'write'" in msg and "'read'" in msg, msg)

    # ---------------------------------------------------------------- 7. the shape claim
    section("7. what the whitelist CLAIMS about the older read surfaces, checked")
    rw = cols(old_store, "v_net_worth")
    for c in ("as_of", "metric_id", "total"):
        check(f"the {OLD} v_net_worth exposes {c} (the reader's whole requirement)", c in rw, rw)
    for c in ("n_copy", "n_additive", "composition_class", "n_measured"):
        check(f"the v0.2.6-only column {c} is ABSENT on {OLD} (absent, not wrong)",
              c not in rw, rw)
    check("and PRESENT on the current store (the set did not drift by accident)",
          all(c in cols(new_store, "v_net_worth") for c in ("n_copy", "n_additive")))
    fs_old, fs_new = cols(old_store, "fact_state"), cols(new_store, "fact_state")
    check(f"fact_state exists on {OLD} with the value columns the readers use",
          all(c in fs_old for c in ("as_of", "metric_id", "value_num", "presence")), fs_old)
    check(f"...and origin/error_type are absent there, so no reader may require them",
          not any(c in fs_old for c in ("origin", "error_type"))
          and all(c in fs_new for c in ("origin", "error_type")), (fs_old, fs_new))
    check("dim_metric is column-identical across the two", fs_old and cols(old_store, "dim_metric")
          == cols(new_store, "dim_metric"), (cols(old_store, "dim_metric"),
                                             cols(new_store, "dim_metric")))
    # The claim is about shape, never about numbers: on the older view the total sums
    # every component, so `total IS NOT NULL` is a no-op there. Asserting that keeps
    # the caveat honest instead of letting the word "compatible" mean "identical".
    row = old_store.execute("SELECT SUM(total IS NOT NULL), COUNT(*) FROM v_net_worth").fetchone()
    check(f"a query written for the v0.2.6 NULL semantics still RUNS on {OLD} "
          f"(it just reads pre-Slice-B totals)", row is not None, row)

    # ---------------------------------------------------------------- 8. end to end
    section("8. the regression itself: export finpage against a pre-migration store")
    spec = importlib.util.spec_from_file_location("bagend_cli", "tools/bagend.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        db_old = write_file_store(tmp, "pre-migration.db", DDL_OLD, old=True)
        db_new = write_file_store(tmp, "current.db", DDL_NEW, old=False)
        db_bogus = write_file_store(tmp, "unrecognised.db", DDL_NEW, old=False)
        with sqlite3.connect(db_bogus) as c:
            c.execute("UPDATE _schema_meta SET value='v0.0.1' WHERE key='schema_version'")

        # the real entrypoint, so the --db flag is exercised as an owner would use it
        rc, so, se = sh("export", "finpage", "--db", str(db_old), "--out", str(tmp / "cli"))
        check("--db is accepted by the CLI and the export exits 0 on a pre-migration store",
              rc == 0, (rc, se[-300:]))
        check("the CLI run warns about the pre-migration store", "PRE-MIGRATION" in se.upper(),
              se[-300:])
        check("the CLI run names the store and its version in the result line (counts only)",
              db_old.name in so and OLD in so, so)
        check("the bundle landed where --out said", (tmp / "cli" / "finpage.json").exists())
        rc2, so2, se2 = sh("export", "finpage", "--db", str(db_bogus), "--out", str(tmp / "cli2"))
        check("the same CLI refuses a store outside the read set", rc2 != 0, (rc2, so2))
        check("...naming the READ-COMPATIBLE set in the failure", "READ-COMPATIBLE" in se2,
              se2[-300:])
        check("a refused CLI run writes no bundle", not (tmp / "cli2" / "finpage.json").exists())

        out = tmp / "out"
        ok, err, warn = run(cli.cmd_export,
                            argparse.Namespace(export_cmd="finpage", out=str(out),
                                               db=str(db_old)))
        check("cmd_export succeeds against a v0.2.4-shaped store (before the split it "
              "raised LoadError here)", err is None, str(err))
        check("...while emitting the pre-migration warning on the way",
              "PRE-MIGRATION" in warn.upper(), repr(warn))
        payload_path = out / "finpage.json"
        check("the bundle was written", payload_path.exists())
        if payload_path.exists():
            import json as _json
            payload = _json.loads(payload_path.read_text())
            check("the bundle RECORDS that it came from a pre-migration store",
                  payload["meta"]["schema"] == OLD, payload["meta"]["schema"])
            nw = payload["pages"]["retirement"]["networth"]
            check("the net-worth anchor is present (shape only, never the value)",
                  nw["total"] is not None and nw["as_of"] == "2026-01-31", nw["as_of"])
            check("the series is shaped and the tax page is a list (1 point here)",
                  len(nw["as_ofs"]) == 1 and isinstance(payload["pages"]["retirement"]["tax"], list),
                  len(nw["as_ofs"]))
        out2 = tmp / "out2"
        ok2, err2, warn2 = run(cli.cmd_export,
                               argparse.Namespace(export_cmd="finpage", out=str(out2),
                                                  db=str(db_new)))
        check("the same call against a current store succeeds", err2 is None, str(err2))
        check("...and stays silent", warn2 == "", repr(warn2))
        _r, err3, _w3 = run(cli.cmd_export,
                            argparse.Namespace(export_cmd="finpage", out=str(tmp / "out3"),
                                               db=str(db_bogus)))
        check("and a store outside the read set is STILL refused at the CLI edge",
              isinstance(err3, L.LoadError) and "READ-COMPATIBLE" in str(err3), str(err3))
        check("no bundle was written for the refused store",
              not (tmp / "out3" / "finpage.json").exists())
        probe = cli._connect_ro(db_bogus)
        try:
            probe.execute("CREATE TABLE _should_not_exist(a)")
            writable = True
        except sqlite3.OperationalError:
            writable = False
        finally:
            probe.close()
        check("_connect_ro honours --db and the handle is still read-only "
              "(--db cannot turn a smoke into a write)", not writable)
        # --db takes an arbitrary path, and SQLite's URI parser reads `#` as a
        # fragment: unescaped, `store#1.db` opens a DIFFERENT, empty database and
        # looks like a clean read of the wrong store. Percent-encoding is what
        # prevents it, so the hazard is asserted rather than assumed.
        db_hash = write_file_store(tmp, "pre#migration.db", DDL_OLD, old=True)
        _r4, err4, _w4 = run(cli.cmd_export,
                             argparse.Namespace(export_cmd="finpage", out=str(tmp / "out4"),
                                                db=str(db_hash)))
        check("--db opens the store a `#` in its path NAMES (not a silently empty one)",
              err4 is None, str(err4))

    old_store.close()
    new_store.close()

    print(f"\n{PASS} passed, {FAIL} failed")
    if FAILURES:
        print("FAILURES:", *FAILURES, sep="\n  ")
    print("BATTERY COMPLETE")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
