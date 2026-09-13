#!/usr/bin/env python3
"""P2 gate — shadow-vs-live diff for the first-wave structural load, classified
three ways: **intended fix** / **bug** / **unknown**.

Contract: docs/superpowers/plans/2026-09-12-structural-prefetch-v0.3.md §8 (P2),
§10 (first wave), and the task's Deliverable B.5.

What it compares (counts, keys and nullness only — NEVER a financial value):
  * fact_state          for source alias `stats:net-worth-data`
  * ss_earnings_annual  for source alias `ss_earning:official-data`

`zero_from_blank` is PRE-DECLARED as intended divergence: the legacy values-only
CSV path skipped a blank cell, while the structural reader materialises every
in-rectangle blank as a stated zero, so row counts are expected to rise.

Exit status: 0 when every difference is an intended fix (or there is no shadow
store to diff); 1 when any difference is a bug or remains unknown/unreviewed.

Run from the repo root:
    python3 tools/tests/shadow_diff.py [--live private/books.db]
                                       [--shadow private/books-shadow.db]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# PRE-DECLARED intended divergence (blueprint v0.3 §8 row P2 and §4 blank rule).
PRE_DECLARED_INTENDED = {
    "zero_from_blank": "an in-rectangle blank is a STATED zero (§3/§4); the legacy "
                       "values-only CSV skipped it, so materialising blanks must add rows",
}

# Differences already REVIEWED against source evidence, keyed by a stable
# signature so a NEW unreviewed difference of the same shape is caught (the
# harness checks the observed count against `expect`). Dimension tokens only —
# no values. Rationale for each is the CSV `_typed` serial->date corruption:
# the values-only dump rendered a NUMBER cell in [20000,80000] as an ISO date,
# which the legacy loader then refused, while the native artifact keeps it.
REVIEWED = {
    ("fact_state", "stats:net-worth-data", "HH", "IRS_INCOME", "added",
     "measured", "entered"): (
        3, "values-only CSV rendered three NUMBER-format cells as ISO dates "
           "(serial->date artifact), so the legacy loader dropped them; the native "
           "artifact carries them as NUMBER literals, so the structural read recovers them"),
    ("fact_state", "stats:net-worth-data", "FD_LTC", "TOTAL_ASSETS", "removed",
     "estimated", None): (
        1, "a phantom derived residual: the CSV lost one component to the same "
           "serial->date corruption, so Total Assets - sum(other accounts) was nonzero; "
           "the native artifact's components sum to the source total, so no LTC row exists"),
    ("fact_state", "stats:net-worth-data", "FD_VZW_401K", "TOTAL_ASSETS", "added",
     "measured", "entered"): (
        2, "two NUMBER-format cells the values-only CSV rendered as ISO dates "
           "(serial->date artifact); the native artifact carries them as NUMBER "
           "literals, so the structural read recovers them"),
    ("ss_earnings_annual", "ss_earning:official-data", None, None, "added",
     "measured", "entered"): (
        3, "the CSV carried ISO-date-shaped earnings for the three earliest work years "
           "(serial->date artifact); the native artifact carries NUMBER cells, so the "
           "structural read recovers three measured years"),
}


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def source_map(con: sqlite3.Connection) -> dict:
    return {r["source_id"]: r["alias"] for r in con.execute("SELECT source_id, alias FROM src_ref")}


def norm_key(natural_key: str) -> str:
    """Drop the source_id prefix (it differs between stores) and keep the business
    identity: alias|account|metric|as_of|seq (or alias|work_year)."""
    return natural_key.split("|", 1)[1] if "|" in natural_key else natural_key


def cols(con: sqlite3.Connection, table: str) -> set:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def fact_rows(con: sqlite3.Connection, smap: dict, alias: str):
    sid = next((k for k, v in smap.items() if v == alias), None)
    if sid is None:
        return {}
    has_origin = "origin" in cols(con, "fact_state")
    sel = ("f.natural_key, f.presence, a.code AS account, m.name AS metric, "
           "f.value_num IS NULL AS vnull"
           + (", f.origin" if has_origin else ", NULL AS origin"))
    out = {}
    for r in con.execute(
            f"""SELECT {sel} FROM fact_state f
                JOIN dim_account a ON a.account_id = f.account_id
                JOIN dim_metric m ON m.metric_id = f.metric_id
                WHERE f.source_id = ? AND f.superseded_by_batch_id IS NULL""", (sid,)):
        out[norm_key(r["natural_key"])] = dict(r)
    return out


def ss_rows(con: sqlite3.Connection, smap: dict, alias: str):
    sid = next((k for k, v in smap.items() if v == alias), None)
    if sid is None:
        return {}
    c = cols(con, "ss_earnings_annual")
    has_presence = "presence" in c
    has_origin = "origin" in c
    sel = ("natural_key, ss_taxed IS NULL AS ss_null, medicare_taxed IS NULL AS med_null"
           + (", presence" if has_presence else ", NULL AS presence")
           + (", origin" if has_origin else ", NULL AS origin"))
    out = {}
    for r in con.execute(
            f"""SELECT {sel} FROM ss_earnings_annual
                WHERE source_id = ? AND superseded_by_batch_id IS NULL""", (sid,)):
        out[norm_key(r["natural_key"])] = dict(r)
    return out


def diff_table(table, alias, live_rows, shadow_rows, differences, notes):
    # key sets
    for k in sorted(set(shadow_rows) - set(live_rows)):
        s = shadow_rows[k]
        differences.append({
            "table": table, "alias": alias, "kind": "added",
            "account": s.get("account"), "metric": s.get("metric"),
            "presence": s.get("presence"), "origin": s.get("origin"),
        })
    for k in sorted(set(live_rows) - set(shadow_rows)):
        l = live_rows[k]
        differences.append({
            "table": table, "alias": alias, "kind": "removed",
            "account": l.get("account"), "metric": l.get("metric"),
            "presence": l.get("presence"), "origin": None,
        })
    # attribute changes on shared keys
    for k in sorted(set(live_rows) & set(shadow_rows)):
        l, s = live_rows[k], shadow_rows[k]
        if l.get("presence") != s.get("presence") and l.get("presence") is not None \
                and s.get("presence") is not None:
            differences.append({
                "table": table, "alias": alias, "kind": "presence",
                "account": s.get("account"), "metric": s.get("metric"),
                "presence": s.get("presence"), "origin": s.get("origin"),
                "old_presence": l.get("presence"),
            })
        for vcol in ("vnull", "ss_null", "med_null"):
            if vcol in l and vcol in s and l[vcol] != s[vcol]:
                differences.append({
                    "table": table, "alias": alias, "kind": "value_null",
                    "account": s.get("account"), "metric": s.get("metric"),
                    "presence": s.get("presence"), "origin": s.get("origin"),
                    "old": "null" if l[vcol] else "set",
                    "new": "null" if s[vcol] else "set",
                })
    notes.append(f"{table} [{alias}]: live={len(live_rows)} shadow={len(shadow_rows)} "
                 f"delta={len(shadow_rows) - len(live_rows):+d}")


def sig(d: dict):
    return (d["table"], d["alias"], d["account"], d["metric"], d["kind"],
            d.get("presence"), d.get("origin"))


def classify(d: dict) -> str:
    """Rules first; anything not explained here must be REVIEWED or it is unknown."""
    if d["kind"] == "added":
        if d.get("presence") == "zero_from_blank":
            return "intended"                       # pre-declared
        if d.get("origin") in ("derived", "external", "copy"):
            return "intended"                       # structural derivation now visible
        if d.get("presence") == "estimated":
            return "intended"
        return "unknown"
    if d["kind"] == "removed":
        return "unknown"
    if d["kind"] == "presence":
        if d.get("old_presence") == "measured" and d.get("presence") in (
                "zero_from_blank", "estimated"):
            return "intended"
        return "unknown"
    if d["kind"] == "value_null":
        if d.get("old") == "null" and d.get("new") == "set":
            return "intended"                       # blank/placeholder now a stated value
        return "bug"                                # a value vanished -> data loss
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", default="private/books.db")
    ap.add_argument("--shadow", default="private/books-shadow.db")
    args = ap.parse_args()
    live_p, shadow_p = Path(args.live), Path(args.shadow)
    if not live_p.exists():
        print(f"SKIP: live store not found at {live_p}")
        return 0
    if not shadow_p.exists():
        print(f"SKIP: shadow store not found at {shadow_p} — the P2 shadow battery "
              f"has not been built/loaded")
        return 0

    live, shadow = connect_ro(live_p), connect_ro(shadow_p)
    lmap, smap = source_map(live), source_map(shadow)
    differences: list[dict] = []
    notes: list[str] = []

    print("== shadow vs live — first wave (stats / ss_earning) ==")
    print(f"live   {live_p}  schema={live.execute('SELECT value FROM _schema_meta').fetchone()[0]}")
    print(f"shadow {shadow_p}  schema={shadow.execute('SELECT value FROM _schema_meta').fetchone()[0]}")
    for name, why in PRE_DECLARED_INTENDED.items():
        print(f"  pre-declared intended divergence: {name} — {why}")

    alias_stats = "stats:net-worth-data"
    alias_ss = "ss_earning:official-data"
    diff_table("fact_state", alias_stats,
               fact_rows(live, lmap, alias_stats), fact_rows(shadow, smap, alias_stats),
               differences, notes)
    diff_table("ss_earnings_annual", alias_ss,
               ss_rows(live, lmap, alias_ss), ss_rows(shadow, smap, alias_ss),
               differences, notes)

    # classify, honouring the reviewed ledger and verifying its expected counts
    buckets = {"intended": 0, "bug": 0, "unknown": 0}
    by_rule = {}
    observed_reviewed: dict = {}
    unresolved: list[str] = []
    for d in differences:
        verdict = classify(d)
        s = sig(d)
        if verdict == "unknown" and s in REVIEWED:
            verdict = "intended"
            observed_reviewed[s] = observed_reviewed.get(s, 0) + 1
        buckets[verdict] += 1
        if verdict == "intended":
            tag = "rule:" + (d.get("presence") or "?") if s not in REVIEWED else "reviewed"
        else:
            tag = verdict
        by_rule[tag] = by_rule.get(tag, 0) + 1
        if verdict == "unknown" or verdict == "bug":
            unresolved.append(f"{d['table']} {d['alias']} {d['kind']} "
                              f"acct={d.get('account')} metric={d.get('metric')} "
                              f"presence={d.get('presence')} origin={d.get('origin')}")
    # a reviewed signature whose observed count changed is no longer reviewed
    for s, (expect, why) in REVIEWED.items():
        got = observed_reviewed.get(s, 0)
        if got != expect:
            buckets["intended"] -= got
            buckets["unknown"] += got
            unresolved.append(f"REVIEWED count changed for {s}: expected {expect}, saw {got} — {why}")

    for n in notes:
        print(f"  {n}")
    print("  difference classification:")
    for k in ("intended", "bug", "unknown"):
        print(f"    {k}: {buckets[k]}")
    for tag, n in sorted(by_rule.items()):
        print(f"    [{tag}] {n}")
    if unresolved:
        print("  UNRESOLVED differences (first 10):")
        for line in unresolved[:10]:
            print(f"    - {line}")

    drift = [u for u in unresolved if u.startswith("REVIEWED count changed")]
    per_table: dict = {}
    for d in differences:
        verdict = classify(d)
        s = sig(d)
        if verdict == "unknown" and s in REVIEWED:
            verdict = "intended"
        per_table.setdefault(d["table"], {"intended": 0, "bug": 0, "unknown": 0})
        per_table[d["table"]][verdict] += 1
    for table in sorted({d["table"] for d in differences}):
        st = per_table[table]
        status = "PASS" if (st["bug"] == 0 and st["unknown"] == 0
                            and not any(table in u for u in drift)) else "FAIL"
        print(f"  {status}  {table}  (intended={st['intended']} bug={st['bug']} "
              f"unknown={st['unknown']})")

    ok = buckets["bug"] == 0 and buckets["unknown"] == 0
    print("BATTERY COMPLETE")
    if not ok:
        print(f"shadow_diff FAILED: bug={buckets['bug']} unknown={buckets['unknown']}")
        return 1
    print("shadow_diff PASSED: every difference is an intended fix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
