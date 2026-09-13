"""books.db v0.2.1 loader — the ratified contract as code (blueprint §3).

Implements: batch identity + atomicity · source-scoped natural keys ·
supersede-then-insert (whole-tab scope) · per-source dedupe rules ·
content_hash recipe H(account|metric|as_of|ordinal|value|presence|origin) for state
(v0.2.5: presence+origin joined the recipe — see state_content_hash) ·
row_order-aware seq derivation · strict date roundtrip · UNMAPPED sentinels ·
schema-version + foreign_keys assertion on connect · legal (origin, presence)
pair enforcement (blueprint v0.3 §4; SQL composite CHECK sees only row-grain
values, origin's column-grain default lives on src_column, so the loader asserts).

Blank semantics (DM-2026-01): a blank cell inside an existing live row means 0
(presence='zero_from_blank') unless the column DECLARES
blank_means='not_applicable' in the allow-list — then no row is written. The
loader prints a per-column zero report at load, emits coverage_calendar
expectations for the tabs it loads structurally, and fails loudly (report line
+ non-zero exit at the CLI) when an EXPECTED anchor period of a not_applicable
column is blank: a missing observation is never silently skipped as N/A.

Series start (DM-2026-01 owner confirmation): a column MAY also DECLARE
`series_start` ('YYYY-MM') in the allow-list — the layout statement of where a
column's series begins ("the layout declares where the series begins", the
ratified precedent for the Tax Rates rows). Before its start a column
contributes nothing: a blank there is not a stated zero and not a missing
observation, and the anchored-blank guard does not expect an anchor before the
start. It resolves the three 1996-1998 `Total IRS Income` findings without a
per-column coverage table: those years are folded into the first stated point
and are genuinely N/A. At or after the start the guard is unchanged — a blank
anchor still fails the load loudly.

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

SCHEMA_VERSION = "v0.2.5"
TOOL_VERSION = "loader21.py"

# ---------------------------------------------------------------- §4 semantics contract
PRESENCE_VALUES = ("measured", "estimated", "zero_from_blank", "error")
ORIGIN_VALUES = ("entered", "copy", "constant_formula", "derived", "external", "key")
# Legal (origin, presence) row pairs — blueprint v0.3 §4, the mirror of the composite
# CHECKs in books.sql (ck_*_origin_presence). `key` has no pair: a key column is row
# addressing, never a fact row. (external,'error') is absent: §4 maps errored
# formulas to origin='derived'. Books.sql cannot enforce the COLUMN-grain default
# (src_column.origin) against the ROW-grain presence, so the loader asserts too.
LEGAL_ORIGIN_PRESENCE_PAIRS = frozenset({
    ("entered", "measured"), ("entered", "zero_from_blank"),
    ("constant_formula", "measured"),
    ("copy", "measured"), ("copy", "zero_from_blank"), ("copy", "estimated"), ("copy", "error"),
    ("derived", "estimated"), ("derived", "error"),
    # external_links membership OVERRIDES kind (blueprint v0.3 §4 precedence): a
    # declared-external column carries measured literals, estimated results, and
    # errors from a failed cross-sheet pull. Restricting external to 'estimated'
    # made the Taxes E/H case (literal values in an external column) unstorable.
    ("external", "measured"), ("external", "estimated"), ("external", "error"),
})


def legal_pair(origin, presence) -> bool:
    """Pure predicate, unit-testable: may a row carrying `origin` also carry
    `presence`? NULL on either side means 'not asserted at write time' and passes —
    the same guard the SQL composite CHECK carries."""
    if origin is None or presence is None:
        return True
    return (origin, presence) in LEGAL_ORIGIN_PRESENCE_PAIRS


def require_legal_pair(origin, presence, where: str) -> None:
    """Load-time assertion of §4's legal pairs; raises instead of inserting."""
    if not legal_pair(origin, presence):
        raise LoadError(
            f"illegal (origin, presence) pair ({origin!r}, {presence!r}) at {where}; "
            f"legal pairs are {sorted(LEGAL_ORIGIN_PRESENCE_PAIRS)} (blueprint v0.3 §4)"
        )


class LoadError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assert_schema(conn: sqlite3.Connection) -> None:
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if not fk:
        raise LoadError("PRAGMA foreign_keys is OFF on this connection — refusing to load")
    row = conn.execute("SELECT value FROM _schema_meta WHERE key='schema_version'").fetchone()
    # row-factory agnostic: tuple rows and sqlite3.Row both compare by value here
    found = None if row is None else row[0]
    if found != SCHEMA_VERSION:
        raise LoadError(f"store schema is {found!r}, expected {SCHEMA_VERSION} — apply tools/schema/books.sql to a fresh store")


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


def state_content_hash(account_id, metric_id, as_of, seq, value, presence, origin) -> str:
    """The v0.2.5 state recipe: H(account|metric|as_of|ordinal|value|presence|origin).

    CONTRACT CHANGE (blueprint v0.3 §5): presence and origin are now INSIDE the hash.
    Under v0.2.4 a measured `0` and a `zero_from_blank` `0` hashed IDENTICALLY — the
    dedupe probe below found the existing row and the reclassified row was SILENTLY
    DEDUPED. Including them in the recipe is what makes the two zeros distinguishable
    in the store, not just in comments. NULL presence/origin stringify as 'None' —
    stable and distinct from every concrete value."""
    return make_hash(account_id, metric_id, as_of, seq, value, presence, origin)


def column_origin(conn: sqlite3.Connection, source_id: int, tab: str, header_text: str) -> str | None:
    """Column-grain origin default from src_column (§2: derivation lives on the
    column, not the row). Nothing has ever written src_column, so today this reads
    as 'no curated default'; the P1+ structural loaders will populate it."""
    row = conn.execute(
        """SELECT c.origin FROM src_column c
             JOIN src_tab t ON t.tab_id = c.tab_id
            WHERE t.source_id = ? AND t.tab = ? AND c.header_text = ? AND c.origin IS NOT NULL
            ORDER BY c.map_id LIMIT 1""",
        (source_id, tab, header_text),
    ).fetchone()
    return None if row is None else row[0]


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
        # v0.3 §7: a quarantined spec must leave a VISIBLE partial batch, not a
        # silently-thinner complete one. load_structural_spec sets this on the
        # quarantine path; __exit__ then records 'partial' instead of 'complete'.
        self.partial = False
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
                "UPDATE load_batch SET status=?, finished_at=? WHERE batch_id=?",
                ("partial" if self.partial else "complete", now(), self.batch_id),
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
                # v0.2.5 §4 row semantics. The CSV path only ever sees coerced
                # literals (blank cells are skipped before this point, so
                # zero_from_blank cannot arise here — it needs the P1 artifact
                # rectangle). origin resolution: classified cell (curation `origin`)
                # > column-grain src_column.origin default > 'entered' (a literal).
                presence = "measured"
                origin = mapping.get("origin") or column_origin(conn, source_id, spec["tab"], col) or "entered"
                # Legal-pair assertion: the SQL composite CHECK can only see row-grain
                # values; origin's default lives on src_column, so enforce the §4 rule
                # here too and fail loudly rather than insert an unmapped state.
                require_legal_pair(origin, presence, f"row {rowno} col {col!r}")
                key = (acct, met, as_of)
                seq = seq_buf.get(key, 0) + 1
                seq_buf[key] = seq
                nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
                h = state_content_hash(acct, met, as_of, seq, val, presence, origin)
                if conn.execute("SELECT 1 FROM fact_state WHERE content_hash=?", (h,)).fetchone():
                    # identical content already current — skip WITHOUT superseding it.
                    # v0.2.5: 'identical' now includes presence+origin (they are in the
                    # hash), so a reclassification is never silently deduped again.
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
                       sheet_row_number, value_num, presence, origin, period_grain, grain_detail,
                       content_hash, source_id, batch_id, ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (nk, acct, met, as_of, seq, rowno, val, presence, origin, grain, spec.get("grain"),
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
            # a reconstructed-by-difference value is a derivation, never a measurement
            d_presence, d_origin = "estimated", "derived"
            require_legal_pair(d_origin, d_presence, f"derived column {mapping['col']!r}")
            for as_of, (measured_sum, src_total) in sorted(row_totals.items()):
                delta = src_total - measured_sum
                if abs(delta) <= 0.01:
                    continue
                seq = seq_buf.get((acct, met, as_of), 0) + 1
                seq_buf[(acct, met, as_of)] = seq
                nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
                h = state_content_hash(acct, met, as_of, seq, delta, d_presence, d_origin)
                conn.execute(
                    """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
                       sheet_row_number, value_num, presence, origin, period_grain, grain_detail,
                       verify_note, content_hash, source_id, batch_id, ingested_at)
                       VALUES (?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?)""",
                    (nk, acct, met, as_of, seq, delta, d_presence, d_origin, grain, spec.get("grain"),
                     mapping.get("note"), h, source_id, batch.batch_id, now()),
                )
                n += 1
        if derived_cols and row_totals:
            issues.append(f"derived: {len(derived_cols)} column(s) reconstructed by difference; presence='estimated', origin='derived'")
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

def run_wave1(curation_path: Path, conn: sqlite3.Connection, only: str | None = None,
              structural: bool = False) -> dict:
    """Run the wave-1 curation.

    structural=False -> the legacy path (values-only CSV/xlsx per spec).
    structural=True  -> the P2 structural reader: only specs that declare an
    `artifact` are loaded; every other spec is skipped and LISTED, never
    silently routed back to the CSV path (that would defeat the point).
    """
    assert_schema(conn)
    cur = load_curation(curation_path)
    if structural:
        specs = [s for s in cur["sources"] if s.get("artifact")
                 and (not only or only in s["alias"])]
        want_accts = {c["account"] for s in specs for c in s.get("columns", []) if c.get("account")}
        want_metrics = {c["metric"] for s in specs for c in s.get("columns", []) if c.get("metric")}
        accounts = [a for a in cur.get("dim_accounts", []) if a["code"] in want_accts]
        metrics = [m for m in cur.get("dim_metrics", []) if m["name"] in want_metrics]
    else:
        accounts, metrics = cur.get("dim_accounts", []), cur.get("dim_metrics", [])
    acct_ids, metric_ids = ensure_dims(conn, accounts, metrics)
    allow = load_allow_list() if structural else None
    results = {}
    if structural:
        results["_skipped_no_artifact"] = [
            s["alias"] for s in cur["sources"] if not s.get("artifact")
            and (not only or only in s["alias"])]
    deferred = cur.get("deferred_sources", [])
    if deferred:
        results["_deferred"] = [{ "alias": s["alias"], "reason": s.get("reason", "deferred") } for s in deferred]
    vocab = cur.get("txn_type_vocab", {}).get("td_txn_by_year:<year>", {})
    vocab_map = vocab.get("map", {})
    for spec in cur["sources"]:
        key = spec["alias"]
        if only and only not in key:
            continue
        if structural and not spec.get("artifact"):
            continue
        family = spec["family"]
        with Batch(conn, note=f"{key}") as batch:
            if structural:
                results[key] = load_structural_spec(conn, batch, spec, allow, acct_ids, metric_ids)
                continue
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


def _words_by_row(words: list) -> list[list]:
    """Cluster word tuples (x0,y0,x1,y1,text) into visual rows by baseline."""
    rows: dict[int, list] = {}
    for w in words:
        rows.setdefault(round(w[1] / 3) * 3, []).append(w)
    return [sorted(v, key=lambda w: w[0]) for _, v in sorted(rows.items())]


def _parse_chase(path: Path) -> tuple[str | None, list[dict]]:
    """Chase Amazon card statement (account suffix redacted). 3-column activity table:
    Date (MM/DD, no year) | Description | signed $ Amount (unsigned=purchase,
    leading '-'=payment/credit). Section bands ('PAYMENTS AND OTHER CREDITS',
    'PURCHASE') are standalone rows. 'Order Number' sublines carry no
    date/amount and are skipped. as_of = statement date from the filename."""
    import fitz
    m = _re.match(r"(\d{4})(\d{2})(\d{2})-statements", path.name)
    if not m:
        return None, []
    yr, mo = int(m.group(1)), int(m.group(2))
    as_of = f"{yr:04d}-{mo:02d}-{int(m.group(3)):02d}"
    doc = fitz.open(str(path))
    txns = []
    for page in doc:
        for row in _words_by_row(page.get_text("words")):
            if len(row) < 2:
                continue
            texts = [w[4] for w in row]
            joined = " ".join(texts)
            if joined in ("PAYMENTS AND OTHER CREDITS", "PURCHASE",
                          "ACCOUNT ACTIVITY", "ACCOUNT ACTIVITY (CONTINUED)",
                          "SHOP WITH POINTS ACTIVITY", "Split Transaction"):
                continue
            date_w = next((w for w in row if w[0] < 80 and _re.fullmatch(r"\d{2}/\d{2}", w[4])), None)
            amt_w = next((w for w in reversed(row)
                          if _re.fullmatch(r"-?\$?[\d,]+\.\d{2}", w[4]) and w[2] > 430), None)
            if date_w is None or amt_w is None:
                continue  # header, Order-Number subline, page furniture
            signed = amt_w[4].replace("$", "").replace(",", "")
            neg = signed.startswith("-")
            amt = float(signed.lstrip("-"))
            desc_words = [w[4] for w in row
                          if w is not date_w and w is not amt_w and w[0] > 80 and w[2] < 430]
            desc = " ".join(desc_words).strip()[:100]
            if not desc:
                continue
            mm, dd = (int(x) for x in date_w[4].split("/"))
            txn_year = yr if mm <= mo else yr - 1  # period spans the prior month
            notation = "PAYMENT" if "PAYMENT" in desc.upper() else ("CREDIT" if neg else "PURCHASE")
            txns.append({"event_date": f"{txn_year:04d}-{mm:02d}-{dd:02d}",
                         "description": desc, "notation": notation, "amount": amt})
    doc.close()
    return as_of, txns


def _parse_citi(path: Path) -> tuple[str | None, list[dict]]:
    """Citi Visa statement. Page 3 table: Sale Date | Post Date | Description |
    Amount. Credits print the literal word 'minus' glued to the amount. Post
    date optional (a lone date sits in the POST x-band — do not shift columns).
    as_of = month-end of the statement month (filename carries month only)."""
    import fitz
    from datetime import date
    m = _re.match(r"Citi-Visa-(\d{4})-(\d{2})\.pdf", path.name)
    if not m:
        return None, []
    yr, mo = int(m.group(1)), int(m.group(2))
    last_day = (date(yr + (mo // 12), mo % 12 + 1, 1) - date.resolution).day if mo < 12 else 31
    as_of = f"{yr:04d}-{mo:02d}-{last_day:02d}"
    doc = fitz.open(str(path))
    txns = []
    for page in doc:
        for row in _words_by_row(page.get_text("words")):
            date_ws = [w for w in row if _re.fullmatch(r"\d{2}/\d{2}", w[4]) and w[0] < 115]
            amt_w = next((w for w in reversed(row)
                          if _re.fullmatch(r"(minus)?\$?[\d,]+\.\d{2}", w[4]) and w[0] > 300), None)
            desc_ws = [w for w in row if w[0] >= 115 and w is not amt_w]
            if not date_ws or amt_w is None or not desc_ws:
                continue  # chips ('New Charges', 'Standard Purchases'), headers
            tok = amt_w[4]
            neg = tok.startswith("minus")
            amt = float(tok.replace("minus", "").replace("$", "").replace(",", ""))
            desc = " ".join(w[4] for w in desc_ws).strip()[:100]
            mm, dd = (int(x) for x in date_ws[-1][4].split("/"))  # sale date; falls back to post band
            txn_year = yr if mm <= mo else yr - 1
            notation = "PAYMENT" if "PAYMENT" in desc.upper() else ("CREDIT" if neg else "PURCHASE")
            txns.append({"event_date": f"{txn_year:04d}-{mm:02d}-{dd:02d}",
                         "description": desc, "notation": notation, "amount": amt})
    doc.close()
    return as_of, txns


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
    parser = spec.get("parser", "usbank")
    if parser == "chase":
        as_of, txns = _parse_chase(path)
    elif parser == "citi":
        as_of, txns = _parse_citi(path)
    else:
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


# ================================================================ P2 structural reader
# blueprint v0.3 §4 (classifier + legal-state table), §5 (store contract), §6
# (identity), v0.2.1 §E4 (load-time shape assertions) + §D3 (allow-list join,
# refuse-on-orphan, quarantine). Consumes the `sheets snapshot` artifact
# (private/raw/sheets/<alias>__<tab>.json); the legacy CSV path stays for the
# specs that have no artifact.
#
# Nothing in this section prints or returns owner values: source rows, column
# letters, kinds and counts only.

ALLOW_LIST_PATH = config.PRIVATE_DIR / "layouts" / "layouts.json"

# §4 derivation_kind is a SET, stored NORMALISED per src_column.derivation_kind:
# lower-case tokens, alphabetically sorted, comma-joined, no spaces.
DERIVATION_TOKENS = frozenset({
    "constant", "deterministic", "aggregate", "projection", "chain",
    "copy", "declared_derived", "unresolved_ref", "unknown_formula",
})
AGGREGATE_FUNCS = frozenset({
    "SUM", "SUMIF", "SUMIFS", "SUMPRODUCT", "AVERAGE", "AVERAGEIF",
    "AVERAGEIFS", "COUNT", "COUNTA", "COUNTIF", "COUNTIFS", "MIN", "MAX",
    "SUBTOTAL", "PRODUCT", "STDEV", "VAR",
})
PROJECTION_FUNCS = frozenset({
    "VLOOKUP", "HLOOKUP", "LOOKUP", "XLOOKUP", "INDEX", "MATCH", "INDIRECT",
    "OFFSET", "QUERY", "FILTER", "SORT", "SORTN", "UNIQUE", "CHOOSE",
    "TRANSPOSE", "ARRAYFORMULA",
})
EXTERNAL_FUNCS = frozenset({
    "IMPORTRANGE", "IMPORTDATA", "IMPORTXML", "IMPORTHTML", "IMPORTFEED",
    "GOOGLEFINANCE", "GOOGLETRANSLATE", "IMAGE",
})

# A1 references. Quoted sheet names ('Inv Income') and bare sheet names are the
# cross-sheet signal; a bare ref is same-tab. A negative lookbehind/lookahead
# keeps function names (LOG10() ) and identifiers out.
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(?P<col>\$?[A-Z]{1,3})(?P<row>\$?\d{1,7})(?!\()\b"
)
_FUNC_RE = re.compile(r"(?<![A-Za-z0-9_.])([A-Z][A-Z0-9_.]*)\s*\(")
_PURE_REF_RE = re.compile(r"^\$?[A-Z]{1,3}\$?\d{1,7}$")
_RANGE_REF_RE = re.compile(r"^\$?[A-Z]{1,3}\$?\d{1,7}:\$?[A-Z]{1,3}\$?\d{1,7}$")
_A1_RE = re.compile(r"^([A-Z]{1,3})(\d{1,7})$")
_STR_RE = re.compile(r'"(?:[^"]|"")*"')


class Quarantine(Exception):
    """A declared-shape mismatch (§E4) or an unparseable formula (§4): the spec is
    quarantined and reported, never partially loaded under a shifted frame."""

    def __init__(self, rule: str, detail: str = ""):
        self.rule = rule
        self.detail = detail
        super().__init__(f"{rule}{': ' + detail if detail else ''}")


def col_letters(i0: int) -> str:
    """0-based column index -> A1 letters."""
    s, n = "", i0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _split_a1(a1: str):
    m = _A1_RE.match(a1 or "")
    return (m.group(1), int(m.group(2))) if m else (None, None)


def _label_key(s) -> str:
    """Whitespace-collapsed, case-folded label/identity comparison."""
    return norm_label(s).casefold()


def _join_norm(s) -> str:
    """Normalise an (alias, tab) join key: lower-case, alphanumerics only.

    layouts.json spells the tab `Net-Worth Data`; a snapshot FILE is spelled
    `stats__Net_Worth_Data.json`. A filename is NEVER identity (charter /
    v0.2.1 E6) — this normalisation only makes the same declared pair match
    across spellings; the artifact's embedded `tab` is the validated title.
    """
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def load_allow_list(path: Path | None = None) -> dict:
    return json.loads(Path(path or ALLOW_LIST_PATH).read_text())


def allow_list_entry(allow: dict, alias: str, tab: str, where: str) -> tuple:
    """Join the allow-list on (alias, tab). REFUSES on an orphan pair, naming it.

    v0.2.1 §D3: no entry -> refuse to load. Tolerant on spelling only; the
    artifact's embedded tab title (not the filename) is what is matched.
    """
    akey = _join_norm(alias)
    src_key = next((k for k in allow.get("sources", {}) if _join_norm(k) == akey), None)
    if src_key is None:
        raise LoadError(
            f"allow-list join refused at {where}: no layouts.json source entry for "
            f"alias {alias!r} (normalised {akey!r})"
        )
    tabs = allow["sources"][src_key].get("tabs", {})
    tkey = _join_norm(tab)
    tab_key = next((k for k in tabs if _join_norm(k) == tkey), None)
    if tab_key is None:
        raise LoadError(
            f"allow-list join refused at {where}: no layouts.json tab entry for "
            f"({alias!r}, {tab!r}) under source {src_key!r}; have {sorted(tabs)}"
        )
    return src_key, tab_key, tabs[tab_key]


# ---------------------------------------------------------------- blank semantics (DM-2026-01)
# A blank cell inside an existing live row means 0 (presence='zero_from_blank')
# unless the column DECLARES blank_means='not_applicable' in the allow-list —
# then the cell has no meaningful value at that row and NO row is written.
# Two values only; a cell-level 'not_recorded' does not exist: absent rows and
# absent periods are coverage_calendar's business, never blank_means'.

BLANK_MEANS_VALUES = ("zero", "not_applicable")


def blank_rule_value(rule) -> tuple[str, str | None]:
    """Accept the plain form ('not_applicable') or the object form
    ({'value': …, 'note': evidence}); return (value, note). Refuse the rest."""
    note = None
    if isinstance(rule, dict):
        note = rule.get("note")
        rule = rule.get("value")
    if rule not in BLANK_MEANS_VALUES:
        raise LoadError(
            f"blank_means value {rule!r} is not one of {BLANK_MEANS_VALUES} "
            f"(DM-2026-01: 'zero' is the default and may be omitted)")
    return rule, note


def blank_rules_for(layout: dict, spec: dict, rect: "_Rect") -> dict[int, str]:
    """Per-column blank rule from the allow-list tab entry's `blank_means` map —
    declared, never inferred (DM-2026-01). Returns {col_index: rule} covering
    every column the spec resolves (default 'zero'). Fails loud on a malformed
    value or a declaration that names no resolvable column."""
    declared = layout.get("blank_means") or {}
    by_label: dict[str, str] = {}
    for label, raw in declared.items():
        value, _note = blank_rule_value(raw)
        by_label[_label_key(label)] = value
    rules: dict[int, str] = {}
    unmatched = dict(by_label)
    for label, (ci, _hdr, _mapping) in rect.resolved.items():
        hit = by_label.get(_label_key(label))
        rules[ci] = hit if hit is not None else "zero"
        unmatched.pop(_label_key(label), None)
    if unmatched:
        raise LoadError(
            f"{spec['alias']}: blank_means declares column(s) {sorted(unmatched)} "
            f"that no column of this spec resolves — fix the allow-list entry "
            f"(declarations are block-scoped to the tab entry)")
    return rules


SERIES_START_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_MONTH_NAMES = (None, "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")
# The shape detector's floor: a column whose populated cells all fall in one
# calendar month with this many of them is an annual-in-practice series.
SERIES_SHAPE_MIN_POPULATED = 8


def series_start_value(rule) -> tuple[str, str | None]:
    """Accept the plain form ('1999-12') or the object form
    ({'value': …, 'note': evidence}); return (value, note). Refuse the rest —
    a series start that is not a calendar month is not a boundary."""
    note = None
    if isinstance(rule, dict):
        note = rule.get("note")
        rule = rule.get("value")
    if not isinstance(rule, str) or not SERIES_START_RE.match(rule.strip()):
        raise LoadError(
            f"series_start value {rule!r} is not a 'YYYY-MM' month — a column "
            f"contributes nothing before its declared series start")
    return rule.strip(), note


def series_starts_for(layout: dict, spec: dict, rect: "_Rect") -> dict[int, tuple]:
    """Per-column series start from the allow-list tab entry's `series_start` map
    (declared, never inferred — same pattern as blank_means). Returns
    {col_index: (start, note)}. Fails loud on a malformed value or a declaration
    that names no resolvable column."""
    declared = layout.get("series_start") or {}
    by_label: dict[str, tuple] = {}
    for label, raw in declared.items():
        by_label[_label_key(label)] = series_start_value(raw)
    starts: dict[int, tuple] = {}
    unmatched = dict(by_label)
    for label, (ci, _hdr, _mapping) in rect.resolved.items():
        hit = by_label.get(_label_key(label))
        if hit is not None:
            starts[ci] = hit
            unmatched.pop(_label_key(label), None)
    if unmatched:
        raise LoadError(
            f"{spec['alias']}: series_start declares column(s) {sorted(unmatched)} "
            f"that no column of this spec resolves — fix the allow-list entry "
            f"(declarations are block-scoped to the tab entry)")
    return starts


def series_shape_lines(rect: "_Rect", pop_months: dict, blank_rules: dict,
                       series_starts: dict) -> list[dict]:
    """REPORT ONLY (DM-2026-01 follow-up, shape detector): for each mapped column
    whose populated cells all fall in a single calendar month — and there are at
    least SERIES_SHAPE_MIN_POPULATED of them — describe the shape as
    'annual-in-practice' and say whether blank_means is declared.

    It reads only WHICH rows are populated (classifier metadata: blank vs a cell
    the reader accepted) and their calendar month — never a value. Its output is
    a report line, never a failure: the counts-only zero report could not tell
    `Deposit (L): zeros=301` (wrong) from a full-spine balance column
    `Plan 401K (G): zeros=300` (right); the shape can."""
    shapes: list[dict] = []
    for label, (ci, _hdr, mapping) in sorted(rect.resolved.items(),
                                             key=lambda kv: kv[1][0]):
        if mapping is None or mapping.get("role") in ("as_of", "work_year"):
            continue
        per_month = pop_months.get(ci) or {}
        populated = sum(per_month.values())
        if populated < SERIES_SHAPE_MIN_POPULATED or len(per_month) != 1:
            continue
        month, count = next(iter(per_month.items()))
        rule = blank_rules.get(ci, "zero")
        declared = ("blank_means declared not_applicable" if rule == "not_applicable"
                    else "blank_means NOT declared (default zero)")
        start = (series_starts.get(ci) or (None, None))[0]
        line = (f"SERIES SHAPE  {label} ({col_letters(ci)}): {populated} populated, "
                f"{round(100 * count / populated)}% {_MONTH_NAMES[month]} "
                f"-> annual-in-practice; {declared}")
        if start:
            line += f"; series_start={start}"
        shapes.append({"label": label, "letters": col_letters(ci),
                       "populated": populated, "month": month,
                       "share_pct": round(100 * count / populated),
                       "blank_means": rule, "series_start": start, "line": line})
    return shapes


def anchor_month_for(column_grain, tab_grain, where: str) -> int | None:
    """The month whose cell is EXPECTED to carry an observation for a column
    whose metric grain is coarser than the tab's row grain (DM-2026-01). Only
    'annual' on a month-based spine is supported (anchor = December); a
    same-grain or undeclared column has no anchor; anything else coarser
    refuses rather than guesses an anchor."""
    if not column_grain:
        return None
    cg = str(column_grain).strip().lower()
    tg = str(tab_grain or "").strip().lower()
    if not tg or cg == tg:
        return None
    if tg.startswith("month") and cg == "annual":
        return 12
    raise LoadError(
        f"{where}: no anchored-blank rule for column grain {column_grain!r} on a "
        f"{tab_grain!r} tab — declare the expectation in coverage_calendar "
        f"instead of guessing")


def _emit_period_coverage(conn, alias: str, tab: str, periods_live: set[str]) -> None:
    """Declare the tab's expected periods (DM-2026-01 boundary: absent rows and
    periods are coverage_calendar's business, never blank_means'). Every month
    in the span the live rows occupy is expected: 'loaded' where a live row
    exists, 'absent-in-source' where the source has none — recorded, never
    zeroed."""
    if not periods_live:
        return
    first, last = min(periods_live), max(periods_live)
    y, m = int(first[:4]), int(first[5:7])
    ey, em = int(last[:4]), int(last[5:7])
    cov: dict[str, str] = {}
    while (y, m) <= (ey, em):
        p = f"{y:04d}-{m:02d}"
        cov[p] = "loaded" if p in periods_live else "absent-in-source"
        m += 1
        if m == 13:
            y, m = y + 1, 1
    coverage(conn, alias, tab, cov,
             note="structural coverage: one expected month-end per live row; "
                  "months the source lacks are absent-in-source, never zeroed "
                  "(DM-2026-01)")


def _anchored_blank_findings(conn, spec: dict, anchored: dict) -> list[dict]:
    """DM-2026-01 guard: a blank cell at an EXPECTED anchor period of a
    not_applicable column is a missing observation, not N/A. Expectations are
    read back from coverage_calendar.expected (their declared home), so a
    period deliberately declared expected=0 stays silent — visibly."""
    if not anchored:
        return []
    expected = {r[0] for r in conn.execute(
        "SELECT period FROM coverage_calendar WHERE source_alias=? AND tab=? "
        "AND expected=1 AND period GLOB '????-12'",
        (spec["alias"], spec["tab"]))}
    return [f for (_ci, _year), f in sorted(anchored.items()) if f["period"] in expected]


def _print_blank_report(alias: str, extras: dict) -> None:
    """Per-column zero report at load (DM-2026-01 follow-up): an undeclared
    not_applicable column shows up here instead of being discovered by hand."""
    report = (extras or {}).get("zero_report") or {}
    cols = report.get("columns") or []
    if not cols:
        return
    print(f"  blank report {alias} (DM-2026-01): column -> zeros materialised", flush=True)
    for c in cols:
        extra = ""
        if c.get("series_start"):
            extra += f" series_start={c['series_start']}"
        if c.get("pre_start_skips"):
            extra += f" pre_start_skips={c['pre_start_skips']}"
        print(f"    {c['label']} ({c['letters']}): zeros={c['zeros']} "
              f"not_applicable_skips={c['not_applicable']} blanks_seen={c['blanks']}"
              f"{extra}", flush=True)
    for extra in (report.get("row_zero_from_blank"), None):
        if extra:
            print(f"    row-grain zero_from_blank rows: {extra}", flush=True)
    # Report-only shape detector (DM-2026-01 follow-up): never a failure.
    for sh in (extras or {}).get("series_shapes") or []:
        print(f"  {sh['line']}", flush=True)
    for f in (extras or {}).get("anchored_blanks") or []:
        print(f"  !! ANCHORED BLANK {alias}: column {f['column']} ({f['letters']}) "
              f"period {f['period']} is expected for a {f['grain']} metric but blank — "
              f"no row written; a missing observation, never N/A (DM-2026-01)", flush=True)


class _Rect:
    def __init__(self, header_row, group_row, sub_header_row, first_data_row,
                 skip_rows, last_data_row, resolved, key_col, external_cols,
                 derived_cols):
        self.header_row = header_row
        self.group_row = group_row
        self.sub_header_row = sub_header_row
        self.first_data_row = first_data_row
        self.skip_rows = skip_rows
        self.last_data_row = last_data_row
        self.resolved = resolved          # label -> (col_index, header_rec, mapping|None)
        self.key_col = key_col            # column index of the row key (date/year)
        self.external_cols = external_cols
        self.derived_cols = derived_cols

    @property
    def cols(self):
        return sorted({ci for ci, _, _ in self.resolved.values()})


def declared_rectangle(spec: dict, layout: dict, artifact: dict) -> _Rect:
    """The ingest rectangle: (first_data_row .. last_data_row) x declared columns.

    Layout semantics are AUTHORITATIVE from the allow-list (header_row,
    group_row, sub_header_row, first_data_row, skip_rows, last_data_row,
    key_column, external_links, derived_columns); the curation spec supplies the
    expected column labels and their account/metric mapping. E5(b)'s per-column
    allow-list fields do not exist in layouts.json yet, so the spec's `col` is
    the expected label today; when the allow-list gains `expected_label` it wins.
    """
    idx = {c["a1"]: c for c in artifact.get("cells", [])}
    header_row = layout.get("header_row") or spec.get("header_row")
    if not header_row:
        raise Quarantine("header_row-undeclared",
                         f"{spec['alias']}: no header_row in allow-list or spec")
    # header labels as declared by the sheet (the descriptor the artifact carries)
    header: dict[str, list] = {}
    for a1, rec in idx.items():
        col, row = _split_a1(a1)
        if row == header_row and rec.get("kind") != "blank":
            header.setdefault(_label_key(rec.get("value")), []).append((col, rec))

    declared: list[tuple] = []
    for cm in spec.get("columns", []):
        declared.append((cm.get("col"), cm))
    for lbl in spec.get("skip_columns", []):
        declared.append((lbl, None))

    resolved: dict = {}
    missing: list[str] = []
    for label, mapping in declared:
        if label is None:
            continue
        hits = header.get(_label_key(label), [])
        if not hits:
            missing.append(str(label))
            continue
        col, rec = hits[0]
        resolved[label] = (col_index(col), rec, mapping)
    if missing:
        raise Quarantine("header-label-missing",
                         f"{spec['alias']}: declared label(s) absent from header_row "
                         f"{header_row}: {missing}")

    first_data_row = layout.get("first_data_row") or spec.get("first_data_row") or (header_row + 1)
    last_data_row = (layout.get("last_data_row") or spec.get("last_data_row")
                     or (artifact.get("ingest_rectangle") or {}).get("last_row"))
    if not last_data_row:
        raise Quarantine("last_data_row-undeclared",
                         f"{spec['alias']}: no last_data_row in allow-list and no artifact rectangle")
    key_col = None
    key_label = layout.get("key_column")
    if key_label:
        key_col = col_index(key_label) if len(str(key_label)) <= 3 and str(key_label).isalpha() else None
    for label, (ci, _rec, mapping) in resolved.items():
        if mapping and mapping.get("role") in ("as_of", "work_year"):
            key_col = ci
    if key_col is None:
        raise Quarantine("key-column-undeclared", f"{spec['alias']}: no as_of/work_year column resolved")
    external_cols = {str(k).upper() for k in (layout.get("external_links") or {})}
    derived_cols = {str(c).upper() for c in (layout.get("derived_columns") or [])}
    return _Rect(header_row, layout.get("group_row"), layout.get("sub_header_row"),
                 int(first_data_row), list(layout.get("skip_rows") or spec.get("skip_rows") or []),
                 int(last_data_row), resolved, key_col, external_cols, derived_cols)


def assert_artifact_coverage(artifact: dict, rect: _Rect, where: str) -> None:
    """v0.3 §3 hard rule + charter v1.0.2 'coverage is proven, never assumed'."""
    if artifact.get("truncated") is not False:
        raise LoadError(
            f"{where}: artifact truncated={artifact.get('truncated')!r} — a truncated "
            f"read is refused, never partially loaded (v0.3 §3)"
        )
    rb = artifact.get("returned_bounds") or {}
    need_rows, need_cols = rect.last_data_row, max(rect.cols) + 1
    if rb.get("rows", 0) < need_rows or rb.get("cols", 0) < need_cols:
        raise LoadError(
            f"{where}: artifact returned_bounds={rb} do not cover the declared "
            f"rectangle (rows<={need_rows}, cols<={col_letters(need_cols - 1)}) — refusing"
        )
    wrect = artifact.get("ingest_rectangle") or {}
    if wrect:
        declared_cols = {col_letters(c) for c in rect.cols}
        wcols = set(wrect.get("columns") or [])
        if (rect.first_data_row < wrect.get("first_row", 1)
                or rect.last_data_row > wrect.get("last_row", 0)
                or not declared_cols <= wcols):
            raise LoadError(
                f"{where}: declared rectangle rows {rect.first_data_row}..{rect.last_data_row} "
                f"cols {sorted(declared_cols)} is not inside the artifact's writer "
                f"rectangle {wrect.get('first_row')}..{wrect.get('last_row')} {sorted(wcols)} — refusing"
            )


def assert_shape(artifact: dict, rect: _Rect, layout: dict, spec: dict) -> None:
    """v0.2.1 §E4 load-time shape assertions. Mismatch -> Quarantine."""
    idx = {c["a1"]: c for c in artifact.get("cells", [])}
    problems: list[str] = []

    # (a) expected label at each declared header cell
    for label, (ci, rec, _m) in rect.resolved.items():
        if rec.get("kind") == "blank":
            problems.append(f"header label {label!r} is blank at {col_letters(ci)}{rect.header_row}")

    # (b) declared group / sub-header tiers are labels, never formulas
    for tier, tier_name in ((rect.group_row, "group_row"), (rect.sub_header_row, "sub_header_row")):
        if tier is None:
            continue
        if not (rect.header_row < int(tier) < rect.first_data_row):
            problems.append(f"{tier_name} r{tier} is not between header_row and first_data_row")
        for ci in rect.cols:
            rec = idx.get(f"{col_letters(ci)}{tier}")
            if rec and rec.get("kind") in ("formula", "error", "spill"):
                problems.append(f"{tier_name} {col_letters(ci)}{tier} carries a {rec['kind']}, not a label")

    # (c) skip_rows shape: strictly inside the header band and NOT live key rows
    for sr in rect.skip_rows:
        sr = int(sr)
        if not (rect.header_row < sr < rect.first_data_row):
            problems.append(f"skip_rows r{sr} is not between header_row and first_data_row")
        krec = idx.get(f"{col_letters(rect.key_col)}{sr}")
        if krec and krec.get("kind") != "blank":
            kv = krec.get("value")
            if rect_key_live(kv, spec):
                problems.append(f"skip_rows r{sr} carries a live key ({col_letters(rect.key_col)}{sr}) "
                                f"— blank band / total row / label-only row expected")

    # (d) first_data_row must begin on a live key row
    kfirst = idx.get(f"{col_letters(rect.key_col)}{rect.first_data_row}")
    if not (kfirst and kfirst.get("kind") != "blank" and rect_key_live(kfirst.get("value"), spec)):
        problems.append(f"first_data_row r{rect.first_data_row} does not carry a live key")

    # (e) declared merges present; a merge shadow is NEVER a blank (§4/E3)
    declared_merges = layout.get("merges") or spec.get("merges") or []
    have = set(artifact.get("merges") or [])
    for m in declared_merges:
        if m not in have:
            problems.append(f"declared merge {m} absent from the artifact")
    for a1, rec in idx.items():
        if rec.get("merge_shadow_of") and rec.get("kind") == "blank":
            problems.append(f"merge shadow {a1} is a blank — shadows inherit, never zero (§4/E3)")

    if problems:
        raise Quarantine("shape-mismatch", "; ".join(problems[:6])
                         + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""))


def rect_key_live(value, spec: dict) -> bool:
    """A row is live iff its key column parses as the declared key type."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    if spec.get("family") == "ssa_earnings" or any(
            c.get("role") == "work_year" for c in spec.get("columns", [])):
        try:
            int(float(str(value).strip()))
            return True
        except (TypeError, ValueError):
            return False
    iso, _why = coerce_date(value, fmt=spec.get("date_format"))
    return iso is not None


def _mask_formula_shape(formula: str) -> str:
    s = _STR_RE.sub('"S"', formula or "")
    s = re.sub(r"\d+", "#", s)
    return re.sub(r"\s+", " ", s).strip()


def normalise_derivation_kinds(tokens) -> str | None:
    toks = sorted({str(t).strip().lower() for t in tokens if t and str(t).strip()})
    return ",".join(toks) if toks else None


def _formula_refs(body: str):
    b = _STR_RE.sub('""', body)
    out = []
    for m in _REF_RE.finditer(b):
        if m.group("sheet") is not None:
            out.append((m.group("sheet"), m.group("col").lstrip("$"), int(m.group("row").lstrip("$"))))
        else:
            out.append((None, m.group("col").lstrip("$"), int(m.group("row").lstrip("$"))))
    return out


class _CellCtx:
    def __init__(self, idx: dict, external_cols: set, derived_cols: set, layout: dict, spec: dict):
        self.idx = idx
        self.external_cols = external_cols
        self.derived_cols = derived_cols
        self.layout = layout
        self.spec = spec
        self.depth = 0


def _blank_record(at: str) -> dict:
    # §3 + §4: an in-rectangle blank is a STATED zero, never an absence, and is
    # emitted by the writer inside the rectangle (kind:"blank").
    return {"origin": "entered", "presence": "zero_from_blank", "derivation": None,
            "value_num": 0.0, "value_text": None, "error_type": None,
            "copy_of": None, "formula_shape": None, "skip_reason": None, "at": at}


def _error_record(at: str, token: str) -> dict:
    return {"origin": "derived", "presence": "error", "derivation": None,
            "value_num": None, "value_text": token or "ERROR", "error_type": token or "ERROR",
            "copy_of": None, "formula_shape": None, "skip_reason": None, "at": at}


def _literal_record(at: str, cell: dict, ctx: _CellCtx, ci: int) -> dict:
    num, why = coerce_num(cell.get("value"))
    if num is None:
        # A non-numeric literal in a numeric fact column (the ratified 1996-98
        # stray date cells, D14): refused loudly and skipped, never coerced.
        return {"origin": None, "presence": None, "derivation": None,
                "value_num": None, "value_text": None, "error_type": None,
                "copy_of": None, "formula_shape": None,
                "skip_reason": f"non-numeric-literal ({why})", "at": at}
    declared_external = col_letters(ci) in ctx.external_cols
    return {"origin": "external" if declared_external else "entered", "presence": "measured",
            "derivation": "declared_derived" if col_letters(ci) in ctx.derived_cols else None,
            "value_num": num, "value_text": None, "error_type": None,
            "copy_of": None, "formula_shape": None, "skip_reason": None, "at": at}


def classify_cell(cell: dict, ci: int, ctx: _CellCtx) -> dict:
    """v0.3 §4 classifier for one artifact cell, applied AFTER merges are resolved
    and AFTER the rectangle is established. Ordered, total, and refuses rather
    than defaulting an unmapped state to `measured`."""
    at = cell.get("a1") or "?"
    kind = cell.get("kind")

    # merge shadow: inherits the anchor wholesale and is NEVER a blank (§4/E3)
    if cell.get("merge_shadow_of"):
        anchor = ctx.idx.get(cell["merge_shadow_of"])
        if anchor is None:
            raise Quarantine("merge-shadow-anchor-missing", f"{at} -> {cell['merge_shadow_of']}")
        if anchor.get("kind") == "blank":
            raise Quarantine("merge-shadow-of-blank", f"{at} -> {cell['merge_shadow_of']}")
        base = classify_cell(anchor, col_index(_split_a1(cell["merge_shadow_of"])[0] or "A"), ctx)
        base = dict(base, at=at)
        base["merge_shadow_of"] = cell["merge_shadow_of"]
        return base

    if kind == "blank":
        return _blank_record(at)

    if kind == "error":
        return _error_record(at, cell.get("error_type"))

    if kind == "spill":
        sp = cell.get("spill_of")
        if not sp:
            # v0.3 §3/§4: an indeterminate spill extent refuses.
            raise Quarantine("indeterminate-spill", f"{at} carries no spill_of")
        anchor = ctx.idx.get(sp)
        if anchor is None:
            raise Quarantine("spill-anchor-missing", f"{at} -> {sp}")
        base = dict(classify_cell(anchor, col_index(_split_a1(sp)[0] or "A"), ctx), at=at)
        base["spill_of"] = sp
        return base

    if kind == "literal":
        return _literal_record(at, cell, ctx, ci)

    if kind == "formula":
        return _classify_formula(at, cell, ci, ctx)

    raise Quarantine("unclassified-kind", f"{at} kind={kind!r} (v0.3 §4 step 4)")


def _classify_formula(at: str, cell: dict, ci: int, ctx: _CellCtx) -> dict:
    if ctx.depth > 32:
        raise Quarantine("formula-cycle", f"{at}: copy/chain resolution exceeded depth 32")
    formula = cell.get("formula") or ""
    body = formula[1:] if formula.startswith("=") else formula
    shape = _mask_formula_shape(formula)
    # The artifact carries the computed value alongside the formula (it is the
    # ingest input). A value that will not coerce to a number is NOT silently
    # zeroed: it is skipped with a logged reason unless it is an error token.
    vnum, _vwhy = coerce_num(cell.get("value"))
    stripped = body.strip()
    if stripped in ('""', "''"):
        # §4: formula -> empty string is NOT ingested, reason logged.
        return {"origin": "derived", "presence": None, "derivation": None,
                "value_num": None, "value_text": None, "error_type": None,
                "copy_of": None, "formula_shape": shape,
                "skip_reason": "formula-empty-string", "at": at}
    if not stripped or stripped.startswith("#") and "(" not in stripped:
        raise Quarantine("unparseable-formula", f"{at}: {shape}")

    clean = _STR_RE.sub('""', body)
    funcs = {m.group(1).upper() for m in _FUNC_RE.finditer(clean)}
    refs = _formula_refs(body)
    cross = [r for r in refs if r[0] is not None]
    same = [(c, r) for (sheet, c, r) in refs if sheet is None]
    external_col = col_letters(ci) in ctx.external_cols

    def derived(base_tokens, origin, presence):
        tokens = set(base_tokens)
        if any(_ref_is_derived(c, r, ctx) for (c, r) in same):
            tokens.add("chain")
        if external_col:
            origin = "external"
        return {"origin": origin, "presence": presence,
                "derivation": normalise_derivation_kinds(tokens),
                "value_num": vnum, "value_text": None, "error_type": None,
                "copy_of": None, "formula_shape": shape, "skip_reason": None, "at": at}

    # cross-sheet / external wins over every formula shape (§4 precedence)
    if cross or funcs & EXTERNAL_FUNCS:
        tokens = {"chain"}
        if funcs & PROJECTION_FUNCS:
            tokens.add("projection")
        if funcs & AGGREGATE_FUNCS:
            tokens.add("aggregate")
        if not (funcs - EXTERNAL_FUNCS):
            tokens.add("deterministic")
        return derived(tokens, "external", "estimated")

    # formula whose operands are all literals -> entered / constant / measured
    if not refs and not funcs:
        if not re.fullmatch(r"[\d\s.+\-*/^%(),&<>=\"']+", body):
            raise Quarantine("unparseable-formula", f"{at}: {shape}")
        return {"origin": "entered", "presence": "measured", "derivation": "constant",
                "value_num": vnum, "value_text": None, "error_type": None,
                "copy_of": None, "formula_shape": shape, "skip_reason": None, "at": at}

    # pure reference -> copy; a copy NEVER raises trust (inherits the source presence)
    if _PURE_REF_RE.match(stripped):
        ref = stripped.replace("$", "")
        src = ctx.idx.get(ref)
        ctx.depth += 1
        try:
            src_cls = classify_cell(src, ci, ctx) if src is not None else None
        finally:
            ctx.depth -= 1
        if src_cls is None:
            tokens = {"copy", "unresolved_ref"}
            return derived(tokens, "copy", "estimated")
        if src_cls.get("skip_reason"):
            return {"origin": "copy", "presence": "estimated", "derivation": "copy",
                    "value_num": None, "value_text": None, "error_type": None,
                    "copy_of": ref, "formula_shape": shape,
                    "skip_reason": f"copy-of-{src_cls['skip_reason']}", "at": at}
        tokens = {"copy"}
        if "chain" in (src_cls.get("derivation") or ""):
            tokens.add("chain")
        return {"origin": "external" if external_col else "copy",
                "presence": src_cls["presence"], "derivation": normalise_derivation_kinds(tokens),
                "value_num": vnum, "value_text": None, "error_type": None,
                "copy_of": ref, "formula_shape": shape, "skip_reason": None, "at": at}

    # a bare range reference is a projection over a span, not a copy
    if _RANGE_REF_RE.match(stripped):
        return derived({"projection"}, "derived", "estimated")

    if funcs & PROJECTION_FUNCS:
        return derived({"projection"}, "derived", "estimated")
    if funcs & AGGREGATE_FUNCS:
        return derived({"aggregate"}, "derived", "estimated")
    # arithmetic over cells: deterministic, escalated to estimated (never measured)
    if refs or re.fullmatch(r"[\s\d.+\-*/^%(),&<>=A-Za-z$'\"]+", body):
        return derived({"deterministic"}, "derived", "estimated")
    raise Quarantine("unparseable-formula", f"{at}: {shape}")


def _ref_is_derived(letters: str, row: int, ctx: _CellCtx) -> bool:
    rec = ctx.idx.get(f"{letters}{row}")
    return bool(rec) and rec.get("kind") in ("formula", "error", "spill")


def _read_artifact(spec: dict) -> dict:
    path = Path(spec["artifact"])
    if not path.exists():
        raise LoadError(f"{spec['alias']}: artifact not found at {path} — fetch it with "
                        f"`bagend.py sheets snapshot` before loading")
    artifact = json.loads(path.read_text())
    if artifact.get("artifact_version") != 1:
        raise LoadError(f"{spec['alias']}: artifact_version={artifact.get('artifact_version')!r} "
                        f"is not the supported v1 (§3)")
    return artifact


def _validate_artifact_identity(spec: dict, artifact: dict) -> None:
    """v0.3 §6: (drive_id, sheet_id) is identity; tab/alias are validated metadata."""
    if spec.get("drive_id") and artifact.get("drive_id") != spec["drive_id"]:
        raise LoadError(f"{spec['alias']}: artifact drive_id does not match the curation spec "
                        f"(§6 identity) — refusing")
    if artifact.get("tab") and _label_key(artifact["tab"]) != _label_key(spec.get("tab")):
        raise LoadError(f"{spec['alias']}: artifact tab {artifact['tab']!r} != declared "
                        f"{spec.get('tab')!r} — refusing (a filename is never identity)")


def _quarantine(conn, batch: Batch, spec: dict, artifact: dict | None, q: Quarantine) -> None:
    """v0.3 §7: quarantine must be VISIBLE — coverage_calendar not-loaded rows plus
    a partial batch. A silent refusal would just make the store look complete."""
    batch.partial = True
    conn.execute("UPDATE load_batch SET status='partial' WHERE batch_id=?", (batch.batch_id,))
    periods: list[str] = []
    if artifact:
        idx = {c["a1"]: c for c in artifact.get("cells", [])}
        try:
            rect = declared_rectangle(spec, {"header_row": spec.get("header_row")}, artifact)
            key_ci = rect.key_col
        except Exception:
            key_ci = 0
        for a1, rec in idx.items():
            col, row = _split_a1(a1)
            if col_index(col) != key_ci or rec.get("kind") == "blank":
                continue
            v = rec.get("value")
            if isinstance(v, str) and re.match(r"^\d{4}", v):
                periods.append(v[:4])
            elif isinstance(v, (int, float)) and 1900 <= v <= 2100:
                periods.append(str(int(v)))
    if not periods:
        periods = [str(datetime.now(timezone.utc).year)]
    for p in sorted(set(periods)):
        coverage(conn, spec["alias"], spec["tab"], {p: "not-loaded"},
                 note=f"quarantined: {q.rule}")
    conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | QUARANTINE '||? WHERE batch_id=?",
                 (str(q)[:300], batch.batch_id))
    print(f"  !! QUARANTINED {spec['alias']}: {q.rule} — {q.detail}", flush=True)


def _write_src_columns(conn, source_id: int, spec: dict, rect: _Rect, col_facts: dict,
                       metric_ids: dict, acct_ids: dict) -> int:
    """Populate src_column (never written before v0.2.5): column-grain derivation,
    per blueprint §2/§5. Replaces the tab's rows so a re-load is idempotent."""
    row = conn.execute("SELECT tab_id FROM src_tab WHERE source_id=? AND tab=? AND block=''",
                       (source_id, spec["tab"])).fetchone()
    if row is None:
        raise LoadError(f"{spec['alias']}: src_tab row missing for tab {spec['tab']!r}")
    tab_id = row[0]
    conn.execute("DELETE FROM src_column WHERE tab_id=?", (tab_id,))
    n = 0
    by_label = {label: tup for label, tup in rect.resolved.items()}
    for label, (ci, header_rec, mapping) in sorted(by_label.items(), key=lambda kv: kv[1][0]):
        facts = col_facts.get(ci, {})
        origin = facts.get("origin")
        if mapping and mapping.get("role") in ("as_of", "work_year"):
            role = "key"
        elif origin == "external" or col_letters(ci) in rect.external_cols:
            role = "external"
        elif origin == "copy":
            role = "copy"
        elif origin == "derived":
            role = "derived"
        elif mapping is None:
            role = "scratch"
        else:
            role = "value"
        account_id = acct_ids.get(mapping.get("account")) if mapping else None
        metric_id = metric_ids.get(mapping.get("metric")) if mapping else None
        unit = None
        if metric_id is not None:
            mrow = conn.execute("SELECT unit FROM dim_metric WHERE metric_id=?", (metric_id,)).fetchone()
            unit = mrow[0] if mrow else None
        conn.execute(
            """INSERT INTO src_column(tab_id, col_index, header_text, header_occurrence,
               account_id, metric_id, unit, origin, derivation_kind, formula_shape, copy_of, role)
               VALUES (?,?,?,1,?,?,?,?,?,?,?,?)""",
            (tab_id, ci, norm_label(header_rec.get("value")), account_id, metric_id, unit,
             facts.get("origin"), normalise_derivation_kinds(facts.get("tokens") or []),
             facts.get("formula_shape"), facts.get("copy_of"), role),
        )
        n += 1
    return n


def _apply_cell_facts(col_facts: dict, ci: int, cls: dict) -> None:
    f = col_facts.setdefault(ci, {"tokens": set(), "origins": set(), "shapes": set(),
                                  "copy_of": None, "formula_shape": None})
    if cls.get("skip_reason"):
        return
    if cls.get("origin"):
        f["origins"].add(cls["origin"])
    if cls.get("derivation"):
        f["tokens"].update(str(cls["derivation"]).split(","))
    if cls.get("formula_shape"):
        f["shapes"].add(cls["formula_shape"])
    if cls.get("copy_of") and not f["copy_of"]:
        f["copy_of"] = cls["copy_of"]


def _resolve_col_origin(col_facts: dict) -> None:
    precedence = ("external", "derived", "copy", "entered")
    for f in col_facts.values():
        for o in precedence:
            if o in f["origins"]:
                f["origin"] = o
                break
        else:
            f["origin"] = None
        if f["shapes"]:
            f["formula_shape"] = " | ".join(sorted(f["shapes"]))
        else:
            f["formula_shape"] = None


def _live_rows(artifact: dict, rect: _Rect, spec: dict):
    """Yield (row_number, key_value) for live rows of the declared rectangle."""
    idx = {c["a1"]: c for c in artifact.get("cells", [])}
    for r in range(rect.first_data_row, rect.last_data_row + 1):
        rec = idx.get(f"{col_letters(rect.key_col)}{r}")
        if rec is None or rec.get("kind") == "blank":
            continue
        yield r, rec.get("value")


def _load_state_structural(conn, batch: Batch, spec: dict, source_id: int, layout: dict,
                           artifact: dict, rect: _Rect, acct_ids, metric_ids) -> tuple:
    idx = {c["a1"]: c for c in artifact.get("cells", [])}
    ctx = _CellCtx(idx, rect.external_cols, rect.derived_cols, layout, spec)
    col_facts: dict = {}
    total_label = next((lbl for lbl in rect.resolved
                        if _label_key(lbl) == _label_key("Total Assets")), None)
    derived_cols = [m for m in spec["columns"] if m.get("mode") == "derive_from_delta"]
    seq_buf: dict = {}
    issues: list[str] = []
    row_totals: dict = {}
    n = 0
    n_skipped = 0
    # DM-2026-01 blank semantics: per-column rule, per-column visibility, and
    # the anchored-blank guard against coverage_calendar.expected.
    blank_rules = blank_rules_for(layout, spec, rect)
    # DM-2026-01 owner confirmation: the allow-list MAY also declare where a
    # column's series begins (series_start). Before that boundary the column
    # contributes nothing — no stated zero, and no expected anchor.
    series_starts = series_starts_for(layout, spec, rect)
    tab_grain = layout.get("grain") or spec.get("grain")
    anchors: dict[int, int] = {}      # col_index -> anchor month (only not_applicable columns)
    for label, (ci, _hdr, mapping) in rect.resolved.items():
        if mapping is None or mapping.get("role") in ("as_of", "work_year"):
            continue
        if blank_rules.get(ci, "zero") != "not_applicable":
            continue
        am = anchor_month_for(mapping.get("grain"), tab_grain,
                              f"{spec['alias']} column {label!r}")
        if am is not None:
            anchors[ci] = am
    blank_seen: dict[int, int] = {}   # col_index -> blank cells seen
    zero_written: dict[int, int] = {} # col_index -> zero_from_blank rows materialised
    na_skipped: dict[int, int] = {}   # col_index -> not_applicable blanks (no row)
    pre_start_skips: dict[int, int] = {}  # col_index -> blanks before series_start (no row)
    pop_months: dict[int, dict] = {}  # col_index -> {calendar month: populated rows}
    anchored: dict = {}               # (col_index, year) -> finding
    period_months: set[str] = set()
    for rowno, keyv in _live_rows(artifact, rect, spec):
        as_of, d_reason = coerce_date(keyv, fmt=spec.get("date_format"))
        if as_of and spec.get("month_end") and len(as_of) == 7:
            import calendar as _cal
            y, m = map(int, as_of.split("-"))
            as_of = f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"
        if as_of is None:
            issues.append(f"row {rowno}: key {d_reason}")
            continue
        period_months.add(as_of[:7])
        row_sum = 0.0
        for label, (ci, _hdr, mapping) in rect.resolved.items():
            if mapping is not None and mapping.get("role") == "as_of":
                continue   # row addressing, never a fact row (§4 key column)
            # Every DECLARED column is classified (so src_column carries the
            # column-grain derivation of skip_columns too); only mapped columns
            # become fact rows.
            derive_mode = bool(mapping and mapping.get("mode") == "derive_from_delta")
            cell = idx.get(f"{col_letters(ci)}{rowno}") or {"a1": f"{col_letters(ci)}{rowno}",
                                                           "kind": "blank"}
            if derive_mode:
                # component reconstructed by difference below: record it, never
                # read the column's placeholder cells as facts (D14).
                col_facts.setdefault(ci, {"tokens": {"deterministic"}, "origins": {"derived"},
                                          "shapes": set(), "copy_of": None,
                                          "formula_shape": None})
                if mapping is None:
                    continue
            else:
                cls = classify_cell(cell, ci, ctx)
                _apply_cell_facts(col_facts, ci, cls)
                # a blank is an artifact blank (or a spill of one); a formula
                # copying a blank is a formula observation, never a blank
                is_blank = (cls.get("presence") == "zero_from_blank"
                            and not cls.get("copy_of")
                            and not cls.get("merge_shadow_of"))
                if is_blank:
                    blank_seen[ci] = blank_seen.get(ci, 0) + 1
            if mapping is None:
                continue   # declared skip column: classified, not ingested
            start = (series_starts.get(ci) or (None, None))[0]
            before_start = start is not None and as_of[:7] < start
            if not derive_mode:
                if cls.get("skip_reason"):
                    issues.append(f"row {rowno} col {col_letters(ci)}: {cls['skip_reason']}")
                    continue
                if not is_blank:
                    # Report-only shape observation: which rows are populated,
                    # never a value (DM-2026-01 shape detector).
                    pm = pop_months.setdefault(ci, {})
                    pm[int(as_of[5:7])] = pm.get(int(as_of[5:7]), 0) + 1
                # DM-2026-01: a declared not_applicable blank writes NO row; a
                # blank BEFORE a declared series_start contributes nothing either
                # (the series did not exist yet — not a zero, not a missing anchor).
                if is_blank and (blank_rules.get(ci, "zero") == "not_applicable"
                                 or before_start):
                    na_skipped[ci] = na_skipped.get(ci, 0) + 1
                    if before_start:
                        pre_start_skips[ci] = pre_start_skips.get(ci, 0) + 1
                    elif ci in anchors and as_of[5:7] == f"{anchors[ci]:02d}":
                        anchored[(ci, as_of[:4])] = {
                            "column": label, "letters": col_letters(ci),
                            "row": rowno, "period": as_of[:7],
                            "grain": mapping.get("grain"),
                        }
                    continue
            if derive_mode:
                continue
            require_legal_pair(cls["origin"], cls["presence"],
                               f"row {rowno} col {col_letters(ci)}")
            val = cls["value_num"]
            if val is None and cls["value_text"] is None:
                issues.append(f"row {rowno} col {col_letters(ci)}: no value (skipped)")
                continue
            acct = acct_ids[mapping["account"]]
            met = metric_ids[mapping["metric"]]
            grain = mapping.get("grain", "month-end")
            key = (acct, met, as_of)
            seq = seq_buf.get(key, 0) + 1
            seq_buf[key] = seq
            nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
            h = state_content_hash(acct, met, as_of, seq, val, cls["presence"], cls["origin"])
            if conn.execute("SELECT 1 FROM fact_state WHERE content_hash=?", (h,)).fetchone():
                n_skipped += 1
                continue
            for old in conn.execute(
                    "SELECT natural_key FROM fact_state WHERE natural_key=? AND batch_id<>? "
                    "AND superseded_by_batch_id IS NULL", (nk, batch.batch_id)).fetchall():
                conn.execute("UPDATE fact_state SET superseded_by_batch_id=? WHERE natural_key=?",
                             (batch.batch_id, old[0]))
            conn.execute(
                """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
                   sheet_row_number, value_num, value_text, presence, origin, error_type,
                   period_grain, grain_detail, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (nk, acct, met, as_of, seq, rowno, val, cls["value_text"], cls["presence"],
                 cls["origin"], cls["error_type"], grain, spec.get("grain"), h,
                 source_id, batch.batch_id, now()),
            )
            if cls["presence"] == "zero_from_blank":
                zero_written[ci] = zero_written.get(ci, 0) + 1
            if met == metric_ids.get("TOTAL_ASSETS") and val is not None:
                row_sum += val
            n += 1
        if total_label is not None:
            trec = idx.get(f"{col_letters(rect.resolved[total_label][0])}{rowno}")
            src_total, _ = coerce_num(trec.get("value")) if trec else (None, None)
            if src_total is not None:
                row_totals[as_of] = (row_sum, src_total)
    # closed-account component derived by difference (unchanged semantics)
    for mapping in derived_cols:
        acct = acct_ids[mapping["account"]]
        met = metric_ids[mapping["metric"]]
        grain = mapping.get("grain", "month-end")
        d_presence, d_origin = "estimated", "derived"
        require_legal_pair(d_origin, d_presence, f"derived column {mapping['col']!r}")
        for as_of, (measured_sum, src_total) in sorted(row_totals.items()):
            delta = src_total - measured_sum
            if abs(delta) <= 0.01:
                continue
            seq = seq_buf.get((acct, met, as_of), 0) + 1
            seq_buf[(acct, met, as_of)] = seq
            nk = f"{source_id}|{acct}|{met}|{as_of}|{seq}"
            h = state_content_hash(acct, met, as_of, seq, delta, d_presence, d_origin)
            conn.execute(
                """INSERT INTO fact_state(natural_key, account_id, metric_id, as_of, seq_in_date,
                   sheet_row_number, value_num, value_text, presence, origin, period_grain,
                   grain_detail, verify_note, content_hash, source_id, batch_id, ingested_at)
                   VALUES (?,?,?,?,?,NULL,?,NULL,?,?,?,?,?,?,?,?,?)""",
                (nk, acct, met, as_of, seq, delta, d_presence, d_origin, grain, spec.get("grain"),
                 mapping.get("note"), h, source_id, batch.batch_id, now()),
            )
            n += 1
    # DM-2026-01: absent rows/periods are coverage_calendar's business — declare
    # the tab's expected months, then run the anchored-blank guard against
    # coverage_calendar.expected so a missing observation fails loudly.
    _emit_period_coverage(conn, spec["alias"], spec["tab"], period_months)
    anchored_findings = _anchored_blank_findings(conn, spec, anchored)
    for f in anchored_findings:
        issues.append(
            f"ANCHORED BLANK col {f['letters']} ({f['column']}): period {f['period']} "
            f"is expected for a {f['grain']} metric but blank — no row written; "
            f"a missing observation, never N/A (DM-2026-01)")
    _resolve_col_origin(col_facts)
    n_cols = _write_src_columns(conn, source_id, spec, rect, col_facts, metric_ids, acct_ids)
    if n_skipped:
        issues.append(f"{n_skipped} rows identical to existing current rows — skipped")
    if issues:
        note = "; ".join(issues[:8]) + (f" (+{len(issues) - 8} more)" if len(issues) > 8 else "")
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?",
                     (note, batch.batch_id))
    zero_report = {"columns": [
        {"label": label, "letters": col_letters(ci),
         "zeros": zero_written.get(ci, 0),
         "not_applicable": na_skipped.get(ci, 0),
         "blanks": blank_seen.get(ci, 0),
         "pre_start_skips": pre_start_skips.get(ci, 0),
         "series_start": (series_starts.get(ci) or (None, None))[0]}
        for label, (ci, _hdr, mapping) in sorted(rect.resolved.items(), key=lambda kv: kv[1][0])
        if mapping is not None and mapping.get("role") not in ("as_of", "work_year")
    ]}
    shapes = series_shape_lines(rect, pop_months, blank_rules, series_starts)
    return n, n_cols, {"zero_report": zero_report, "anchored_blanks": anchored_findings,
                       "series_shapes": shapes}


def _row_presence_origin(cells: list) -> tuple:
    """Row-grain (presence, origin) for a family whose row carries several cells.

    ss_earnings_annual carries one presence per row but two value columns. Rule:
    an error anywhere dominates; else a derived/estimated cell; else any measured
    cell keeps the row measurable (a blank companion never downgrades it); a row
    that is blank across every value column is zero_from_blank. origin is the
    most-derived cell's origin (external > derived > copy > entered).
    """
    order = ("external", "derived", "copy", "constant_formula", "entered")
    presences = [c["presence"] for c in cells if c.get("presence")]
    origins = [c["origin"] for c in cells if c.get("origin")]
    if "error" in presences:
        presence = "error"
    elif "estimated" in presences:
        presence = "estimated"
    elif "measured" in presences:
        presence = "measured"
    elif "zero_from_blank" in presences:
        presence = "zero_from_blank"
    else:
        presence = "measured"
    origin = next((o for o in order if o in origins), "entered")
    return presence, origin


def _load_ssa_earnings_structural(conn, batch: Batch, spec: dict, source_id: int, layout: dict,
                                  artifact: dict, rect: _Rect, acct_ids, metric_ids) -> tuple:
    idx = {c["a1"]: c for c in artifact.get("cells", [])}
    ctx = _CellCtx(idx, rect.external_cols, rect.derived_cols, layout, spec)
    col_facts: dict = {}
    # DM-2026-01: blank_means is a per-CELL column rule; this family writes ONE
    # row per work year whose presence spans two value columns, so a not_
    # applicable declaration has no defined meaning here — refuse, never ignore.
    declared_blank_means = layout.get("blank_means") or {}
    if declared_blank_means:
        raise LoadError(
            f"{spec['alias']}: blank_means is not supported for the ssa_earnings "
            f"family (row-grain presence spans two value columns) — declared: "
            f"{sorted(declared_blank_means)}")
    # Same boundary for series_start: this family has no per-column row grain to
    # bound, so a declaration here would be silently inert — refuse, never ignore.
    declared_starts = layout.get("series_start") or {}
    if declared_starts:
        raise LoadError(
            f"{spec['alias']}: series_start is not supported for the ssa_earnings "
            f"family (one row per work year, no per-column row grain) — declared: "
            f"{sorted(declared_starts)}")
    roles = {}
    for label, (ci, _hdr, mapping) in rect.resolved.items():
        if mapping:
            roles[mapping.get("role")] = ci
    n = 0
    years = set()
    issues: list[str] = []
    blank_cells: dict[str, int] = {}
    n_rows_zero = 0
    for rowno, keyv in _live_rows(artifact, rect, spec):
        try:
            work_year = int(float(str(keyv).strip()))
        except (TypeError, ValueError):
            issues.append(f"row {rowno}: work_year unparseable")
            continue
        cells = []
        values: dict = {}
        for role in ("ss_taxed", "medicare_taxed"):
            ci = roles.get(role)
            if ci is None:
                continue
            cell = idx.get(f"{col_letters(ci)}{rowno}") or {"a1": f"{col_letters(ci)}{rowno}",
                                                           "kind": "blank"}
            cls = classify_cell(cell, ci, ctx)
            _apply_cell_facts(col_facts, ci, cls)
            if (cls.get("presence") == "zero_from_blank"
                    and not cls.get("copy_of") and not cls.get("merge_shadow_of")):
                blank_cells[role] = blank_cells.get(role, 0) + 1
            if cls.get("skip_reason"):
                issues.append(f"row {rowno} col {col_letters(ci)}: {cls['skip_reason']}")
                continue
            cells.append(cls)
            values[role] = cls
        presence, origin = _row_presence_origin(cells) if cells else ("zero_from_blank", "entered")
        if presence == "zero_from_blank":
            n_rows_zero += 1
        error_type = next((c["error_type"] for c in cells if c.get("error_type")), None)
        require_legal_pair(origin, presence, f"ss_earnings row {rowno}")
        ss = values.get("ss_taxed", {}).get("value_num")
        med = values.get("medicare_taxed", {}).get("value_num")
        raw_ss = values.get("ss_taxed", {}).get("value_text")
        nk = f"{source_id}|{work_year}"
        conn.execute(
            """INSERT INTO ss_earnings_annual(natural_key, work_year, ss_taxed, medicare_taxed,
               presence, origin, error_type, needs_verify, source_id, batch_id, ingested_at)
               VALUES (?,?,?,?,?,?,?,0,?,?,?)""",
            (nk, work_year, ss if ss is not None else raw_ss, med, presence, origin,
             error_type, source_id, batch.batch_id, now()),
        )
        years.add(work_year)
        n += 1
    _resolve_col_origin(col_facts)
    _write_src_columns(conn, source_id, spec, rect, col_facts, metric_ids, acct_ids)
    coverage(conn, spec["alias"], spec["tab"],
             {str(y): ("loaded" if y in years else "absent-in-source") for y in range(1996, 2026)},
             note="structural read; non-numeric work-year rows refused loudly")
    if issues:
        note = "; ".join(issues[:8]) + (f" (+{len(issues) - 8} more)" if len(issues) > 8 else "")
        conn.execute("UPDATE load_batch SET note=COALESCE(note,'')||' | '||? WHERE batch_id=?",
                     (note, batch.batch_id))
    zero_report = {
        "columns": [
            {"label": role, "letters": col_letters(ci), "zeros": blank_cells.get(role, 0),
             "not_applicable": 0, "blanks": blank_cells.get(role, 0)}
            for role, ci in sorted(roles.items(), key=lambda kv: kv[1])
            if role in ("ss_taxed", "medicare_taxed")
        ],
        "row_zero_from_blank": n_rows_zero,
    }
    return n, {"zero_report": zero_report, "anchored_blanks": []}


def load_structural_spec(conn, batch: Batch, spec: dict, allow: dict, acct_ids, metric_ids) -> dict:
    """P2 entry: one curation spec -> the store via its snapshot artifact."""
    source_id = ensure_source(conn, spec)
    ensure_sentinels(conn, source_id)
    artifact = None
    try:
        artifact = _read_artifact(spec)
        _validate_artifact_identity(spec, artifact)
        alias_base = spec["alias"].split(":", 1)[0]
        _src_key, _tab_key, layout = allow_list_entry(
            allow, alias_base, artifact.get("tab") or spec.get("tab"), spec["alias"])
        rect = declared_rectangle(spec, layout, artifact)
        assert_artifact_coverage(artifact, rect, spec["alias"])
        assert_shape(artifact, rect, layout, spec)
        if spec["family"] == "state":
            n, n_cols, extras = _load_state_structural(conn, batch, spec, source_id, layout,
                                                       artifact, rect, acct_ids, metric_ids)
        elif spec["family"] == "ssa_earnings":
            n, extras = _load_ssa_earnings_structural(conn, batch, spec, source_id, layout,
                                                      artifact, rect, acct_ids, metric_ids)
            n_cols = None
        else:
            raise LoadError(f"{spec['alias']}: structural reader has no implementation for "
                            f"family {spec['family']!r} (P2 first wave is stats + ss_earning)")
        _print_blank_report(spec["alias"], extras)
        return {"rows": n, "quarantined": False, "src_columns": n_cols,
                "blank_report": extras.get("zero_report"),
                "anchored_blanks": extras.get("anchored_blanks", []),
                "series_shapes": extras.get("series_shapes", []),
                "artifact_sha256": artifact.get("artifact_sha256"),
                "artifact": str(spec["artifact"])}
    except Quarantine as q:
        _quarantine(conn, batch, spec, artifact, q)
        return {"rows": 0, "quarantined": True, "rule": q.rule, "detail": q.detail}
