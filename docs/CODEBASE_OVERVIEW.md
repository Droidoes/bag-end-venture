# CODEBASE_OVERVIEW — bag-end-venture (North Star)

What this repo is, how the parts fit, and what must never regress. Updated
2026-09-06 (Roth review).

## The system in one paragraph

Google Drive holds the canonical financial records (the LIVE `My Info` tree:
13 native Google Sheets + statement archives, plus Tax Records). The repo's
toolkit reads those sources through their native APIs into typed local
artifacts, ingests them into a rebuildable SQLite store (`private/books.db`),
and answers questions there — without ever mutating a source. Git carries only
method: schemas, tooling, specs, docs. No personal number is ever committed.

## Three zones (ratified)

| Zone | Where | Role here |
|---|---|---|
| **Records** | Google Drive `My Info` | canonical custody — read natively, never written |
| **Knowledge** | Obsidian vault | cited for doctrine/canon; read-only |
| **Research** | `~/Droidoes/10x-learning-machine` | Portfolio desk consumes deliverables; read-only |

## Data flow

```
Drive (live tree) ──catalog──> private/catalog.tsv        (the map of what exists)
        │
        ├─ native Sheet ──sheets tabs|dump──> private/raw/sheets/*.csv  (typed values)
        └─ uploaded file ──fetch──> private/raw/*            (original bytes)
                                             │
                                        _provenance.tsv     (source_kind, obtained_via)
                                             │
                                             ▼
                                   private/books.db (SQLite)
                                   rows carry _source_path, _drive_id, _ingested_at
                                             │
                                             ▼
                                  query → memos / answers (numbers with lineage)
```

- `private/` is gitignored and may hold numbers; nothing in it is committed.
- `.scratch/` is ephemeral working space (leg reports, drafts, retired files).
- `tools/` holds code, specs, DDL and manifests only — **never data**.

## Layout of the repo

| Path | Purpose |
|---|---|
| `AGENTS.md` | Charter (v1.0-draft; ratification gate) — desks, doctrine, data contract, boundaries |
| `README.md` | Entry point |
| `docs/TASKS.md` | Task ledger — the single queue |
| `docs/session-handoff-*.md` | Method-level EOD state (figures scrubbed) |
| `tools/bagend.py` + `tools/bagend/` | The toolkit: catalog / fetch / sheets / inspect / ingest / query |
| `tools/PANEL.md` + `tools/panel_routes.json` | Panel protocol + routing table |
| `tools/workflows/*.js` | Canonical fan-out templates (pre-flight ping, survey) |
| `tools/manifests/layouts.schema.md` | Committed spec for the allow-list (data half lives in `private/layouts/layouts.json`) |
| `tools/schema/README.md` | DDL home — **no ratified schema yet** (v0.1 rejected; v0.2 in work) |
| `templates/` | Decision-memo template |
| `private/` | Data-bearing artifacts (census, provenance, layouts, defects, pilots DB, decisions log) |
| `.scratch/` | Ephemeral: leg reports, schema drafts (incl. rejected v0.1), retired first-COS drafts |

## Invariants (never regress)

1. **Native Sheets are read natively** (`sheets dump` → typed CSV); xlsx export
   for analysis is prohibited — enforced by `fetch`/`ingest` guards.
2. **No personal numbers anywhere in git** — not in docs, comments, prompts, or
   manifests; `tools/check_hygiene.sh` gates every commit.
3. **Sources are never mutated** — defects are flagged with evidence, never
   silently fixed.
4. **Ledger vs state:** ledgers carry many rows per date; state series are 1:1
   (one legitimate same-day pair). Two keying families. **Blanks are not
   uniform** (owner ruling 2026-09-10, stated to apply to all sheet
   extraction): a blank numeric cell *inside an existing period row* is **0** —
   the source's own convention for "nothing happened that period" (e.g. 401k
   catch-up before 2019). An **absent row or period is not recorded** — never
   0: absence of evidence is not evidence of absence, and a series that ends at
   2026 says nothing about 2027. Ingest keeps the two apart
   (`presence='zero_from_blank'` vs no row at all). Rows that exist only as
   pre-series labels — e.g. Tax Rates 2010–2014 before the 2015 series start —
   are not period records at all: the layout declares where the series begins.
   (Owner rulings 2026-09-10/11.)
5. **The allow-list is the ingest gate** — header rows are confirmed by a human
   (Joe), never guessed; unresolved headers are refused loudly.
6. **Derived/scratch/worksheet/duplicate tabs are never ingested** — double
   count is this corpus's default failure mode.
7. **A number without provenance is not a finding.**

## The three owner questions (the spec)

1. Can I retire right now?
2. What's the optimal path to move 401(k)/rollover money into Roth?
3. How can the portfolio be used better to increase return?

Decumulation substrate (Task #8): derive the ceiling withdrawal (the
goal-seek-to-zero-at-100 annuity Joe confirmed), run the ladder at ceiling
**and** planned-spending levels, model Social Security at 78% of scheduled as
the base case (2026 Trustees Report), with a 2032 step-change for claim-at-62
analysis.

## Milestone changelog

- **2026-09-04** — bootstrap drafts (first COS): superseded, archived.
- **2026-09-06** — data-architecture day (second COS): Drive-canonical +
  SQLite compute ratified; persona Roth; plain desks; Joe+LLC entity model;
  census (3,058 rows) + 29 sources fetched + provenance; survey 5/5 legs
  reconciled; schema v0.1 rejected by 3-leg review; toolkit shipped with
  negative-tested guards; panel protocol ratified.
- **2026-09-06 (Roth review)** — `Retirement Balance` decoded (decumulation
  boundary model; annuity = goal-seek ceiling, owner-confirmed); 2026 balance
  question resolved (continuous growth, not a source change); repo corrected:
  stale first-COS drafts retired, rejected schema removed from `tools/schema/`,
  routing table + independence rule updated, layouts gaps found (Task #7),
  defect statuses reconciled, handoff figure-scrubbed, charter authored.
- **2026-09-07 (Roth, schema day)** — books.db schema v0.2 authored per the
  ratified fix order (source-scoped business keys + batch versioning, declared
  precedence with tie-surfacing, full allow-list as data, roundtrip date
  guards, versionable assumption register for the decumulation substrate);
  two adversarial harnesses green (75 assertions); three-leg panel: round 1
  REJECT/RATIFY-WITH-CHANGES×2 reconciled → **round 2 clean verdicts**;
  `tools/schema/books.sql` = v0.2.1 ratified.
- **2026-09-08 (Roth, backfill)** — full brokerage statement history
  parsed: 372 PDFs -> 1,582 holding snapshots; the brokerage account's monthly
  positions now span 2008-12 -> 2026-09 (189 months) with purchase dates; the
  decade story is a store query (2012 gold accumulation -> 2020 COVID spree ->
  2025 consolidation to two tickers). Gaps documented: plan-custodian-era PDF layout,
  card image-only statements, per-lot detail.
- **2026-09-07 (Roth, wave-1)** — loader contract shipped
  (`tools/bagend/loader21.py` + 23-assertion synthetic battery) and wave-1
  complete on a fresh v0.2.1 store: net-worth spine (1,045 cells incl. the
  derived LTC component + IRS income metrics), 3,213 ledger events across
  brokerage/checking/card with full txn classification, SSA earnings +
  benefit estimates, coverage calendar and dedupe log populated. The net-worth
  view reproduces the source's own totals exactly at every spot check; the
  store rebuilds clean from Drive + curation in one pass.
- **2026-09-08 (Roth, tax scan)** — full tax-return scan 2012-2025: schema
  v0.2.4 (additive tax line-item columns in `tax_year_facts`, live store
  parity-verified), 14 year rows loaded from IRS transcripts + tax-prep
  packages, all three owner anchors matched, panel verification 4/4 n/n with
  zero discrepancies; the 2022 marginal-bracket mislabel retired; Schedule C
  found blank in every fetched package (LLC history not in these sources);
  Q2 refresh + Q3 scoped and parked per owner; luna route fixed and verified
  (all four flash routes live).
- **2026-09-08 (Roth, morning)** — tax history completed (2018 filled from the
  Vault-recovered Records PDF + Account Transcript witness, batch 32); Task #8
  first pass (`A_max` ceiling derived from the store: ~1.5-1.8× planned
  spending; the plan never decumulates); **financial page shipped** —
  `bagend.py export finpage` + single-file `apps/finpage/BagEnd.html`
  (Homepage-DB connect pattern, zero committed numbers, JS/Python model
  parity); owner framework ruling: one capability = one page on a shared
  shell + one data contract (ledger #15, #16 queued).
- **2026-09-10 (Roth, layout day)** — native **structure** read shipped
  (`bagend.py sheets grid`: merges + formulas + formats, literals redacted by
  default): the values-only path could not show group bands or derived columns,
  which is what left the unresolved-header backlog in Task #3. First tabs
  resolved with it — `stats / Inv Income` (worked entry, subtotal bands outside
  every merge), `stats / 401k Contributions` (no merges at all; the recorded
  "merged 2-row header" note was stale), `stats / Taxes` (four group bands; two
  columns are cross-sheet `IMPORTRANGE` pulls from the SSA tab) — and `Buybacks`
  ruled a **worksheet**, never ingested. The blank rule above was ratified in
  the same pass, and two source flags were filed (D15 subtotal drops an
  account; D16 duplicate total/catch-up columns).
- **2026-09-11 (Roth, structure day)** — **Task #3 closed**: all 11 unresolved
  allow-list entries settled with the owner; `layouts.json` now carries 0
  unresolved entries, and the layout schema gained the tiers and block data the
  cases forced (`group_row`, `sub_header_row`, `first_data_row`, `skip_rows`,
  `derived_columns`, `external_links`, `header_totals`). The blank rule was
  completed (blank cell in a live row = 0; absent row = not recorded; pre-series
  label rows = not records), and the xlsx→Sheets migration defect family was
  swept and **certified clean across all 13 sheets** (`bagend.py sheets errors
  --all` reports 0 error cells in every tab). Loader follow-through: Task #18.
- **2026-09-12 (Roth, capability day)** — **model-pinned, tool-using fan-out
  verified**, and the panel protocol corrected with it: `subagent` accepts
  `provider`/`model`/`reasoning_effort` (all four flash routes pinned; each child
  quoted its own identity line verbatim and executed real tool calls), the
  binding is **per session at session start** (enabling the setting needs a new
  conversation — a restart is not enough; the failure text is
  `child model selection is disabled for this tool instance`), and workflow
  `agent()` children **can** use tools — retiring the 2026-09-10 constraint that
  had parked both fan-out templates. `subagent_fork` deliberately exposes no
  model fields (keeps the inherited prefix eligible for KV-cache reuse); workflow
  `agent()` accepts `provider`/`model` but rejects `reasoning_effort`. Toolchain:
  **Task #19(a) closed** — the `query` path opens `books.db` read-only
  (`_connect_ro()`), so a stray `DROP` can no longer destroy the store. Ledger
  #21 records the capability. Remaining gate between the ratified layout
  knowledge and the loader: **Task #18** — the six Task #3 tier fields
  (`group_row`, `sub_header_row`, `first_data_row`, `skip_rows`,
  `derived_columns`, `external_links`) exist only in the allow-list, which
  `loader21` never reads.
