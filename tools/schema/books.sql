-- books.db schema — v0.2.5 (2026-09-12) · author: Roth (single-threaded, per ratified fix order)
-- Requirement set: .scratch/schema-review/{CONVERGENCE,leg1-semantics,leg2-adversarial,leg3-purpose}.md
-- Blueprint: docs/superpowers/plans/2026-09-07-schema-v0.2.md
-- P0 blueprint: docs/superpowers/plans/2026-09-12-structural-prefetch-v0.3.md §2/§4/§5/§8
-- METHOD ONLY: no financial values, no account numbers.
--
-- v0.2.4 (2026-09-08, tax-scan): tax_year_facts gains the return line items the
-- Q2 marginal-rate work needs — taxable_income, total_tax, std_deduction,
-- ss_wages, state_income_tax — all nullable REAL with typeof guards (additive only).
--
-- v0.2.5 (2026-09-12, structural pre-fetch P0): the presence vocabulary gains
-- 'zero_from_blank' (a blank inside the ingest rectangle is a STATED zero, not a
-- measurement). The four row-level state families — fact_state, holding_state,
-- ss_earnings_annual, ss_benefit_estimates — carry presence + nullable origin +
-- nullable error_type and a composite CHECK over the legal (origin, presence)
-- pairs (blueprint §4, expanded conjunctively because SQLite forbids row-value IN
-- inside CHECK). holding_state also gains the needs_verify it never had. src_column
-- gains the column-grain derivation fields (origin, derivation_kind, formula_shape,
-- copy_of, role) — nullable, additive; nothing has ever written to src_column, so
-- there is no rebuild cost. ERRORS are represented as: canonical token (#NAME?,
-- #REF!, ...) in value_text AND presence='error' AND error_type — fact_state's
-- one-of value CHECK is deliberately UNCHANGED; value_text carrying the token
-- satisfies it.
--
-- SLICE B (view contract, blueprint v0.3 section 5) — APPLIED TO THIS SCRIPT WITH NO
-- VERSION BUMP, on instruction; the COS sequences the bump once the concurrent leg
-- lands. The READ SURFACE is now honest about presence and origin: v_state_current
-- exposes presence/origin/error_type plus the column-grain derivation_kind
-- attributed from src_column; v_net_worth gained a composition breakdown and its
-- additive total excludes copy and error; v_state_conflicts and v_holding_current
-- expose presence/origin/error_type. A store built from an earlier copy of this file
-- therefore carries DIFFERENT view DDL: it must be rebuilt (or have its views
-- recreated) before it agrees with this script. Tables and CHECKs are UNTOUCHED —
-- this is a view-only change. See .scratch/sliceb/report.md.
--
-- APPLICATION RULES
--   * Apply to a FRESH store only. No IF NOT EXISTS anywhere: re-application fails
--     loudly by design. Migration path is rebuild-from-Drive, never ALTER-in-place
--     (the one sanctioned exception: v0.2.3 → v0.2.4 added the five tax line-item
--     columns via ALTER, verified by sqlite_master parity against this script).
--   * v0.2.5 is ADDITIVE-ALTER-able for its new COLUMNS, but it also WIDENS the
--     presence CHECK and adds composite pair CHECKs. A CHECK change has no ALTER
--     statement in SQLite — so an existing v0.2.4 store is migrated by REBUILDING
--     each affected table (create new -> copy -> drop old -> rename -> recreate
--     indexes), never by ALTER-in-place. The P0 parity harness must therefore
--     compare a REBUILT table against a FRESHLY CREATED one (sqlite_master DDL +
--     row data) — not against an ALTER diff.
--   * Every connection MUST set PRAGMA foreign_keys=ON (per-connection in SQLite);
--     the loader asserts it plus _schema_meta.schema_version='v0.2.5' on connect.
--
-- IDENTITY MODEL (blueprint D1/D2)
--   * natural_key: SOURCE-SCOPED business identity constructed at ingest
--     (src|account|metric|as_of|ordinal, or src|account|date|ordinal|amount-shape).
--     UNIQUE(natural_key, batch_id) => two sources may each carry a row for the same
--     business fact (competing evidence, copy-forward seams), and re-ingest versions
--     rows instead of aborting/splicing/destroying (B3/B4).
--   * Exact cross-source duplicates are blocked by content_hash UNIQUE on fact_state
--     (hashes cover the value, so same-day pairs with different values never collide)
--     and by the per-source dedupe_rule applied at ingest + dedupe_log on the event
--     side (B1).
--   * source_id/batch_id/ingested_at = lineage, never identity.
--   * superseded_by_batch_id marks rows a newer load of the same source replaced;
--     current = superseded_by_batch_id IS NULL (B3).
--   * v_state_current resolves by declared source precedence, then sheet recency,
--     then batch, then seq_in_date (last event of the day, within one source) (B2/U-4),
--     and only from each source's LATEST batch for the (account, metric, as_of) slice —
--     so a re-ingest supersedes its slice by construction, never by loader bookkeeping
--     (panel v0.2 round: P03).
--
-- LOADER CONTRACT (enforced by the harness, not by comments):
--   * content_hash recipe: H(account_id | metric_id | as_of | seq_in_date |
--     value_num | value_text | presence | origin) — ordinal IN, source identity
--     OUT. v0.2.5 CONTRACT CHANGE: presence and origin joined the recipe — under
--     v0.2.4 a measured `0` and a zero_from_blank `0` hashed IDENTICALLY and were
--     silently deduped, so a reclassification could never survive the re-ingest
--     probe (blueprint §5). Equal-valued same-day pairs differ by ordinal and
--     coexist; cross-source identical rows collide on the partial UNIQUE index and
--     are blocked (B1).
--   * A batch loads a COMPLETE slice (one tab of one source). Re-ingest, in ONE
--     transaction: (1) mark every prior row of that slice superseded_by_batch_id,
--     (2) apply src_tab.dedupe_rule across sources, logging to dedupe_log,
--     (3) INSERT the new rows. Unchanged re-ingests therefore succeed as fresh
--     versions (old rows leave the partial hash index the moment they are marked).
--   * seq_in_date is DERIVED by the loader from sheet_row_number per
--     src_tab.row_order (ascending/descending/unsorted); the schema stores the
--     raw pair so the derivation is auditable (B4).
--   * date cells must roundtrip: a date string is only stored when
--     date(x) = x (kills '2024-02-31' → SQLite normalizes it to '2024-03-02').
--   * UNMAPPED txn types COUNT as cash in v_cash_flow (money is real, its type
--     is unresolved); the unmapped bucket is always visible by txn_type + raw_label.

-- ---------------------------------------------------------------- governance
CREATE TABLE _schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO _schema_meta(key, value) VALUES ('schema_version', 'v0.2.5');

CREATE TABLE load_batch (
  batch_id     INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  tool_version TEXT,
  status       TEXT NOT NULL CHECK (status IN ('complete','partial','failed')),
  note         TEXT
);

-- ---------------------------------------------------------------- allow-list (blueprint D3)
CREATE TABLE src_ref (
  source_id      INTEGER PRIMARY KEY,
  alias          TEXT NOT NULL UNIQUE,             -- never a filename
  drive_id       TEXT NOT NULL,
  source_kind    TEXT NOT NULL CHECK (source_kind IN ('native-google-sheet','drive-file')),
  read_path      TEXT NOT NULL CHECK (read_path IN ('sheets.values.get','files.get alt=media')),
  precedence     INTEGER NOT NULL CHECK (precedence BETWEEN 1 AND 999), -- lower = more authoritative; NO default: must be curated (fail-loud)
  role           TEXT NOT NULL CHECK (role IN ('raw','reference','documentation','derived','scratch','worksheet','duplicate','deferred')),
  sheet_modified TEXT CHECK (sheet_modified IS NULL OR (sheet_modified GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND date(substr(sheet_modified,1,10)) = substr(sheet_modified,1,10))),
  CHECK ((source_kind='native-google-sheet') = (read_path='sheets.values.get'))
);

CREATE TABLE src_tab (
  tab_id        INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  tab           TEXT NOT NULL,
  block         TEXT NOT NULL DEFAULT '',           -- '' = whole tab; named block otherwise
  role          TEXT NOT NULL CHECK (role IN ('raw','reference','documentation','derived','scratch','worksheet','duplicate','deferred')),
  header_state  TEXT NOT NULL DEFAULT 'unresolved' CHECK (header_state IN ('confirmed','unresolved','not-applicable')),
  header_row    INTEGER CHECK (header_row IS NULL OR header_row >= 1),
  dedupe_rule   TEXT NOT NULL CHECK (dedupe_rule IN ('disjoint_by_key','natural_key_prefer_latest','copy_forward_seams','none')),
  row_order     TEXT NOT NULL CHECK (row_order IN ('ascending-date','descending-date','unsorted')),
  grain         TEXT,                               -- declared source grain for validation
  note          TEXT,
  UNIQUE (source_id, tab, block),
  CHECK ((header_state='confirmed') = (header_row IS NOT NULL AND header_row >= 1))
);

-- v0.2.5: derivation is a COLUMN-grain fact (blueprint §2) — these five fields are
-- nullable and additive; nothing had ever written to src_column, so no rebuild cost.
CREATE TABLE src_column (
  map_id          INTEGER PRIMARY KEY,
  tab_id          INTEGER NOT NULL REFERENCES src_tab ON DELETE RESTRICT,
  col_index       INTEGER NOT NULL CHECK (col_index >= 0),
  header_text     TEXT NOT NULL,
  header_occurrence INTEGER NOT NULL DEFAULT 1 CHECK (header_occurrence >= 1),
  account_id      INTEGER REFERENCES dim_account,
  metric_id       INTEGER REFERENCES dim_metric,
  unit            TEXT,
  origin          TEXT CHECK (origin IS NULL OR origin IN ('entered','copy','constant_formula','derived','external','key')),
  derivation_kind TEXT,   -- §4: a SET, not a partition — stored as a NORMALISED COMMA-SEPARATED
                          -- STRING: lower-case tokens, alphabetically sorted, joined by ',' with no
                          -- spaces (e.g. 'aggregate,chain'). Normalisation is the loader's job; the
                          -- store keeps the canonical string and compares it verbatim.
  formula_shape   TEXT,   -- masked structural shape of the column's formula (shape, never values)
  copy_of         TEXT,   -- pure-reference lineage: the source cell/column this column copies (§4)
  role            TEXT CHECK (role IS NULL OR role IN ('value','key','derived','external','copy','scratch')),
  UNIQUE (tab_id, col_index, header_occurrence)
);
-- NOTE: dim_account/dim_metric are created below; SQLite resolves FKs at runtime,
-- so src_column may reference tables defined later in the script.

-- ---------------------------------------------------------------- dimensions
CREATE TABLE dim_account (
  account_id   INTEGER PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,                -- neutral token, curated
  institution  TEXT NOT NULL,
  registration TEXT NOT NULL CHECK (registration IN ('taxable','401k','trad-ira','roth','hsa','checking','card','pension','other','unsettled')),
  entity       TEXT NOT NULL CHECK (entity IN ('Joe','LLC')),
  purpose      TEXT NOT NULL CHECK (purpose IN ('floor','growth','reserve','unsettled')),
  notes        TEXT
);

CREATE TABLE dim_metric (
  metric_id       INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,
  is_flow         INTEGER NOT NULL CHECK (is_flow IN (0,1)),          -- flow/delta vs stock; no silent default
  is_year_relative INTEGER NOT NULL CHECK (is_year_relative IN (0,1)), -- P/L & cost-basis: never merge across seams
  polarity        TEXT NOT NULL DEFAULT 'unknown' CHECK (polarity IN ('asset','liability','flow','unknown')),
  unit            TEXT NOT NULL DEFAULT 'USD',
  scope_flag      TEXT,                              -- ex-holding scopes are NOT accounts
  methodology     TEXT                               -- e.g. NOTES!'s "P/L counts dividend as cost"
);

CREATE TABLE dim_txn_type (
  txn_type_id    INTEGER PRIMARY KEY,
  source_id      INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  raw_label      TEXT NOT NULL,                     -- normalized (trim/case) at ingest
  canonical      TEXT NOT NULL CHECK (canonical IN ('UNMAPPED','CONTRIBUTION','DIVIDEND','INTEREST','PURCHASE','SALE','FEE','TRANSFER','PAYMENT','DEPOSIT','WITHDRAWAL','TAX','BALANCE_FORWARD','CHANGE_IN_VALUE','OTHER')),
  is_informational INTEGER NOT NULL DEFAULT 0 CHECK (is_informational IN (0,1)),  -- single authoritative copy (B6.5)
  UNIQUE (source_id, raw_label)
);

CREATE TABLE dim_category (
  category_id   INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  source_label  TEXT NOT NULL,                      -- normalized at ingest
  canonical     TEXT NOT NULL,
  spending_class TEXT NOT NULL CHECK (spending_class IN ('floor','discretionary','transfer','unsettled')),  -- U-1
  UNIQUE (source_id, source_label)
);

CREATE TABLE dim_security (
  security_id   INTEGER PRIMARY KEY,
  ticker        TEXT NOT NULL UNIQUE,
  exchange      TEXT,                                -- source prefix (NYSE:, INDEXSP:...) stripped from the ticker
  name          TEXT,
  asset_class   TEXT CHECK (asset_class IN ('equity','bond','cash','fund','other')),
  expense_ratio REAL CHECK (expense_ratio IS NULL OR typeof(expense_ratio)='real'),
  note          TEXT                                 -- curated dim: provenance by curation note
);

CREATE TABLE dim_tax_bracket (                        -- U-6: bracket bounds as data, not constants
  tax_year      INTEGER NOT NULL CHECK (tax_year BETWEEN 1900 AND 2100),
  filing_status TEXT NOT NULL CHECK (filing_status IN ('single','head-of-household','married-joint','married-separate')),
  schedule      TEXT NOT NULL CHECK (schedule IN ('ordinary','ltcg')),
  ordinal       INTEGER NOT NULL CHECK (ordinal >= 1),
  upper_limit   REAL CHECK (upper_limit IS NULL OR typeof(upper_limit)='real'),
  rate          REAL NOT NULL CHECK (typeof(rate)='real'),
  source        TEXT NOT NULL CHECK (source IN ('irs','estimate')),   -- future-year bounds are estimates
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  ingested_at   TEXT NOT NULL,
  PRIMARY KEY (tax_year, filing_status, schedule, ordinal)
);

-- ---------------------------------------------------------------- fact: state series
CREATE TABLE fact_state (
  state_id        INTEGER PRIMARY KEY,
  natural_key     TEXT NOT NULL,                     -- source-scoped business identity (D1)
  account_id      INTEGER NOT NULL REFERENCES dim_account ON DELETE RESTRICT,
  metric_id       INTEGER NOT NULL REFERENCES dim_metric ON DELETE RESTRICT,
  as_of           TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(as_of) = as_of),
  seq_in_date     INTEGER NOT NULL CHECK (seq_in_date > 0 AND seq_in_date = CAST(seq_in_date AS INTEGER)),
  sheet_row_number INTEGER,                          -- raw, verifiable (B4)
  value_num       REAL CHECK (value_num IS NULL OR typeof(value_num)='real'),
  value_text      TEXT,
  presence        TEXT NOT NULL DEFAULT 'measured' CHECK (presence IN ('measured','estimated','zero_from_blank','error')),
  origin          TEXT CHECK (origin IS NULL OR origin IN ('entered','copy','constant_formula','derived','external','key')),
  error_type      TEXT,                              -- canonical error token (#NAME?, #REF!, ...) when presence='error'
  period_grain    TEXT NOT NULL CHECK (period_grain IN ('daily','near-daily','weekly','monthly','month-end','quarterly','annual','unknown')),
  grain_detail    TEXT,                              -- 'Friday-anchored', 'bridge', 'mixed monthly to weekly' …
  event_group_id  INTEGER CHECK (event_group_id IS NULL OR event_group_id > 0),  -- same-day event chains (TIPS pair): delta between rows is derivable
  content_hash    TEXT NOT NULL,
  needs_verify    INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),   -- U-5: uniform verify flag
  verify_note     TEXT,
  source_id       INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,      -- lineage, not identity
  batch_id        INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at     TEXT NOT NULL,
  UNIQUE (natural_key, batch_id),
  -- ERROR REPRESENTATION (§5): an errored cell puts its canonical token (#NAME?,
  -- #REF!, ...) in value_text AND sets presence='error' AND error_type. The one-of
  -- value CHECK below is deliberately UNCHANGED by v0.2.5 — value_text carrying the
  -- token satisfies it; no error row is unrepresentable any more.
  CHECK ((value_num IS NULL) <> (value_text IS NULL)),
  -- LEGAL (origin, presence) PAIRS — blueprint §4, encoded as an explicit list of
  -- expanded conjuncts (SQLite forbids row-value IN inside a CHECK). `key` carries
  -- NO pair: a key column is row addressing, never a fact row. (external,'error') IS
  -- present — this comment previously claimed it was absent, contradicting the CHECK;
  -- corrected 2026-09-12. §4's precedence rule makes external_links membership
  -- override kind, so an errored cross-sheet pull is external x error, and a
  -- declared-external column must be able to hold measured literals, estimated
  -- results and errors alike (the Stats/Taxes E-H case). The same list lives in
  -- loader21.LEGAL_ORIGIN_PRESENCE_PAIRS and is enforced at load time too, because
  -- origin's column-grain default lives on src_column while presence is row-grain —
  -- a cross-table rule SQL cannot see. P0 harness keeps the two lists equal.
  CONSTRAINT ck_fact_state_origin_presence CHECK (
    origin IS NULL OR presence IS NULL
    OR (origin='entered' AND presence='measured')
    OR (origin='entered' AND presence='zero_from_blank')
    OR (origin='constant_formula' AND presence='measured')
    OR (origin='copy' AND presence='measured')
    OR (origin='copy' AND presence='zero_from_blank')
    OR (origin='copy' AND presence='estimated')
    OR (origin='copy' AND presence='error')
    OR (origin='derived' AND presence='estimated')
    OR (origin='derived' AND presence='error')
    OR (origin='external' AND presence='measured')
    OR (origin='external' AND presence='estimated')
    OR (origin='external' AND presence='error')
  )
);
CREATE UNIQUE INDEX ux_fact_state_hash ON fact_state (content_hash) WHERE superseded_by_batch_id IS NULL;
-- PARTIAL (superseded-aware): marked rows leave the index before the replacement batch
-- inserts, so unchanged re-ingests succeed as fresh versions (P02), equal-valued
-- same-day pairs coexist via ordinal-in-hash (P01), and cross-source identical
-- rows are still blocked (B1).
CREATE INDEX ix_fact_state_lookup ON fact_state (account_id, metric_id, as_of);

-- ---------------------------------------------------------------- fact: ledger / events
CREATE TABLE fact_event (
  event_id        INTEGER PRIMARY KEY,
  natural_key     TEXT NOT NULL,
  business_txn_id TEXT,                             -- the source's own durable id (B7)
  account_id      INTEGER NOT NULL REFERENCES dim_account ON DELETE RESTRICT,
  event_date      TEXT NOT NULL CHECK (event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(event_date) = event_date),
  seq_in_date     INTEGER NOT NULL CHECK (seq_in_date > 0 AND seq_in_date = CAST(seq_in_date AS INTEGER)),
  sheet_row_number INTEGER,
  txn_type_id     INTEGER NOT NULL REFERENCES dim_txn_type ON DELETE RESTRICT,   -- UNMAPPED sentinel, never NULL (M5)
  category_id     INTEGER NOT NULL REFERENCES dim_category ON DELETE RESTRICT,
  raw_label       TEXT,                             -- verbatim source label, for auditability (M5)
  description     TEXT,                             -- free text, no amounts
  amount          REAL CHECK (amount IS NULL OR typeof(amount)='real'),
  quantity        REAL CHECK (quantity IS NULL OR typeof(quantity)='real'),
  price           REAL CHECK (price IS NULL OR typeof(price)='real'),
  fee             REAL CHECK (fee IS NULL OR typeof(fee)='real'),
  unit            TEXT NOT NULL DEFAULT 'USD' CHECK (unit IN ('USD','shares','kWh','units','unknown')),
  quality         TEXT CHECK (quality IN ('estimated','actual')),               -- m9
  event_group_id  INTEGER CHECK (event_group_id IS NULL OR event_group_id > 0), -- links conversion/transfer legs
  counterparty    TEXT,
  security_id     INTEGER REFERENCES dim_security ON DELETE RESTRICT,
  content_hash    TEXT NOT NULL,
  needs_verify    INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  verify_note     TEXT,
  source_id       INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id        INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at     TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);
CREATE INDEX ix_fact_event_date ON fact_event (account_id, event_date);
CREATE INDEX ix_fact_event_txn ON fact_event (business_txn_id) WHERE business_txn_id IS NOT NULL;

-- ---------------------------------------------------------------- tax lots
CREATE TABLE position_lot (
  lot_id        INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  account_id    INTEGER NOT NULL REFERENCES dim_account ON DELETE RESTRICT,
  security_id   INTEGER NOT NULL REFERENCES dim_security ON DELETE RESTRICT,
  opened_on     TEXT CHECK (opened_on IS NULL OR (opened_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(opened_on) = opened_on)),
  lot_seq       INTEGER NOT NULL DEFAULT 1 CHECK (lot_seq >= 1),   -- same-day same-security discriminator (M6)
  quantity      REAL CHECK (quantity IS NULL OR typeof(quantity)='real'),
  cost_basis    REAL CHECK (cost_basis IS NULL OR typeof(cost_basis)='real'),
  acquired_via  TEXT,
  closed_on     TEXT CHECK (closed_on IS NULL OR (closed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(closed_on) = closed_on)),
  road_ref      TEXT,
  content_hash  TEXT NOT NULL,
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  verify_note   TEXT,
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);

-- ---------------------------------------------------------------- SSA / tax facts (fix order #5)
CREATE TABLE ss_earnings_annual (
  id              INTEGER PRIMARY KEY,
  natural_key     TEXT NOT NULL,
  work_year       INTEGER NOT NULL CHECK (work_year BETWEEN 1900 AND 2100),
  ss_taxed        REAL CHECK (ss_taxed IS NULL OR typeof(ss_taxed)='real'),
  medicare_taxed  REAL CHECK (medicare_taxed IS NULL OR typeof(medicare_taxed)='real'),
  ss_rate         REAL CHECK (ss_rate IS NULL OR typeof(ss_rate)='real'),
  medicare_rate   REAL CHECK (medicare_rate IS NULL OR typeof(medicare_rate)='real'),
  medicare_addl_rate REAL CHECK (medicare_addl_rate IS NULL OR typeof(medicare_addl_rate)='real'),
  fica_total      REAL CHECK (fica_total IS NULL OR typeof(fica_total)='real'),  -- source-carried derived sum; cross-check only, never merged
  presence        TEXT NOT NULL DEFAULT 'measured' CHECK (presence IN ('measured','estimated','zero_from_blank','error')),
  origin          TEXT CHECK (origin IS NULL OR origin IN ('entered','copy','constant_formula','derived','external','key')),
  error_type      TEXT,                              -- canonical error token when presence='error' (v0.2.5)
  needs_verify    INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  verify_note     TEXT,
  source_id       INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id        INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at     TEXT NOT NULL,
  UNIQUE (natural_key, batch_id),
  -- v0.2.5 legal (origin, presence) pairs — §4 list, literally identical to
  -- ck_fact_state_origin_presence (the P0 harness asserts both DDL and semantics).
  CONSTRAINT ck_ss_earnings_origin_presence CHECK (
    origin IS NULL OR presence IS NULL
    OR (origin='entered' AND presence='measured')
    OR (origin='entered' AND presence='zero_from_blank')
    OR (origin='constant_formula' AND presence='measured')
    OR (origin='copy' AND presence='measured')
    OR (origin='copy' AND presence='zero_from_blank')
    OR (origin='copy' AND presence='estimated')
    OR (origin='copy' AND presence='error')
    OR (origin='derived' AND presence='estimated')
    OR (origin='derived' AND presence='error')
    OR (origin='external' AND presence='measured')
    OR (origin='external' AND presence='estimated')
    OR (origin='external' AND presence='error')
  )
);
-- medicare_only is DERIVED (medicare_taxed - ss_taxed): never stored.

CREATE TABLE ss_taxes_paid_annual (
  id            INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  work_year     INTEGER NOT NULL CHECK (work_year BETWEEN 1900 AND 2100),
  taxes_paid    REAL CHECK (taxes_paid IS NULL OR typeof(taxes_paid)='real'),
  est_total_eoy REAL CHECK (est_total_eoy IS NULL OR typeof(est_total_eoy)='real'),
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  verify_note   TEXT,
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);

CREATE TABLE ss_benefit_estimates (
  id            INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  work_year     INTEGER NOT NULL CHECK (work_year BETWEEN 1900 AND 2100),
  claim_basis   TEXT NOT NULL CHECK (claim_basis IN ('Disability','Age62','Age63','Age64','Age65','Age66','Age67','Age68','Age69','Age70')),
  amount        REAL NOT NULL CHECK (typeof(amount)='real'),
  unit          TEXT NOT NULL CHECK (unit IN ('monthly','annual')),
  is_estimate   INTEGER NOT NULL CHECK (is_estimate IN (0,1)),   -- no default: loader must decide (finding 18)
  presence      TEXT NOT NULL DEFAULT 'measured' CHECK (presence IN ('measured','estimated','zero_from_blank','error')),
  origin        TEXT CHECK (origin IS NULL OR origin IN ('entered','copy','constant_formula','derived','external','key')),
  error_type    TEXT,                              -- canonical error token when presence='error' (v0.2.5)
  basis_date    TEXT CHECK (basis_date IS NULL OR (basis_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(basis_date) = basis_date)),
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id),
  -- v0.2.5 legal (origin, presence) pairs — §4 list, literally identical to
  -- ck_fact_state_origin_presence (the P0 harness asserts both DDL and semantics).
  CONSTRAINT ck_ss_benefit_origin_presence CHECK (
    origin IS NULL OR presence IS NULL
    OR (origin='entered' AND presence='measured')
    OR (origin='entered' AND presence='zero_from_blank')
    OR (origin='constant_formula' AND presence='measured')
    OR (origin='copy' AND presence='measured')
    OR (origin='copy' AND presence='zero_from_blank')
    OR (origin='copy' AND presence='estimated')
    OR (origin='copy' AND presence='error')
    OR (origin='derived' AND presence='estimated')
    OR (origin='derived' AND presence='error')
    OR (origin='external' AND presence='measured')
    OR (origin='external' AND presence='estimated')
    OR (origin='external' AND presence='error')
  )
);

CREATE TABLE ss_cola (
  id            INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  cola_period   TEXT NOT NULL,                       -- raw 'mmm-yy' label, kept verbatim
  period_start  TEXT CHECK (period_start IS NULL OR (period_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(period_start) = period_start)),
  pct           REAL NOT NULL CHECK (typeof(pct)='real'),
  block         TEXT NOT NULL CHECK (block IN ('primary','supplement')),   -- overlapping blocks coexist (finding 3)
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);

CREATE TABLE irs_payments (
  id            INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  payment_date  TEXT NOT NULL CHECK (payment_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(payment_date) = payment_date),
  is_scheduled  INTEGER NOT NULL DEFAULT 0 CHECK (is_scheduled IN (0,1)),  -- "flag future scheduled rows"
  amount        REAL CHECK (amount IS NULL OR typeof(amount)='real'),
  description   TEXT,
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);

CREATE TABLE meter_reading (                         -- not fact_event: cumulative kWh register, all-TEXT source
  id            INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,
  meter         TEXT NOT NULL,
  read_date     TEXT NOT NULL CHECK (read_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(read_date) = read_date),
  reading       REAL NOT NULL CHECK (typeof(reading)='real'),
  unit          TEXT NOT NULL DEFAULT 'kWh',
  is_cumulative INTEGER NOT NULL DEFAULT 1 CHECK (is_cumulative IN (0,1)),
  quality       TEXT CHECK (quality IN ('estimated','actual')),
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  source_id     INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);

CREATE TABLE tax_year_facts (
  id              INTEGER PRIMARY KEY,
  natural_key     TEXT NOT NULL,
  tax_year        INTEGER NOT NULL CHECK (tax_year BETWEEN 1900 AND 2100),
  filing_status   TEXT NOT NULL CHECK (filing_status IN ('single','head-of-household','married-joint','married-separate')),
  agi             REAL CHECK (agi IS NULL OR typeof(agi)='real'),
  magi            REAL CHECK (magi IS NULL OR typeof(magi)='real'),
  taxable_income  REAL CHECK (taxable_income IS NULL OR typeof(taxable_income)='real'),
  total_tax       REAL CHECK (total_tax IS NULL OR typeof(total_tax)='real'),
  std_deduction   REAL CHECK (std_deduction IS NULL OR typeof(std_deduction)='real'),
  ss_wages        REAL CHECK (ss_wages IS NULL OR typeof(ss_wages)='real'),
  state_income_tax REAL CHECK (state_income_tax IS NULL OR typeof(state_income_tax)='real'),
  marginal_bracket TEXT,
  ltcg_rate       REAL CHECK (ltcg_rate IS NULL OR typeof(ltcg_rate)='real'),
  state           TEXT,
  rmd_due         REAL CHECK (rmd_due IS NULL OR typeof(rmd_due)='real'),
  ss_taxed_share  REAL CHECK (ss_taxed_share IS NULL OR typeof(ss_taxed_share)='real'),
  source          TEXT NOT NULL CHECK (source IN ('filed-return','irs-transcript','tax-prep-pdf','estimate')),
  is_estimate     INTEGER NOT NULL CHECK (is_estimate IN (0,1)),
  needs_verify    INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  as_of           TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(as_of) = as_of),
  source_id       INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id        INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at     TEXT NOT NULL,
  UNIQUE (natural_key, batch_id)
);
-- roth_conversion_room removed: stored derived value would silently rot (O-2/N4);
-- bracket room is computed from dim_tax_bracket.

-- ---------------------------------------------------------------- decumulation substrate (Task #8)
-- Versionable like every fact family: Q1's parameters legitimately change each year
-- (Trustees Report, owner rulings) and retractions must have a home (panel v0.2 C1).
CREATE TABLE assumption_register (
  assumption_id INTEGER PRIMARY KEY,
  natural_key   TEXT NOT NULL,                       -- 'src|key' — source-scoped so competing vintages coexist
  key           TEXT NOT NULL,                       -- semantic key, e.g. 'ssa.go_broke.year'
  value_num     REAL CHECK (value_num IS NULL OR typeof(value_num)='real'),
  value_text    TEXT,
  unit          TEXT,
  source        TEXT NOT NULL,                       -- e.g. '2026-trustees-report','owner-goal-seek','owner-typed'
  as_of         TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(as_of) = as_of),
  review_by     TEXT,
  needs_verify  INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  verify_note   TEXT,
  note          TEXT,
  batch_id      INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at   TEXT NOT NULL,
  UNIQUE (natural_key, batch_id),
  CHECK ((value_num IS NULL) <> (value_text IS NULL))
);
CREATE INDEX ix_assumption_key ON assumption_register (key);

-- Current assumption per semantic key: highest batch wins; no key-suffix convention.
CREATE VIEW v_assumption_current AS
WITH cur AS (
  SELECT a.*, ROW_NUMBER() OVER (PARTITION BY a.key ORDER BY a.batch_id DESC) AS rn
  FROM assumption_register a
  WHERE a.superseded_by_batch_id IS NULL
)
SELECT assumption_id, key, value_num, value_text, unit, source, as_of, review_by,
       needs_verify, verify_note, note, batch_id, ingested_at
FROM cur WHERE rn = 1;

-- ---------------------------------------------------------------- governance facts
CREATE TABLE dedupe_log (  dedupe_id           INTEGER PRIMARY KEY,
  batch_id            INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  rule                TEXT NOT NULL CHECK (rule IN ('natural_key_prefer_latest','copy_forward_seams')),
  source_alias        TEXT NOT NULL REFERENCES src_ref(alias) ON DELETE RESTRICT,
  suppressed_natural_key TEXT NOT NULL,
  kept_natural_key    TEXT,
  note                TEXT,
  at                  TEXT NOT NULL
);

CREATE TABLE data_defects (
  defect_id    INTEGER PRIMARY KEY,
  source_alias TEXT NOT NULL REFERENCES src_ref(alias) ON DELETE RESTRICT,
  tab          TEXT NOT NULL DEFAULT '',
  cell_ref     TEXT NOT NULL DEFAULT '',
  what         TEXT NOT NULL,
  evidence     TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('OPEN','ACCEPT','NOT-A-DEFECT','FIXED-VERIFIED')),
  ruling       TEXT,
  verified_at  TEXT CHECK (verified_at IS NULL OR (verified_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(verified_at) = verified_at)),
  CHECK (status <> 'FIXED-VERIFIED' OR verified_at IS NOT NULL),
  UNIQUE (source_alias, tab, cell_ref, what)
);

CREATE TABLE coverage_calendar (
  coverage_id  INTEGER PRIMARY KEY,
  source_alias TEXT NOT NULL REFERENCES src_ref(alias) ON DELETE RESTRICT,
  tab          TEXT NOT NULL DEFAULT '',
  period       TEXT NOT NULL CHECK (period GLOB '[0-9][0-9][0-9][0-9]' OR period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
  expected     INTEGER NOT NULL DEFAULT 1 CHECK (expected IN (0,1)),
  status       TEXT NOT NULL CHECK (status IN ('not-loaded','loaded-empty','absent-in-source','loaded')),
  note         TEXT,
  UNIQUE (source_alias, tab, period)
);

CREATE TABLE decision_memo_ref (
  id          INTEGER PRIMARY KEY,
  dm_id       TEXT NOT NULL UNIQUE,
  desk        TEXT NOT NULL CHECK (desk IN ('accounting','retirement','portfolio')),
  title       TEXT NOT NULL,
  decided_on  TEXT CHECK (decided_on IS NULL OR (decided_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(decided_on) = decided_on)),
  review_by   TEXT CHECK (review_by IS NULL OR (review_by GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(review_by) = review_by)),
  drive_doc   TEXT,
  ingested_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- views
-- The day's state: declared source precedence, then recency, then last event of the day.
-- Reads ONLY each source's LATEST batch for the (account, metric, as_of) slice, so a
-- re-ingest supersedes its slice by construction (P03) — partial supersession can no
-- longer publish a stale ordinal.
-- Auditable: exposes source_id, batch_id, seq_in_date, ingested_at, value_text.
-- SLICE B (blueprint v0.3 section 5): the trust labels are now part of the published
-- surface, so filtering on them is the DEFAULT, not something a reader has to
-- remember. Exposed per row: presence, origin, error_type.
--   * presence/origin/error_type come straight from the row (row-grain, section 2).
--   * derivation_kind is a COLUMN-grain fact living on src_column, so it is
--     ATTRIBUTED to the row through the only linkage v0.2.5 stores:
--     (source_id, account_id, metric_id). column_map_id names the src_column row the
--     attribution came from; n_column_candidates says whether it was unique, and is
--     stated as 0 when nothing matched — a missing attribution is a NUMBER here, never
--     an absence a reader has to interpret. Zero candidates means the column was never
--     curated, so derivation_kind NULL then means UNKNOWN, never "not derived": the two
--     NULLs (curated-and-plain vs never-curated) stay distinguishable. Absence is never
--     laundered into a value.
--   * Both joins are LEFT joins against a GROUP BY-unique key and a PRIMARY KEY, so
--     the row set is EXACTLY what it was: no row is added, duplicated or dropped.
--   * `composition_class` + `is_additive` state the aggregation rule ONCE, here, so
--     every consumer that sums this view uses the same definition instead of
--     re-inventing the filter (and getting the NULL case wrong). Precedence matters:
--     `copy` is a value of ORIGIN while the other classes label PRESENCE, and
--     (copy, error) is a legal pair in v0.2.5 — a row whose origin is 'copy' is a copy
--     whatever presence it inherited, because a copy inherits its source's presence.
--     ADDITIVE (is_additive=1) = not a declared duplicate and not an error. Note
--     origin is nullable on legacy rows, so the flag (or COALESCE(origin,'') <> 'copy')
--     is the NULL-safe way to filter; a bare `origin <> 'copy'` silently drops them.
-- A reader who wants only what the source actually measured filters
-- presence = 'measured'; a reader who must not divide by fabricated rows filters
-- presence <> 'zero_from_blank'.
CREATE VIEW v_state_current AS
WITH current_rows AS (
  SELECT f.state_id, f.account_id, f.metric_id, f.as_of, f.value_num, f.value_text,
         f.presence, f.origin, f.error_type,
         f.period_grain, f.seq_in_date, f.source_id, f.batch_id, f.ingested_at,
         s.precedence, s.sheet_modified,
         ROW_NUMBER() OVER (
           PARTITION BY f.account_id, f.metric_id, f.as_of
           ORDER BY s.precedence ASC,
                    COALESCE(s.sheet_modified, '') DESC,
                    f.batch_id DESC,
                    f.seq_in_date DESC,
                    f.source_id DESC
         ) AS rn
  FROM fact_state f
  JOIN src_ref s ON s.source_id = f.source_id
  WHERE f.superseded_by_batch_id IS NULL
    AND f.batch_id = (SELECT MAX(f2.batch_id) FROM fact_state f2
                      WHERE f2.source_id = f.source_id
                        AND f2.account_id = f.account_id
                        AND f2.metric_id = f.metric_id
                        AND f2.as_of = f.as_of
                        AND f2.superseded_by_batch_id IS NULL)
),
column_derivation AS (
  SELECT t.source_id, c.account_id, c.metric_id,
         MIN(c.map_id) AS map_id, COUNT(*) AS n_candidates
  FROM src_column c
  JOIN src_tab t ON t.tab_id = c.tab_id
  WHERE c.account_id IS NOT NULL AND c.metric_id IS NOT NULL
    AND (c.role IS NULL OR c.role <> 'key')
  GROUP BY t.source_id, c.account_id, c.metric_id
)
SELECT cr.account_id, cr.metric_id, cr.as_of, cr.value_num, cr.value_text, cr.period_grain,
       cr.seq_in_date, cr.source_id, cr.batch_id, cr.ingested_at,
       cr.presence, cr.origin, cr.error_type,
       CASE WHEN cr.origin = 'copy' THEN 'copy'
            WHEN cr.presence = 'error' THEN 'error'
            ELSE cr.presence END AS composition_class,
       CASE WHEN cr.origin = 'copy' OR cr.presence = 'error' THEN 0 ELSE 1 END AS is_additive,
       COALESCE(cd.n_candidates, 0) AS n_column_candidates,
       cd.map_id       AS column_map_id,
       c2.derivation_kind AS derivation_kind
FROM current_rows cr
LEFT JOIN column_derivation cd
       ON cd.source_id = cr.source_id AND cd.account_id = cr.account_id
      AND cd.metric_id = cr.metric_id
LEFT JOIN src_column c2 ON c2.map_id = cd.map_id
WHERE cr.rn = 1;

-- Days where two or more sources disagree at equal declared authority — the COS
-- curates these (P04/P14: no silent winner by insertion order).
-- SLICE B: a disagreement between a copy and its source, or between a value and an
-- errored cell, is not the same curation problem as two sources stating different
-- measurements — so the labels have to be on this surface too.
CREATE VIEW v_state_conflicts AS
WITH ranked AS (
  SELECT f.account_id, f.metric_id, f.as_of, f.value_num, f.value_text,
         f.presence, f.origin, f.error_type,
         f.source_id, f.batch_id, f.seq_in_date,
         s.precedence, s.sheet_modified,
         ROW_NUMBER() OVER (
           PARTITION BY f.account_id, f.metric_id, f.as_of
           ORDER BY s.precedence ASC,
                    COALESCE(s.sheet_modified, '') DESC,
                    f.batch_id DESC,
                    f.seq_in_date DESC,
                    f.source_id DESC
         ) AS rn
  FROM fact_state f
  JOIN src_ref s ON s.source_id = f.source_id
  WHERE f.superseded_by_batch_id IS NULL
    AND f.batch_id = (SELECT MAX(f2.batch_id) FROM fact_state f2
                      WHERE f2.source_id = f.source_id
                        AND f2.account_id = f.account_id
                        AND f2.metric_id = f.metric_id
                        AND f2.as_of = f.as_of
                        AND f2.superseded_by_batch_id IS NULL)
)
SELECT account_id, metric_id, as_of, value_num, value_text, source_id, batch_id,
       precedence, sheet_modified, presence, origin, error_type
FROM ranked r1
WHERE rn > 1
  AND EXISTS (SELECT 1 FROM ranked r2
              WHERE r2.rn = 1
                AND r2.account_id = r1.account_id AND r2.metric_id = r1.metric_id
                AND r2.as_of = r1.as_of
                AND r2.precedence = r1.precedence
                AND COALESCE(r2.sheet_modified,'') = COALESCE(r1.sheet_modified,''));

-- The published definition of money-that-counts (finding 11 / B6.5).
-- Per-source latest batch for the (account, date) slice (P09/P10: re-ingest replaces
-- the day's events by construction). UNMAPPED counts as cash — money is real, its type
-- is unresolved; the bucket is always visible via txn_type + raw_label.
-- SLICE B, FLAGGED NOT FAKED: there is NOTHING here to expose. fact_event carries no
-- presence/origin — the ratified scope (blueprint v0.3 section 2) put presence on the
-- four STATE families only, and the event family is not one of them. So the copy/error
-- anti-double-count rule has no surface on this view, and cash flow is qualified by
-- `quality` and `is_informational` instead. Giving fact_event the same labels is a
-- schema change (CHECK + rebuild + version bump), not a view change: out of Slice B.
CREATE VIEW v_cash_flow AS
SELECT e.event_id, e.natural_key, e.account_id, e.event_date, e.seq_in_date,
       e.amount, e.quantity, e.price, e.fee, e.unit, e.quality, e.description,
       e.raw_label, e.security_id, e.event_group_id, e.source_id, e.batch_id, e.ingested_at,
       t.canonical AS txn_type, t.is_informational,
       c.canonical AS category, c.spending_class
FROM fact_event e
JOIN dim_txn_type t ON t.txn_type_id = e.txn_type_id
JOIN dim_category c ON c.category_id = e.category_id
WHERE e.superseded_by_batch_id IS NULL
  AND e.batch_id = (SELECT MAX(e2.batch_id) FROM fact_event e2
                    WHERE e2.source_id = e.source_id
                      AND e2.account_id = e.account_id
                      AND e2.event_date = e.event_date
                      AND e2.superseded_by_batch_id IS NULL)
  AND t.is_informational = 0;

-- Household totals at month-end grain, aggregated across accounts, no magic metric name
-- baked into the view itself (C2/U-3). Callers filter by metric; a missing metric is a
-- visible empty set, not an impersonation of absence.
-- SLICE B (blueprint v0.3 section 5): the total now declares what it rests on.
--   * `total`, `min_component`, `max_component` are ADDITIVE totals: they cover only
--     rows the read surface marks `is_additive = 1` — neither a declared duplicate nor
--     an error. A copy is the same number stated twice (summing it with its source
--     double-counts); an error row carries no value, so it must never be silently
--     skipped as if it were a zero component. The rule is defined ONCE, on
--     v_state_current, and consumed here.
--   * `n_components` stays every current row in the group. The five n_* columns below
--     are a PARTITION of it and always sum to it — that is the invariant the harness
--     asserts — so a reader can see, without remembering a filter, whether a total
--     rests on fabricated or duplicate rows.
--   * `n_error` is FIXED: it counted `value_num IS NULL`, which is NOT presence='error'
--     — an errored cell carries its token in value_text (so it was counted), while a
--     non-error text component was counted as an error too. `n_additive_null_value`
--     now carries the honest value-shape signal: additive rows with no numeric value
--     contribute nothing to the total, so P07's promise — a total may never look
--     complete while a component is missing — is enforced on the right signal.
--   * `zero_from_blank` rows DO contribute (DM-2026-01: a blank inside a live row is a
--     stated zero, and it is what reconciles the source's own total). They are counted
--     separately so a reader who averages can divide by what the source observed.
CREATE VIEW v_net_worth AS
SELECT as_of, metric_id,
       CASE WHEN COUNT(DISTINCT period_grain) = 1 THEN MIN(period_grain) ELSE 'mixed' END AS period_grain,
       SUM(CASE WHEN is_additive = 1 THEN value_num END) AS total,
       COUNT(*) AS n_components,
       SUM(CASE WHEN composition_class = 'measured' THEN 1 ELSE 0 END) AS n_measured,
       SUM(CASE WHEN composition_class = 'estimated' THEN 1 ELSE 0 END) AS n_estimated,
       SUM(CASE WHEN composition_class = 'copy' THEN 1 ELSE 0 END) AS n_copy,
       SUM(CASE WHEN composition_class = 'zero_from_blank' THEN 1 ELSE 0 END) AS n_zero_from_blank,
       SUM(CASE WHEN composition_class = 'error' THEN 1 ELSE 0 END) AS n_error,
       SUM(is_additive) AS n_additive,
       SUM(CASE WHEN is_additive = 1 AND value_num IS NULL THEN 1 ELSE 0 END) AS n_additive_null_value,
       MIN(CASE WHEN is_additive = 1 THEN value_num END) AS min_component,
       MAX(CASE WHEN is_additive = 1 THEN value_num END) AS max_component
FROM v_state_current
WHERE period_grain IN ('monthly','month-end')
GROUP BY as_of, metric_id;

-- ---------------------------------------------------------------- audit: curation changes (P06)
-- Precedence and sheet_modified decide which source becomes history. Curation edits are
-- legitimate (correcting a wrong rank) but must never rewrite the past silently.
CREATE TABLE src_audit (
  audit_id   INTEGER PRIMARY KEY,
  source_id  INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  column_changed TEXT NOT NULL,
  old_value  TEXT,
  new_value  TEXT,
  changed_at TEXT NOT NULL
);

CREATE TRIGGER trg_src_audit AFTER UPDATE OF precedence, sheet_modified ON src_ref
BEGIN
  INSERT INTO src_audit(source_id, column_changed, old_value, new_value, changed_at)
  VALUES (OLD.source_id, 'precedence', OLD.precedence, NEW.precedence, strftime('%Y-%m-%dT%H:%M:%S','now'));
  INSERT INTO src_audit(source_id, column_changed, old_value, new_value, changed_at)
  VALUES (OLD.source_id, 'sheet_modified', OLD.sheet_modified, NEW.sheet_modified, strftime('%Y-%m-%dT%H:%M:%S','now'));
END;

-- ---------------------------------------------------------------- holdings (wave-2)
-- Per-security position SNAPSHOTS from the Trading-Performance Data tabs
-- (2022-2026; earlier years live in the statement archive). Lot-level detail
-- from statements remains a separate, deferred pass.
-- v0.2.5: this family carried NEITHER presence NOR needs_verify — both added here
-- (presence with the extended CHECK and the same DEFAULT 'measured'; needs_verify
-- uniform with every other fact family, U-5), plus origin/error_type per §4/§5.
CREATE TABLE holding_state (
  holding_id   INTEGER PRIMARY KEY,
  natural_key  TEXT NOT NULL,
  account_id   INTEGER NOT NULL REFERENCES dim_account ON DELETE RESTRICT,
  security_id  INTEGER NOT NULL REFERENCES dim_security ON DELETE RESTRICT,
  as_of        TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(as_of) = as_of),
  shares       REAL CHECK (shares IS NULL OR typeof(shares)='real'),
  cost_basis   REAL CHECK (cost_basis IS NULL OR typeof(cost_basis)='real'),
  market_value REAL CHECK (market_value IS NULL OR typeof(market_value)='real'),
  price        REAL CHECK (price IS NULL OR typeof(price)='real'),
  purchase_date TEXT CHECK (purchase_date IS NULL OR (purchase_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(purchase_date) = purchase_date)),
  presence       TEXT NOT NULL DEFAULT 'measured' CHECK (presence IN ('measured','estimated','zero_from_blank','error')),
  origin         TEXT CHECK (origin IS NULL OR origin IN ('entered','copy','constant_formula','derived','external','key')),
  error_type     TEXT,                              -- canonical error token when presence='error' (v0.2.5)
  needs_verify   INTEGER NOT NULL DEFAULT 0 CHECK (needs_verify IN (0,1)),
  source_id    INTEGER NOT NULL REFERENCES src_ref ON DELETE RESTRICT,
  batch_id     INTEGER NOT NULL REFERENCES load_batch ON DELETE RESTRICT,
  superseded_by_batch_id INTEGER REFERENCES load_batch ON DELETE SET NULL,
  ingested_at  TEXT NOT NULL,
  UNIQUE (natural_key, batch_id),
  -- v0.2.5 legal (origin, presence) pairs — §4 list, literally identical to
  -- ck_fact_state_origin_presence (the P0 harness asserts both DDL and semantics).
  CONSTRAINT ck_holding_state_origin_presence CHECK (
    origin IS NULL OR presence IS NULL
    OR (origin='entered' AND presence='measured')
    OR (origin='entered' AND presence='zero_from_blank')
    OR (origin='constant_formula' AND presence='measured')
    OR (origin='copy' AND presence='measured')
    OR (origin='copy' AND presence='zero_from_blank')
    OR (origin='copy' AND presence='estimated')
    OR (origin='copy' AND presence='error')
    OR (origin='derived' AND presence='estimated')
    OR (origin='derived' AND presence='error')
    OR (origin='external' AND presence='measured')
    OR (origin='external' AND presence='estimated')
    OR (origin='external' AND presence='error')
  )
);
CREATE INDEX ix_holding_state ON holding_state (account_id, security_id, as_of);

-- SLICE B: holding_state gained presence/origin/error_type in v0.2.5 but this view —
-- the only read surface on it — did not carry them, so every aggregate over positions
-- (including the allocation shares in finpage) silently summed copies and errored rows
-- alongside measurements. Same rule as v_state_current: expose the labels so filtering
-- is the default; which rows are returned is UNCHANGED.
CREATE VIEW v_holding_current AS
WITH cur AS (
  SELECT h.account_id, h.security_id, h.as_of, h.shares, h.cost_basis, h.market_value, h.price,
         h.purchase_date, h.presence, h.origin, h.error_type,
         h.source_id, h.batch_id, h.ingested_at,
         ROW_NUMBER() OVER (
           PARTITION BY h.account_id, h.security_id, h.as_of
           ORDER BY h.batch_id DESC, h.source_id DESC
         ) AS rn
  FROM holding_state h
  WHERE h.superseded_by_batch_id IS NULL
    AND h.batch_id = (SELECT MAX(h2.batch_id) FROM holding_state h2
                      WHERE h2.source_id = h.source_id AND h2.account_id = h.account_id
                        AND h2.security_id = h.security_id AND h2.as_of = h.as_of
                        AND h2.superseded_by_batch_id IS NULL)
)
SELECT account_id, security_id, as_of, shares, cost_basis, market_value, price,
       purchase_date, presence, origin, error_type, source_id, batch_id, ingested_at
FROM cur WHERE rn = 1;
