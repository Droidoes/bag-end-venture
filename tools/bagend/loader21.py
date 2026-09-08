"""books.db v0.2.1 loader — the ratified contract as code (blueprint §3).

Implements: batch identity + atomicity · source-scoped natural keys ·
supersede-then-insert (whole-tab scope) · per-source dedupe rules ·
content_hash recipe H(account|metric|as_of|ordinal|value) for state ·
row_order-aware seq derivation · strict date roundtrip · UNMAPPED sentinels ·
schema-version + foreign_keys assertion on connect.

Curation (what loads, and how each column maps) lives in
private/curation/*.json — this module is method only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA_VERSION = "v0.2.4"
TOOL_VERSION = "loader21.py"


class LoadError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assert_schema(conn: sqlite3.Connection) -> None:
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if not fk:
        raise LoadError("PRAGMA foreign_keys is OFF on this connection — refusing to load")
    row = conn.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()
    if row != (SCHEMA_VERSION,):
        raise LoadError(f"store schema is {row}, expected {SCHEMA_VERSION} — apply tools/schema/books.sql to a fresh store")


def norm_label(s) -> str:
    return " ".join(str(s).split())


def coerce_date(v, fmt: str | None = None) -> tuple[str | None, str | None]:
    """Strict roundtrip coercion. Returns (iso_date, reason) — one is None.
    Rejects anything that doesn't survive date(x) = x, and records the raw form."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, "empty"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # Excel serial dates (COLA-style) are NOT supported in wave 1: honest refusal.
        return None, f"serial:{v!r}"
    s = norm_label(v)
    if s in ("---", "-", "N/A", "#VALUE!", "#N/A"):
        return None, f"placeholder:{s}"
    if fmt and fmt == "%y-%b":
        s = _re.sub(r"^(\d)-", r"0\1-", s)  # '9-Dec' -> '09-Dec'
    m = None
    fmts = [fmt] if fmt else []
    fmts += ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            m = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if m is None:
        return None, f"unparseable:{s!r}"
    iso = m.strftime("%Y-%m-%d")
    if fmt in ("%y-%b", "%b-%y", "%Y-%m"):
        # month-level source: return YYYY-MM; caller may coerce to month-end
        return iso[:7], None
    try:
        rt = datetime.strptime(iso, "%Y-%m-%d")  # roundtrip
        if m.strftime("%Y-%m-%d") != iso:
            return None, f"roundtrip-mismatch:{s!r}"
        return iso, None
    except ValueError:
        return None, f"impossible-date:{s!r}"


def coerce_num(v) -> tuple[float | None, str | None]:
    """Coerce a cell to REAL the honest way. Returns (value, reason)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, "empty"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), None
    s = norm_label(v)
    if s in ("---", "-", "N/A", "#VALUE!", "#N/A"):
        return None, f"placeholder:{s}"
    if s.startswith("$"):
        s = s[1:]
    # strip commas/currency/parens-negative only when the result round-trips as a number
    for cand in (s, s.replace(",", "")):
        try:
            return float(cand), None
        except ValueError:
            continue
    try:
        neg = s.startswith("(") and s.endswith(")")
        return float("-" + s[1:-1]) if neg else float(s), None
    except ValueError:
        return None, f"non-numeric:{s!r}"


def make_hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def load_curation(path: Path) -> dict:
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------- batches

class Batch:
    """One load run. The batch row is committed FIRST (status 'failed'); all fact
    work runs inside one transaction and is rolled back on error, leaving a
    visible failed-batch record (panel B6.3). On success the row flips to
    'complete'."""

    def __init__(self, conn: sqlite3.Connection, note: str = ""):
        self.conn = conn
        cur = conn.execute(
            "INSERT INTO load_batch(started_at, status, tool_version, note) VALUES (?, 'failed', ?, ?)",
            (now(), TOOL_VERSION, note or None),
        )
        conn.commit()
        self.batch_id = cur.lastrowid

    def __enter__(self):
        self.conn.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute(
                "UPDATE load_batch SET status='complete', finished_at=? WHERE batch_id=?",
                (now(), self.batch_id),
            )
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
            try:
                self.conn.execute(
                    "UPDATE load_batch SET note=COALESCE(note,'')||' | FAILED: '||?, finished_at=? WHERE batch_id=?",
                    (str(exc)[:300], now(), self.batch_id),
                )
                self.conn.commit()
            except Exception:
                pass
        return False


# ---------------------------------------------------------------- curation -> dims

def ensure_dims(conn: sqlite3.Connection, accounts: list[dict], metrics: list[dict]) -> dict[str, int]:
    acct_ids: dict[str, int] = {}
    for a in accounts:
        row = conn.execute("SELECT account_id FROM dim_account WHERE code=?", (a["code"],)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO dim_account(code, institution, registration, entity, purpose, notes) VALUES (?,?,?,?,?,?)",
                (a["code"], a["institution"], a["registration"], a["entity"], a["purpose"], a.get("notes")),
            )
            acct_ids[a["code"]] = cur.lastrowid
        else:
            acct_ids[a["code"]] = row[0]
    metric_ids: dict[str, int] = {}
    for m in metrics:
        row = conn.execute("SELECT metric_id FROM dim_metric WHERE name=?", (m["name"],)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO dim_metric(name, is_flow, is_year_relative, polarity, unit, scope_flag, methodology) VALUES (?,?,?,?,?,?,?)",
                (m["name"], m["is_flow"], m["is_year_relative"], m["polarity"], m["unit"], m.get("scope_flag"), m.get("methodology")),
            )
            metric_ids[m["name"]] = cur.lastrowid
        else:
            metric_ids[m["name"]] = row[0]
    return acct_ids, metric_ids


def ensure_source(conn: sqlite3.Connection, spec: dict) -> int:
    alias = spec["alias"]
    row = conn.execute("SELECT source_id FROM src_ref WHERE alias=?", (alias,)).fetchone()
    if row is not None:
        # curation evolves (precedence, dedupe, recency): keep the registry row in sync
        conn.execute("UPDATE src_ref SET precedence=?, sheet_modified=?, role=?, drive_id=? WHERE source_id=?",
                     (spec.get("precedence", 100), spec.get("sheet_modified"), spec.get("role", "raw"),
                      spec.get("drive_id", ""), row[0]))
        conn.execute("""UPDATE src_tab SET dedupe_rule=?, row_order=?, grain=?, header_state=?, header_row=?
                        WHERE source_id=?""",
                     (spec.get("dedupe_rule", "disjoint_by_key"), spec.get("row_order", "ascending-date"),
                      spec.get("grain"), spec.get("header_state", "confirmed"), spec.get("header_row"),
                      row[0]))
        return row[0]
    cur = conn.execute(
        "INSERT INTO src_ref(alias, drive_id, source_kind, read_path, precedence, role, sheet_modified) VALUES (?,?,?,?,?,?,?)",
        (alias, spec["drive_id"], spec["source_kind"], spec["read_path"],
         spec.get("precedence", 100), spec.get("role", "raw"), spec.get("sheet_modified")),
    )
    source_id = cur.lastrowid
    conn.execute(
        "INSERT INTO src_tab(source_id, tab, role, header_state, header_row, dedupe_rule, row_order, grain, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (source_id, spec["tab"], spec.get("role", "raw"), spec.get("header_state", "confirmed"),
         spec.get("header_row"), spec.get("dedupe_rule", "disjoint_by_key"),
         spec.get("row_order", "ascending-date"), spec.get("grain"), spec.get("notes")),
    )
    return source_id


def ensure_sentinels(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute(
        "INSERT INTO dim_txn_type(source_id, raw_label, canonical) VALUES (?, 'UNMAPPED', 'UNMAPPED') "
        "ON CONFLICT(source_id, raw_label) DO NOTHING",
        (source_id,),
    )
    conn.execute(
        "INSERT INTO dim_category(source_id, source_label, canonical, spending_class) VALUES (?, 'UNMAPPED', 'UNMAPPED', 'unsettled') "
        "ON CONFLICT(source_id, source_label) DO NOTHING",
        (source_id,),
    )


def get_sentinel(conn: sqlite3.Connection, source_id: int, table: str) -> int:
    col = "txn_type_id" if table == "dim_txn_type" else "category_id"
    label_col = "raw_label" if table == "dim_txn_type" else "source_label"
    row = conn.execute(
        f"SELECT {col} FROM {table} WHERE source_id=? AND {label_col}='UNMAPPED'", (source_id,)
    ).fetchone()
    if row is None:
        raise LoadError(f"{table}: UNMAPPED sentinel missing for source {source_id}")
    return row[0]


def supersede_tab(conn: sqlite3.Connection, batch_id: int, source_id: int, tables: list[str]) -> int:
    n = 0
    for t in tables:
        cur = conn.execute(
            f"UPDATE {t} SET superseded_by_batch_id=? WHERE source_id=? AND superseded_by_batch_id IS NULL",
            (batch_id, source_id),
        )
        n += cur.rowcount
    return n


def coverage(conn: sqlite3.Connection, alias: str, tab: str, periods: dict[str, str], note: str = "") -> None:
    """Absence is not zero (M1/finding 17): record what each expected period contained."""
    for period, status in periods.items():
        conn.execute(
            """INSERT INTO coverage_calendar(source_alias, tab, period, expected, status, note)
               VALUES (?,?,?,1,?,?) ON CONFLICT(source_alias, tab, period)
               DO UPDATE SET status=excluded.status, note=excluded.note""",
            (alias, tab, period, status, note),
        )


# ---------------------------------------------------------------- family loaders

def load_state_spine(conn: sqlite3.Connection, batch: Batch, spec: dict, acct_ids, metric_ids) -> int:
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    with open(spec["local"], newline="", encoding="utf-8", errors="replace") as fh:
        for _ in range(spec.get("csv_skip", 0)):
            next(fh, None)
        reader = csv.DictReader(fh)
        header = [norm_label(h) for h in (reader.fieldnames or [])]
        col_map = {c["col"]: c for c in spec["columns"] if c.get("role") != "as_of"}
        n = 0
        n_skipped = 0
        n_sup = 0
        issues: list[str] = []
        seq_buf: dict = {}
        total_col = "Total Assets"
        max_total_delta = 0.0
        derived_cols = [m for m in col_map.values() if m.get("mode") == "derive_from_delta"]
        row_totals: dict[str, tuple[float, float]] = {}  # as_of -> (measured_sum, source_total)
        for rowno, raw in enumerate(reader, start=2):
            date_cell = raw.get("Date") or raw.get(spec["columns"][0]["col"])
            as_of, d_reason = coerce_date(date_cell, fmt=spec.get("date_format"))
            if as_of and spec.get("month_end") and len(as_of) == 7:
                # 'YYYY-MM' -> month-end
                import calendar as _cal
                y, m = map(int, as_of.split("-"))
                as_of = f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"
            if as_of is None:
                issues.append(f"row {rowno}: date {d_reason}")
                continue
            row_sum = 0.0
            for col, mapping in col_map.items():
                if mapping.get("mode") == "derive_from_delta":
                    continue  # handled in the post-pass below
                cell = raw.get(col)
                if cell is None or (isinstance(cell, str) and not cell.strip()):
                    continue
                val, v_reason = coerce_num(cell)
                if val is None:
                    issues.append(f"row {rowno} col {col}: {v_reason}")
                    continue
                if mapping["metric"] == "TOTAL_ASSETS":
                    row_sum += val
                acct = acct_ids[mapping["account"]]
                met = metric_ids[mapping["metric"]]
                grain = mapping.get("grain", "month-end")
                key = (acct, met, as_of)
                seq = seq_buf.get(key, 0) + 1
                seq_buf[key] = seq
                nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
                h = make_hash(acct, met, as_of, seq, val)
                if conn.execute("SELECT 1 FROM fact_state WHERE content_hash=?", (h,)).fetchone():
                    # identical content already current — skip WITHOUT superseding it
                    n_skipped += 1
                    continue
                # replace prior versions of this business key from the SAME source
                for old_row in conn.execute(
                    "SELECT natural_key FROM fact_state WHERE natural_key=? AND batch_id<>? AND superseded_by_batch_id IS NULL",
                    (nk, batch.batch_id)).fetchall():
                    conn.execute("UPDATE fact_state SET superseded_by_batch_id=? WHERE natural_key=?",
                                 (batch.batch_id, old_row[0]))
                    n_sup += 1
                conn.execute(
                    """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
                       sheet_row_number, value_num, presence, period_grain, grain_detail,
                       content_hash, source_id, batch_id, ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (nk, acct, met, as_of, seq, rowno, val, "measured", grain, spec.get("grain"),
                     h, source_id, batch.batch_id, now()),
                )
                n += 1
            src_total, _ = coerce_num(raw.get(total_col))
            if src_total is not None and derived_cols:
                row_totals[as_of] = (row_sum, src_total)
            if src_total is not None and row_sum:
                max_total_delta = max(max_total_delta, abs(src_total - row_sum))
        # Post-pass: closed accounts the owner says were folded into the source's
        # total. The component is DERIVED by difference — stored with
        # presence='estimated' so it is never mistaken for a measurement (D14).
        for mapping in derived_cols:
            acct = acct_ids[mapping["account"]]
            met = metric_ids[mapping["metric"]]
            grain = mapping.get("grain", "month-end")
            for as_of, (measured_sum, src_total) in sorted(row_totals.items()):
                delta = src_total - measured_sum
                if abs(delta) <= 0.01:
                    continue
                seq = seq_buf.get((acct, met, as_of), 0) + 1
                seq_buf[(acct, met, as_of)] = seq
                nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
                h = make_hash(acct, met, as_of, seq, delta)
                conn.execute(
                    """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
                       sheet_row_number, value_num, presence, period_grain, grain_detail,
                       verify_note, content_hash, source_id, batch_id, ingested_at)
                       VALUES (?,?,?,?,?,NULL,?,'estimated',?,?,?,?,?,?,?)""",
                    (nk, acct, met, as_of, seq, delta, grain, spec.get("grain"),
                     mapping.get("note"), h, source_id, batch.batch_id, now()),
                )
                n += 1
        if derived_cols and row_totals:
            issues.append(f"derived: {len(derived_cols)} column(s) reconstructed by difference; presence='estimated'")
        if max_total_delta > 0.01 and not derived_cols:
            issues.append(f"cross-check: max |SUM(accounts) - source Total Assets| = {max_total_delta:.2f}")
        if n_skipped:
            issues.append(f"{n_skipped} rows identical to existing current rows (cross-source agreement) — skipped")
        if n_sup:
            issues.append(f"{n_sup} prior versions superseded")
        if issues:
            note = "; ".join(issues[:8]) + (f" (+{len(issues)-8} more)" if len(issues) > 8 else "")
            conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?", (note, batch.batch_id))
    return n, n_sup


def _prefix_match(desc: str, vocab: dict) -> str | None:
    """Longest-prefix match over the curated vocabulary, SPACE-INSENSITIVE
    (the 2022+ checking dumps concatenate labels: 'ACHDEBIT' = 'ACH DEBIT').
    A '__default__' entry applies when nothing matches (logged assumption)."""
    d = re.sub(r"\s+", "", norm_label(desc).upper())
    best = None
    for prefix in vocab:
        if prefix == "__default__":
            continue
        p = re.sub(r"\s+", "", prefix.upper())
        if d.startswith(p) and (best is None or len(p) > len(best)):
            best = prefix
    if best is not None:
        return vocab[best]
    # stray leading digits in some checking descriptions ('4 Check #113', '7 ACH DEPOSIT')
    if d[:1].isdigit():
        m = re.match(r"\d+", d)
        stripped = d[m.end():] if m else d
        for prefix in vocab:
            if prefix == "__default__":
                continue
            p = re.sub(r"\s+", "", prefix.upper())
            if stripped.startswith(p):
                return vocab[prefix]
    return vocab.get("__default__")


def _token_of(desc: str) -> str:
    return norm_label(desc).split()[0].upper() if norm_label(desc) else "?"


def _header_lookup(fieldnames: list[str], target: str) -> str | None:
    """Tolerant header match: exact first, then suffix — Sheets dumps wrap labels
    with newlines ('Years You\\nYears You Worked' normalizes to a doubled prefix)."""
    norm = {norm_label(f): f for f in fieldnames}
    if target in norm:
        return norm[target]
    for nf, f in norm.items():
        if nf.endswith(target):
            return f
    return None


def load_events_td(conn: sqlite3.Connection, batch: Batch, spec: dict, xlsx_path: Path, acct_ids, vocab: dict) -> int:
    import openpyxl
    alias = spec["alias"].replace("<year>", xlsx_path.stem.rsplit("_", 1)[-1])
    spec = {**spec, "alias": alias, "tab": spec["tab"].replace("<year>", xlsx_path.stem.rsplit("_", 1)[-1])}
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    unmapped_id = get_sentinel(conn, source_id, "dim_txn_type")
    cat_id = get_sentinel(conn, source_id, "dim_category")
    txn_cache: dict[str, int] = {norm_label(k): unmapped_id for k in ()}
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[list(wb.sheetnames)[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return 0
    header = [norm_label(h) if h else f"COL_{i+1}" for i, h in enumerate(rows[0])]
    idx = {h: i for i, h in enumerate(header)}
    sentinel = spec.get("sentinel", "***END OF FILE***")
    n = 0
    issues: list[str] = []
    seq_buf: dict = {}
    acct = acct_ids[spec["account"]]
    for rowno, r in enumerate(rows[1:], start=2):
        if r is None or all(v is None for v in r):
            continue
        if r[0] and norm_label(r[0]).startswith(sentinel.split(" ")[0]):
            break  # sentinel row ends the ledger
        date_cell = r[idx["DATE"]]
        event_date, d_reason = coerce_date(date_cell)
        if event_date is None:
            issues.append(f"row {rowno}: date {d_reason}")
            continue
        desc = norm_label(r[idx["DESCRIPTION"]]) if r[idx["DESCRIPTION"]] else ""
        canonical = _prefix_match(desc, vocab) or "UNMAPPED"
        raw_lbl = desc if desc else "UNMAPPED"
        tid = txn_cache.get(raw_lbl)
        if tid is None:
            row = conn.execute(
                "SELECT txn_type_id, canonical FROM dim_txn_type WHERE source_id=? AND raw_label=?", (source_id, raw_lbl)
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO dim_txn_type(source_id, raw_label, canonical) VALUES (?,?,?)",
                    (source_id, raw_lbl, canonical),
                )
                tid = cur.lastrowid
            else:
                tid = row[0]
                if row[1] != canonical:
                    conn.execute("UPDATE dim_txn_type SET canonical=? WHERE txn_type_id=?", (canonical, tid))
            txn_cache[raw_lbl] = tid
        amt, _ = coerce_num(r[idx["AMOUNT"]])
        qty, _ = coerce_num(r[idx["QUANTITY"]] if idx.get("QUANTITY") is not None else None)
        price, _ = coerce_num(r[idx["PRICE"]] if idx.get("PRICE") is not None else None)
        fee, _ = coerce_num(r[idx["COMMISSION"]] if idx.get("COMMISSION") is not None else None)
        txn_id = None
        if idx.get("TRANSACTION ID") is not None and r[idx["TRANSACTION ID"]] is not None:
            txn_id = str(int(float(r[idx["TRANSACTION ID"]])))
        sec_id = None
        if idx.get("SYMBOL") is not None and r[idx["SYMBOL"]]:
            tick = norm_label(r[idx["SYMBOL"]]).upper()
            srow = conn.execute("SELECT security_id FROM dim_security WHERE ticker=?", (tick,)).fetchone()
            if srow is None:
                cur = conn.execute("INSERT INTO dim_security(ticker) VALUES (?)", (tick,))
                sec_id = cur.lastrowid
            else:
                sec_id = srow[0]
        key = (acct, event_date)
        seq = seq_buf.get(key, 0) + 1
        seq_buf[key] = seq
        nk = f"{source_id}|{acct}|{event_date}|{seq}"
        h = make_hash("event", acct, event_date, amt, re.sub(r"\s+", "", desc).upper(), txn_id)
        conn.execute(
            """INSERT INTO fact_event(natural_key, business_txn_id, account_id, event_date, seq_in_date,
               sheet_row_number, txn_type_id, category_id, raw_label, description,
               amount, quantity, price, fee, unit, security_id, content_hash,
               source_id, batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'USD',?,?,?,?,?)""",
            (nk, txn_id, acct, event_date, seq, rowno, tid, cat_id, desc, desc,
             amt, qty, price, fee, sec_id, h, source_id, batch.batch_id, now()),
        )
        n += 1
    if issues:
        note = "; ".join(issues[:8]) + (f" (+{len(issues)-8} more)" if len(issues) > 8 else "")
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?", (note, batch.batch_id))
    return n


def load_ssa_earnings(conn: sqlite3.Connection, batch: Batch, spec: dict) -> int:
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    col_map = {c["role"]: c["col"] for c in spec["columns"]}
    n = 0
    issues: list[str] = []
    with open(spec["local"], newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {c["role"]: _header_lookup(reader.fieldnames or [], c["col"]) for c in spec["columns"]}
        for rowno, raw in enumerate(reader, start=2):
            wy_cell = raw.get(fields["work_year"])
            try:
                work_year = int(float(wy_cell))
            except (TypeError, ValueError):
                continue
            ss, s_r = coerce_num(raw.get(fields.get("ss_taxed", "")))
            med, m_r = coerce_num(raw.get(fields.get("medicare_taxed", "")))
            if ss is None and med is None:
                if s_r and "placeholder" not in s_r:
                    issues.append(f"row {rowno}: ss_taxed {s_r}")
                continue
            nk = f"{source_id}|{work_year}"
            conn.execute(
                """INSERT INTO ss_earnings_annual(natural_key, work_year, ss_taxed, medicare_taxed,
                   source_id, batch_id, ingested_at) VALUES (?,?,?,?,?,?,?)""",
                (nk, work_year, ss, med, source_id, batch.batch_id, now()),
            )
            n += 1
    if issues:
        note = "; ".join(issues[:8]) + (f" (+{len(issues)-8} more)" if len(issues) > 8 else "")
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?", (note, batch.batch_id))
    return n


def load_ssa_benefits(conn: sqlite3.Connection, batch: Batch, spec: dict) -> int:
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    col_map = {c["role"]: c["col"] for c in spec["columns"]}
    claims = {c["col"]: c["role"].split(":", 1)[1] for c in spec["columns"] if c["role"].startswith("claim:")}
    n = 0
    with open(spec["local"], newline="") as fh:
        reader = csv.DictReader(fh)
        wy_field = _header_lookup(reader.fieldnames or [], col_map["work_year"])
        claim_fields = {c: _header_lookup(reader.fieldnames or [], c) for c in claims}
        for raw in reader:
            wy_cell = raw.get(wy_field)
            try:
                work_year = int(float(wy_cell))
            except (TypeError, ValueError):
                continue
            for col, basis in claims.items():
                cell = raw.get(claim_fields[col])
                amt, reason = coerce_num(cell)
                if amt is None:
                    continue
                nk = f"{source_id}|{work_year}|{basis}"
                conn.execute(
                    """INSERT INTO ss_benefit_estimates(natural_key, work_year, claim_basis, amount, unit,
                       is_estimate, needs_verify, source_id, batch_id, ingested_at)
                       VALUES (?,?,?,?,'monthly',1,?,?,?,?)""",
                    (nk, work_year, basis, amt, 1 if work_year == 2025 else 0, source_id, batch.batch_id, now()),
                )
                n += 1
    return n


# ---------------------------------------------------------------- pipeline

def run_wave1(curation_path: Path, conn: sqlite3.Connection, only: str | None = None) -> dict:
    assert_schema(conn)
    cur = load_curation(curation_path)
    acct_ids, metric_ids = ensure_dims(conn, cur.get("dim_accounts", []), cur.get("dim_metrics", []))
    results = {}
    deferred = cur.get("deferred_sources", [])
    if deferred:
        results["_deferred"] = [{ "alias": s["alias"], "reason": s.get("reason", "deferred") } for s in deferred]
    vocab = cur.get("txn_type_vocab", {}).get("td_txn_by_year:<year>", {})
    vocab_map = vocab.get("map", {})
    for spec in cur["sources"]:
        key = spec["alias"]
        if only and only not in key:
            continue
        family = spec["family"]
        with Batch(conn, note=f"{key}") as batch:
            superseded = 0
            if family == "state":
                source_id = ensure_source(conn, spec)
                ensure_sentinels(conn, source_id)
                n, superseded = load_state_spine(conn, batch, spec, acct_ids, metric_ids)
            elif family == "event":
                import glob as _g
                total = 0
                per_year: dict[str, dict] = {}
                for xp in sorted(_g.glob(spec["local_glob"])):
                    year = Path(xp).stem.rsplit("_", 1)[-1]
                    alias = spec["alias"].replace("<year>", year)
                    source_id = ensure_source(conn, {**spec, "alias": alias})
                    ensure_sentinels(conn, source_id)
                    sup = supersede_tab(conn, batch.batch_id, source_id, ["fact_event"])
                    k = load_events_td(conn, batch, spec, Path(xp), acct_ids, vocab_map)
                    total += k
                    per_year[alias] = {"rows": k, "superseded": sup}
                for alias, v in per_year.items():
                    coverage(conn, alias, spec["tab"].replace("<year>", alias.rsplit(":", 1)[-1]),
                             {alias.rsplit(":", 1)[-1]: ("loaded" if v["rows"] else "loaded-empty")},
                             note="sentinel row excluded; '---' cells -> NULL")
                    results[alias] = v
                n = total
            elif family in ("checking", "card", "card_legacy"):
                import glob as _g
                tmpl = spec["alias"]
                vocab_map = cur.get("txn_type_vocab", {}).get(tmpl, {}).get("map", {})
                cat_classes = cur.get("category_classes", {}).get(tmpl, {})
                total, deduped = 0, 0
                for xp in sorted(_g.glob(spec["local_glob"])):
                    year = Path(xp).stem.rsplit("_", 1)[-1] if Path(xp).suffix == ".csv" else None
                    if Path(xp).suffix.lower() == ".xlsx":
                        import openpyxl as _xl
                        _wb = _xl.load_workbook(xp, read_only=True)
                        _sheets = [s for s in _wb.sheetnames if s.endswith("-Data")] or _wb.sheetnames
                        _wb.close()
                        for sheet in _sheets:
                            year = sheet.rsplit("-", 1)[0] if sheet.endswith("-Data") else sheet
                            alias = tmpl.replace("<year>", year)
                            sub = {**spec, "alias": alias, "tab": sheet,
                                   "sheet": sheet, "year_from_tab": year if spec.get("year_from_tab") else None}
                            source_id = ensure_source(conn, sub)
                            ensure_sentinels(conn, source_id)
                            superseded += supersede_tab(conn, batch.batch_id, source_id, ["fact_event"])
                            k, d = load_events_generic(conn, batch, sub, Path(xp), acct_ids, vocab_map, cat_classes)
                            total += k
                            deduped += d
                            coverage(conn, alias, sheet, {year: ("loaded" if k else "loaded-empty")},
                                     note="summary block excluded" if spec.get("summary_block") else None)
                            results[alias] = {"rows": k, "superseded": 0, "deduped": d}
                    else:
                        alias = tmpl.replace("<year>", year)
                        sub = {**spec, "alias": alias, "tab": year,
                               "year_from_tab": year if spec.get("year_from_tab") else None}
                        source_id = ensure_source(conn, sub)
                        ensure_sentinels(conn, source_id)
                        superseded += supersede_tab(conn, batch.batch_id, source_id, ["fact_event"])
                        k, d = load_events_generic(conn, batch, sub, Path(xp), acct_ids, vocab_map, cat_classes)
                        total += k
                        deduped += d
                        coverage(conn, alias, year, {year: ("loaded" if k else "loaded-empty")},
                                 note="summary block excluded" if spec.get("summary_block") else None)
                        results[alias] = {"rows": k, "superseded": 0, "deduped": d}
                results["_deduped"] = results.get("_deduped", 0) + deduped
                n = total
            elif family == "card_csv":
                import glob as _g
                total = 0
                for xp in sorted(_g.glob(spec["local_glob"])):
                    tag = Path(xp).stem.replace(" ", "_")[:40]
                    alias = spec["alias"].replace("<file>", tag)
                    sub = {**spec, "alias": alias}
                    source_id = ensure_source(conn, sub)
                    ensure_sentinels(conn, source_id)
                    sup = supersede_tab(conn, batch.batch_id, source_id, ["fact_event"])
                    k, _ = load_events_generic(conn, batch, sub, Path(xp), acct_ids,
                                               cur.get("txn_type_vocab", {}).get(spec["alias"], {}).get("map", {}),
                                               cur.get("category_classes", {}).get(spec["alias"], {}))
                    total += k
                    results[alias] = {"rows": k, "superseded": sup}
                n = total
            elif family == "card_statement":
                import glob as _g
                total = 0
                per_file_errors: list[str] = []
                for xp in sorted(_g.glob(spec["local_glob"])):
                    tag = Path(xp).stem.replace(" ", "_")[:40]
                    alias = spec["alias"].replace("<file>", tag)
                    sub = {**spec, "alias": alias}
                    source_id = ensure_source(conn, sub)
                    ensure_sentinels(conn, source_id)
                    try:
                        sup = supersede_tab(conn, batch.batch_id, source_id, ["fact_event"])
                        k = load_card_statement(conn, batch, sub, acct_ids, Path(xp))
                        total += k
                        results[alias] = {"rows": k, "superseded": sup}
                    except Exception as e:
                        per_file_errors.append(f"{Path(xp).name}: {e}")
                        results[alias] = {"rows": 0, "error": str(e)[:80]}
                if per_file_errors:
                    note = "skipped: " + "; ".join(per_file_errors[:6])
                    conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?",
                                 (note, batch.batch_id))
                n = total
            elif family == "statement":
                import glob as _g
                total = 0
                per_file_errors: list[str] = []
                for xp in sorted(_g.glob(spec["local_glob"])):
                    stem = Path(xp).stem
                    if any(ex.lower() in stem.lower() for ex in spec.get("local_exclude", [])):
                        continue
                    tag = stem.replace(" ", "_")[:40]
                    alias = spec["alias"].replace("<file>", tag)
                    sub = {**spec, "alias": alias}
                    source_id = ensure_source(conn, sub)
                    ensure_sentinels(conn, source_id)
                    try:
                        sup = supersede_tab(conn, batch.batch_id, source_id, ["holding_state", "position_lot"])
                        k = load_statement(conn, batch, sub, acct_ids, Path(xp))
                        total += k
                        results[alias] = {"rows": k, "superseded": sup}
                    except Exception as e:
                        per_file_errors.append(f"{Path(xp).name}: {e}")
                        results[alias] = {"rows": 0, "error": str(e)[:80]}
                if per_file_errors:
                    note = "skipped: " + "; ".join(per_file_errors[:6]) + (f" (+{len(per_file_errors)-6})" if len(per_file_errors) > 6 else "")
                    conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?",
                                 (note, batch.batch_id))
                n = total
            elif family == "holdings":
                source_id = ensure_source(conn, spec)
                ensure_sentinels(conn, source_id)
                superseded = supersede_tab(conn, batch.batch_id, source_id, ["holding_state"])
                n = load_holdings(conn, batch, spec, acct_ids)
            elif family == "ssa_earnings":
                source_id = ensure_source(conn, spec)
                ensure_sentinels(conn, source_id)
                superseded = supersede_tab(conn, batch.batch_id, source_id, ["ss_earnings_annual"])
                n = load_ssa_earnings(conn, batch, spec)
                years = {r[0] for r in conn.execute(
                    "SELECT DISTINCT work_year FROM ss_earnings_annual WHERE source_id=? AND superseded_by_batch_id IS NULL", (source_id,))}
                coverage(conn, spec["alias"], spec["tab"],
                         {str(y): ("loaded" if y in years else "absent-in-source") for y in range(1996, 2026)},
                         note="source carries date-shaped junk in the earnings columns for 1996-1998")
            elif family == "ssa_benefit":
                source_id = ensure_source(conn, spec)
                ensure_sentinels(conn, source_id)
                superseded = supersede_tab(conn, batch.batch_id, source_id, ["ss_benefit_estimates"])
                n = load_ssa_benefits(conn, batch, spec)
                years = {r[0] for r in conn.execute(
                    "SELECT DISTINCT work_year FROM ss_benefit_estimates WHERE source_id=? AND superseded_by_batch_id IS NULL", (source_id,))}
                coverage(conn, spec["alias"], spec["tab"],
                         {str(y): ("loaded" if y in years else "absent-in-source") for y in range(1996, 2026)},
                         note="estimate columns populated on 8 of 30 rows")
            else:
                raise LoadError(f"unknown family {family!r} for {key}")
        if family not in ("event", "checking", "card", "card_legacy", "statement", "card_statement", "card_csv"):
            results[key] = {"rows": n, "superseded": superseded}
    return results


# ---------------------------------------------------------------- generic event loader (checking / card)

def _cat_id(conn, source_id, label, classes):
    """Per-source category dim row; canonical = normalized label, spending_class from the
    curated map (default 'unsettled' — classification is a follow-up curation pass)."""
    label = norm_label(label)
    if not label:
        label = "UNMAPPED"
    row = conn.execute("SELECT category_id FROM dim_category WHERE source_id=? AND source_label=?",
                       (source_id, label)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO dim_category(source_id, source_label, canonical, spending_class) VALUES (?,?,?,?)",
            (source_id, label, label, classes.get(label, "unsettled")),
        )
        return cur.lastrowid
    return row[0]


def _dedupe_carry_over(conn, batch, source_id, acct_id, rows_loaded):
    """natural_key_prefer_latest for events: identical-content rows already current from
    ANOTHER source of the same account (adjacent-year Dec-31 carry-overs) are marked
    superseded, with the suppression evidenced in dedupe_log (leg A R2 / B-M1)."""
    n = 0
    for h, nk in rows_loaded:
        for (old_nk, old_src) in conn.execute(
            """SELECT natural_key, source_id FROM fact_event
               WHERE content_hash=? AND account_id=? AND source_id<>?
                 AND superseded_by_batch_id IS NULL""",
            (h, acct_id, source_id),
        ).fetchall():
            conn.execute("UPDATE fact_event SET superseded_by_batch_id=? WHERE natural_key=?",
                         (batch.batch_id, old_nk))
            conn.execute(
                """INSERT INTO dedupe_log(batch_id, rule, source_alias, suppressed_natural_key, kept_natural_key, note, at)
                   VALUES (?,?,?,?,?,?,?)""",
                (batch.batch_id, "natural_key_prefer_latest",
                 conn.execute("SELECT alias FROM src_ref WHERE source_id=?", (old_src,)).fetchone()[0],
                 old_nk, nk, "identical-content carry-over row (adjacent year tabs)", now()),
            )
            n += 1
    return n


def load_events_generic(conn, batch, spec, path, acct_ids, vocab, category_classes) -> tuple[int, int]:
    """Column-map-driven event loader for checking/card families."""
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    cat_sentinel = get_sentinel(conn, source_id, "dim_category")
    unmapped_id = get_sentinel(conn, source_id, "dim_txn_type")
    amount_mode = spec.get("amount_mode", "signed")
    expected_year = spec.get("year_from_tab")
    stop_on_summary = spec.get("summary_block", False)
    rows_loaded: list[tuple[str, str]] = []
    txn_cache: dict[str, int] = {}
    issues: list[str] = []
    seq_buf: dict = {}
    n = 0
    acct = acct_ids[spec["account"]]

    def emit(event_date, rowno, desc, type_lbl, cat_lbl, amount, qty=None):
        nonlocal n
        matched = (_prefix_match(desc, vocab)
                   or (_prefix_match(type_lbl, vocab) if type_lbl else None)
                   or "UNMAPPED")
        canonical = matched.get("canonical", matched) if isinstance(matched, dict) else matched
        informational = matched.get("informational", 0) if isinstance(matched, dict) else 0
        raw_lbl = (norm_label(type_lbl) or desc or "UNMAPPED") if spec.get("label_is_type") else (desc if desc else (norm_label(type_lbl) if type_lbl else "UNMAPPED"))
        tid = txn_cache.get(raw_lbl)
        if tid is None:
            row = conn.execute("SELECT txn_type_id, canonical FROM dim_txn_type WHERE source_id=? AND raw_label=?",
                               (source_id, raw_lbl)).fetchone()
            if row is None:
                cur = conn.execute("INSERT INTO dim_txn_type(source_id, raw_label, canonical, is_informational) VALUES (?,?,?,?)",
                                   (source_id, raw_lbl, canonical, informational))
                tid = cur.lastrowid
            else:
                tid = row[0]
                if row[1] != canonical:
                    # curation evolved (UNMAPPED -> mapped): correct the vocabulary row
                    conn.execute("UPDATE dim_txn_type SET canonical=?, is_informational=? WHERE txn_type_id=?",
                                 (canonical, informational, tid))
            txn_cache[raw_lbl] = tid
        cid = _cat_id(conn, source_id, cat_lbl, category_classes) if cat_lbl else cat_sentinel
        key = (acct, event_date)
        seq = seq_buf.get(key, 0) + 1
        seq_buf[key] = seq
        nk = f"{source_id}|{acct}|{event_date}|{seq}"
        h = make_hash("event", acct, event_date, amount, re.sub(r"\s+", "", desc).upper(), type_lbl)   # content hash: source/seq-free, label space-normalized
        conn.execute(
            """INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, sheet_row_number,
               txn_type_id, category_id, raw_label, description, amount, quantity, unit, content_hash,
               source_id, batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'USD',?,?,?,?)""",
            (nk, acct, event_date, seq, rowno, tid, cid, raw_lbl, desc, amount, qty, h,
             source_id, batch.batch_id, now()),
        )
        rows_loaded.append((h, nk))
        n += 1

    if path.suffix.lower() == ".csv":
        with open(path, newline="") as fh:
            reader = csv.reader(fh)
            header = [norm_label(h) for h in next(reader, [])]
            # POSITIONAL access: DictReader silently drops duplicate/empty header cells
            # (the 2022-2025 checking tabs ship a blank first header cell AND repeated
            # empty trailing cells — under DictReader the date column gets overwritten).
            idx: dict[str, int | None] = {}
            for c in spec["columns"]:
                pos = None
                if c["col"] in header:
                    pos = header.index(c["col"])
                elif c["role"] == "event_date":
                    pos = 0  # unlabeled date column fallback
                idx[c["role"]] = pos
            data_started = False
            for rowno, raw in enumerate(reader, start=2):
                def cell(role):
                    i = idx.get(role)
                    return raw[i] if (i is not None and i < len(raw) and raw[i] is not None) else None
                date_cell = cell("event_date")
                event_date, d_reason = coerce_date(date_cell)
                if event_date is None:
                    if data_started and stop_on_summary and (cell("raw_label_and_description") or cell("category_label")):
                        break  # per-category summary block reached
                    if date_cell and str(date_cell).strip():
                        issues.append(f"row {rowno}: date {d_reason}")
                    continue
                data_started = True
                if expected_year and event_date[:4] != expected_year:
                    issues.append(f"row {rowno}: cell year {event_date[:4]} != tab year {expected_year}")
                desc = norm_label(cell("raw_label_and_description")) if cell("raw_label_and_description") else ""
                cat_lbl = norm_label(cell("category_label")) if cell("category_label") else ""
                type_lbl = norm_label(cell("type_label")) if cell("type_label") else ""
                amount = None
                if amount_mode == "credit_minus_debit":
                    cr, _ = coerce_num(cell("credit"))
                    db, _ = coerce_num(cell("debit"))
                    amount = (cr or 0.0) - (db or 0.0)
                elif amount_mode == "credit_minus_spending":
                    cr, _ = coerce_num(cell("credit"))
                    sp, _ = coerce_num(cell("spending"))
                    amount = (cr or 0.0) - (sp or 0.0)
                else:
                    amount, a_reason = coerce_num(cell("amount"))
                    if amount is None:
                        issues.append(f"row {rowno}: amount {a_reason}")
                        continue
                emit(event_date, rowno, desc, type_lbl, cat_lbl, amount)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = spec.get("sheet") or wb.sheetnames[0]
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return 0, 0
        hdr_row = spec.get("header_row", 1)
        if hdr_row > len(rows):
            return 0, 0
        header = [norm_label(h) if h else f"COL_{i+1}" for i, h in enumerate(rows[hdr_row - 1])]
        idx = {c["role"]: header.index(c["col"]) if c["col"] in header else None for c in spec["columns"]}
        for rowno, r in enumerate(rows[hdr_row:], start=hdr_row + 1):
            if idx["event_date"] is None or r[idx["event_date"]] is None:
                continue
            event_date, d_reason = coerce_date(r[idx["event_date"]])
            if event_date is None:
                issues.append(f"row {rowno}: date {d_reason}")
                continue
            def g(role):
                i = idx.get(role)
                return norm_label(r[i]) if (i is not None and r[i] is not None) else ""
            desc, cat_lbl, type_lbl = g("raw_label_and_description"), g("category_label"), g("type_label")
            qty, _ = coerce_num(r[idx["quantity"]] if idx.get("quantity") is not None and r[idx["quantity"]] is not None else None)
            amount = None
            if amount_mode == "credit_minus_debit":
                cr, _ = coerce_num(r[idx["credit"]] if idx.get("credit") is not None else None)
                db, _ = coerce_num(r[idx["debit"]] if idx.get("debit") is not None else None)
                amount = (cr or 0.0) - (db or 0.0)
            elif amount_mode == "credit_minus_spending":
                cr, _ = coerce_num(r[idx["credit"]] if idx.get("credit") is not None else None)
                sp, _ = coerce_num(r[idx["spending"]] if idx.get("spending") is not None else None)
                amount = (cr or 0.0) - (sp or 0.0)
            else:
                amount, a_reason = coerce_num(r[idx["amount"]] if idx.get("amount") is not None else None)
                if amount is None:
                    issues.append(f"row {rowno}: amount {a_reason}")
                    continue
            emit(event_date, rowno, desc, type_lbl, cat_lbl, amount, qty)

    deduped = _dedupe_carry_over(conn, batch, source_id, acct, rows_loaded) if spec.get("dedupe_rule") == "natural_key_prefer_latest" else 0
    if issues:
        note = "; ".join(issues[:8]) + (f" (+{len(issues)-8} more)" if len(issues) > 8 else "")
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?", (note, batch.batch_id))
    return n, deduped


# ---------------------------------------------------------------- holdings loader (wave-2)

ACCOUNT_TOKENS = {"TD": "TD_RO", "FD-RO": "RO_IRA", "ML": "BAML"}


def load_holdings(conn, batch, spec, acct_ids) -> int:
    """Parse a Trading-Performance Data tab: the POSITIONS block only.

    Structure: ticker rows ('NYSE:B', name, ...) followed by per-account rows
    (account token in col D, price/shares/cost/mv in cols F-I), then a
    'Sub Total' row. Everything else is skipped: dividend-ladder columns,
    INDEX rows (col A startswith 'INDEX'), the watchlist block (ticker + price
    in col C, no account column), annotation rows ('New Cost...', 'ATH'), and
    CUSIP/'Invalid Symbol' junk rows.
    """
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    n = 0
    issues: list[str] = []
    cur_ticker = cur_name = cur_exchange = None
    with open(spec["local"], newline="") as fh:
        for rowno, r in enumerate(csv.reader(fh), start=1):
            a = r[0].strip() if len(r) > 0 and r[0] else ""
            if a.startswith("INDEX") or a.upper() in ("TIP", "TLT", "NEAR", "MCHI", "BABA", "BMY", "C") and len(r) > 3 and not (r[3] or "").strip():
                cur_ticker = None
                continue
            if a and not a.startswith("Sub Total"):
                # ticker row: exchange:ticker prefix. NOTE the source puts the
                # FIRST account's numbers on the ticker row itself — fall
                # through and emit it like any account row.
                if ":" in a:
                    ex, tk = a.split(":", 1)
                    cur_exchange, cur_ticker = ex, tk
                else:
                    cur_ticker, cur_exchange = a, None
                cur_name = (r[1] or "").strip() if len(r) > 1 else ""
            acct_token = (r[3] or "").strip() if len(r) > 3 else ""
            if acct_token not in ACCOUNT_TOKENS or cur_ticker is None:
                continue
            shares, s_r = coerce_num(r[6] if len(r) > 6 else None)
            if shares is None or shares <= 0:
                continue
            cost, _ = coerce_num(r[7] if len(r) > 7 else None)
            mv, _ = coerce_num(r[8] if len(r) > 8 else None)
            price, _ = coerce_num(r[5] if len(r) > 5 else None)
            if mv is None and price is not None:
                mv = shares * price  # derived, but the source's own convention
            acct = acct_ids[ACCOUNT_TOKENS[acct_token]]
            srow = conn.execute("SELECT security_id FROM dim_security WHERE ticker=?", (cur_ticker,)).fetchone()
            if srow is None:
                cur2 = conn.execute("INSERT INTO dim_security(ticker, exchange, name) VALUES (?,?,?)",
                                    (cur_ticker, cur_exchange, cur_name))
                sec_id = cur2.lastrowid
            else:
                sec_id = srow[0]
            as_of = spec.get("as_of")
            nk = f"{source_id}|{acct}|{sec_id}|{as_of}"
            conn.execute(
                """INSERT INTO holding_state(natural_key, account_id, security_id, as_of, shares,
                   cost_basis, market_value, price, source_id, batch_id, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (nk, acct, sec_id, as_of, shares, cost, mv, price, source_id, batch.batch_id, now()),
            )
            n += 1
    if issues:
        note = "; ".join(issues[:8])
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?", (note, batch.batch_id))
    return n


# ---------------------------------------------------------------- statement loader (wave-2 tail)
import re as _re

def _parse_statement_positions(path: Path, account: str) -> tuple[str | None, list[dict]]:
    """Parse a Schwab/TD brokerage statement PDF into per-security position rows.

    Returns (as_of, positions) where each position is
    {ticker, name, quantity, price, market_value, cost_basis, section}.
    Unpriced securities carry cost_basis only. NOTHING is guessed: rows that
    don't fit the symbol+numbers pattern are skipped and counted as issues.
    """
    import fitz  # pymupdf
    doc = fitz.open(str(path))
    page_texts = [p.get_text() for p in doc]
    text = "\n".join(page_texts)
    doc.close()
    # statement period, page-scoped. Two layout eras:
    #   Schwab: 'Statement Period\nJune 1-30, 2024'
    #   TD:     'Statement Reporting Period:\n 12/01/16 - 12/31/16'
    as_of = None
    is_td = "Statement Reporting Period" in text
    for pt in page_texts:
        if is_td:
            m = _re.search(r"Statement Reporting Period:\s*\n\s*\d{1,2}/\d{1,2}/\d{2}\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{2})", pt)
            if m:
                from datetime import datetime as _dt
                try:
                    end = _dt.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%m/%d/%y")
                    as_of = end.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        else:
            if "Positions" not in pt or "Statement Period" not in pt:
                continue
            m = _re.search(r"Statement Period\s*\n\s*(?:[A-Za-z]+ \d{1,2}[-–])?([A-Za-z]+) \d{1,2}[-–](\d{1,2}), (\d{4})", pt)
            if m:
                try:
                    from datetime import datetime as _dt
                    end = _dt.strptime(f"{m.group(1)} {m.group(2)}, {m.group(3)}", "%B %d, %Y")
                    as_of = end.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
    positions: list[dict] = []
    section = None
    for part in text.split("Total "):
        sm = _re.search(r"Positions - ([A-Za-z ]+)", part)
        if sm:
            section = sm.group(1).strip()
        # priced rows: symbol, desc lines, qty, price, mv, cost
        for mm in _re.finditer(
            r"\n([A-Z][A-Z0-9.\-]{0,9})\s*\n((?:[^\n]+\n){1,6}?)\s*"
            r"([\d,]+\.\d+)\s*\n\s*([\d,]+\.\d+)\s*\n\s*([\d,]+\.\d+)\s*\n\s*([\d,]+\.\d+)",
            part):
            sym, desc, qty, price, mv, cost = mm.group(1), mm.group(2).strip().split("\n")[0], \
                float(mm.group(3).replace(",", "")), float(mm.group(4).replace(",", "")), \
                float(mm.group(5).replace(",", "")), float(mm.group(6).replace(",", ""))
            if sym.startswith("INDEX") or sym in ("CASH", "F") or (qty == 0 and mv == 0 and cost == 0):
                continue
            positions.append({"ticker": sym, "name": desc[:60], "quantity": qty, "price": price,
                              "market_value": mv, "cost_basis": cost, "section": section})
        # unpriced ADR blocks (frozen/sanctioned): NAME block, F marker,
        # qty, cost, N/A — ticker = first word of the name (source lists names)
        for mm in _re.finditer(
            r"\n([A-Z][A-Z0-9.\- ]{2,30}?)\s*\n(?:F\s*\n)?(?:SPONSORED|UNSPONSORED)[^\n]*\n"
            r"(?:1 ADR REPS[^\n]*\n(?:[^\n]+\n)?)?([\d,]+\.\d+)\s*\n\s*([\d,]+\.\d+)\s*\n\s*(?:N/A|n/a|—)",
            part):
            name, qty, cost = mm.group(1).strip(), \
                float(mm.group(2).replace(",", "")), float(mm.group(3).replace(",", ""))
            sym = name.split()[0]  # e.g. 'GAZPROM PJSC' -> 'GAZPROM'
            positions.append({"ticker": sym, "name": name[:60], "quantity": qty, "price": None,
                              "market_value": None, "cost_basis": cost, "section": section})
    if is_td:
        positions = []
        for mm in _re.finditer(
            r"\n([A-Z][A-Z0-9.\-]{0,9})\s*\n"           # symbol (ABX, GOLD, ...)
            r"([\d,]+\.?\d*)\s*\n"                       # quantity
            r"([\d,]+\.\d+)\s*\n"                        # current price
            r"([\d,]+\.\d+)\s*\n"                        # market value
            r"(\d{1,2}/\d{1,2}/\d{2})\s*\n"              # purchase date
            r"([\d,]+\.\d+)\s*\n"                        # cost basis
            r"([\d,]+\.\d+)",                              # average cost
            text):
            sym = mm.group(1)
            if sym in ("CASH", "YTD", "COM", "F"):
                continue
            positions.append({
                "ticker": sym, "name": sym, "quantity": float(mm.group(2).replace(",", "")),
                "price": float(mm.group(3).replace(",", "")), "market_value": float(mm.group(4).replace(",", "")),
                "cost_basis": float(mm.group(6).replace(",", "")),
                "purchase_date": mm.group(5), "section": "td-positions",
            })
    # account hint from the statement text (routing for the mixed folders)
    account_hint = None
    if "Schwab One" in text or "Statement for Account #" in text:
        account_hint = "TD_RO"
    elif "Rollover" in text:
        account_hint = "RO_IRA"
    elif _re.search(r"401\s*\(?\s*[kK]\)?", text) or "Plan Account" in text:
        account_hint = "FD_VZW_401K"
    return as_of, positions, account_hint


def load_statement(conn, batch, spec, acct_ids, path: Path) -> int:
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    as_of, positions, account_hint = _parse_statement_positions(path, spec["account"])
    if as_of is None:
        raise LoadError(f"{path.name}: no statement period found — refusing to guess")
    acct = acct_ids[account_hint or spec["account"]]
    n = 0
    for p in positions:
        srow = conn.execute("SELECT security_id FROM dim_security WHERE ticker=?", (p["ticker"],)).fetchone()
        if srow is None:
            cur = conn.execute("INSERT INTO dim_security(ticker, name) VALUES (?,?)", (p["ticker"], p["name"]))
            sec_id = cur.lastrowid
        else:
            sec_id = srow[0]
        nk = f"{source_id}|{acct}|{sec_id}|{as_of}"
        opened = None
        if p.get("purchase_date"):
            try:
                from datetime import datetime as _dt
                opened = _dt.strptime(p["purchase_date"], "%m/%d/%y").strftime("%Y-%m-%d")
            except ValueError:
                opened = None
        conn.execute(
            """INSERT INTO holding_state(natural_key, account_id, security_id, as_of, shares,
               cost_basis, market_value, price, purchase_date, source_id, batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nk, acct, sec_id, as_of, p["quantity"], p["cost_basis"], p["market_value"],
             p["price"], opened, source_id, batch.batch_id, now()),
        )
        n += 1
    return n


# ---------------------------------------------------------------- USBANK card statement loader

USB_CREDIT_MARKERS = ("CREDIT", "PAYMENT", "REFUND", "REBATE", "REVERSAL")


def _parse_usbank(path: Path) -> tuple[str | None, list[dict]]:
    import fitz
    doc = fitz.open(str(path))
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    m = _re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–]\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    as_of = None
    if m:
        from datetime import datetime as _dt
        try:
            as_of = _dt.strptime(m.group(2), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            as_of = None
    txns = []
    for mm in _re.finditer(
        r"\n(\d{2}/\d{2})\s*\n\s*(\d{2}/\d{2})\s*\n"
        r"((?:[^\n]+\n){1,3}?)\s*\$([\d,]+\.\d{2})",
        text):
        post, tdate, desc_lines, amt = mm.group(1), mm.group(2), mm.group(3), float(mm.group(4).replace(",", ""))
        desc = desc_lines.strip().split("\n")
        notation = ""
        for d in desc:
            du = d.strip().upper()
            if du in ("CREDIT ADJUSTMENT", "PAYMENT", "PURCHASE", "FINANCE CHARGE", "ANNUAL FEE",
                      "REVERSAL", "REFUND", "REBATE") or du.startswith("PAYMENT"):
                notation = d.strip()
                desc = [x for x in desc if x.strip().upper() != du]
        txns.append({
            "event_date": post,
            "description": " ".join(desc).strip()[:100],
            "notation": notation,
            "amount": amt,
        })
    # fix dates: post dates are mm/dd of the statement year
    out = []
    for t in txns:
        mm_dd = t["event_date"].replace("/", "-")
        if as_of:
            yr = as_of[:4]
            iso = f"{yr}-{mm_dd}"
            # December statements: 01/xx dates belong to the next year
            if as_of[5:7] == "12" and mm_dd.startswith("01"):
                iso = f"{int(yr)+1}-{mm_dd}"
            out.append({**t, "event_date": iso})
    return as_of, out


def load_card_statement(conn, batch, spec, acct_ids, path: Path) -> int:
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    unmapped_id = get_sentinel(conn, source_id, "dim_txn_type")
    cat_id = get_sentinel(conn, source_id, "dim_category")
    as_of, txns = _parse_usbank(path)
    if as_of is None:
        raise LoadError(f"{path.name}: no statement period found — refusing to guess")
    acct = acct_ids[spec["account"]]
    n = 0
    txn_cache: dict[str, int] = {}
    for t in txns:
        notation = t["notation"].upper()
        is_credit = any(m in notation for m in USB_CREDIT_MARKERS)
        signed = t["amount"] if is_credit else -t["amount"]
        canonical = "PAYMENT" if "PAYMENT" in notation else ("OTHER" if "CREDIT" in notation or "REFUND" in notation else "PURCHASE")
        raw_lbl = notation or "PURCHASE"
        tid = txn_cache.get(raw_lbl)
        if tid is None:
            row = conn.execute("SELECT txn_type_id FROM dim_txn_type WHERE source_id=? AND raw_label=?",
                               (source_id, raw_lbl)).fetchone()
            if row is None:
                cur = conn.execute("INSERT INTO dim_txn_type(source_id, raw_label, canonical) VALUES (?,?,?)",
                                   (source_id, raw_lbl, canonical))
                tid = cur.lastrowid
            else:
                tid = row[0]
            txn_cache[raw_lbl] = tid
        nk = f"{source_id}|{acct}|{t['event_date']}|{n+1}"
        conn.execute(
            """INSERT INTO fact_event(natural_key, account_id, event_date, seq_in_date, txn_type_id,
               category_id, raw_label, description, amount, unit, content_hash,
               source_id, batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,'USD',?,?,?,?)""",
            (nk, acct, t["event_date"], n + 1, tid, cat_id, t["description"], t["description"],
             signed, make_hash("event", acct, t["event_date"], signed, t["description"]),
             source_id, batch.batch_id, now()),
        )
        n += 1
    return n
