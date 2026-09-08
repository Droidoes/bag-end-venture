# Bag End — Task Ledger

Roth's ledger. Status legend: OPEN (ready to work) · BLOCKED (waiting on
another task) · OWNER (waiting on Joe) · PARKED (owner set aside) · DONE.
Renumbering only with Joe's nod.

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | **Schema v0.2** for `books.db` — single-threaded authorship (COS), fix order: identity model → state precedence by declared source recency → allow-list storage + column maps → cheap invariants → only then missing tables | **DONE — ratified v0.2.1** (2026-09-07) | DDL at `tools/schema/books.sql`; blueprint in `docs/superpowers/plans/2026-09-07-schema-v0.2.md`; convergence `.scratch/schema-review/v02/CONVERGENCE.md`; two harnesses green (49 + 26 assertions) |
| 2 | Three-leg panel re-review of v0.2 — clean verdict required before any fact rows land | **DONE** | Round 2 verdicts: CLEAN · CLEAN · CLEAN-WITH-NITS (the round-1 REJECT leg re-executed its own probes and returned CLEAN) |
| 3 | Resolve the 11 `header_row: unresolved` tabs — propose with evidence, Joe confirms before ingest | OPEN | COLA removed from the list by owner ruling (public data, web-pullable — never ingested) |
| 4 | Apply v0.2.1 to a fresh store; **loader contract** then **wave-1 ingest** (spine → brokerage ledgers → SSA → checking/card); build the first decumulation answer to Q1 | **WAVE-1 DONE** — 4,342 current fact rows on a fresh v0.2.1 store: spine 1,045 cells (incl. derived LTC + IRS metrics) · events 3,213 across brokerage/checking/card, 99.9% classified (2 sentinel rows) · SSA 27 + 56. Loader battery 23 assertions green; clean rebuild reproducible. **Q1 ANSWERED** (owner rulings: 2× spending + ~1yr-income package; retire now = resounding yes; all variants cleared except the harshest no-SS case at ~68) | Q1 = "can I retire now?" |
| 5 | **Charter v1.0** — `AGENTS.md` (ratified 2026-09-07), `README.md`, `docs/TASKS.md` (this file), `docs/CODEBASE_OVERVIEW.md`; `to-be-*` drafts retired to `.scratch/retired/` | **DONE — ratified** | plain-language pass + panel rulings folded into v1.0 changelog |
| 6 | Owner rulings queue: spending level the plan must fund · target stop age + SS@67 decision-or-variable · five money questions · commit/remote posture · zones & inventory design · D9/D13 cosmetics | OWNER | none block 1–4 |
| 7 | **Complete the layouts allow-list** for the `trading-*` sheets' unlisted tabs (per-account state tabs, `Stock P&L`, `TIPS`, `NEAR`, `Data`, transaction tabs, scratch tabs) — fan-out from `.scratch/survey/b1*.txt` evidence; COS authors entries; Joe confirms headers | OPEN | found by Roth's 2026-09-06 tab census; source-level notes added to `private/layouts/layouts.json` |
| 9 | **Wave-2: holdings history** — **complete monthly series: 372 statement PDFs parsed, TD brokerage account 189 months 2008-12 -> 2026-09** (statement parsers, folder-qualified fetch, account auto-routing, verified to printed totals); cost-basis bridge as state; USBANK LLC card statements loaded (entity=LLC) | **DONE** | Gaps documented: plan-custodian 2008-2016 numbered statements have no structured qty/cost text layer (Rollover per-security history needs the custodian's CSV exports — ruling requested); card image-only PDFs (CSV export ruling); per-lot FIFO lives in the custodian's lot ledger |
| 10 | **Q2 groundwork** — 401(k) plan ledgers loaded (2,124 rows, fully classified incl. informational markers, cross-file dedupe with evidence); IRS 2026 brackets in `dim_tax_bracket` (IR-2025-103); Q2 assumptions registered (filing status + other income NEEDS-VERIFY); first conversion-ladder answer computed (`.scratch/q2/roth_path.py`) | **FIRST ANSWER DELIVERED** — Plan A (12% bracket, 2026-2035) converts 504k at ~58k federal tax; Plan B (22%) converts 1.06M at ~124k; no-conversion RMDs land in 24%+; **Q2 refresh (tax-history fold-in) PARKED per owner 2026-09-08** | refinements queued when reopened: filing status confirmed Single by the 2026-09-08 tax scan (assumption already satisfied), SS-taxation interaction, bracket indexing, NJ state tax, no-state-tax move |
| 11 | **Full tax-return scan 2012-2025** — fetch + parse IRS transcripts (2019-2022) and tax-prep Records/Filing PDFs (2012-2017, 2023-2025) into `tax_year_facts`; cross-check vs Joe's Tax Rates history; panel-verified | **DONE** (2026-09-08) — schema v0.2.4 (5 tax line-item columns, additive, parity-verified); 14 year rows loaded in batch 31 under dedicated tax sources; 4-leg flash verification n/n zero discrepancies; all three owner anchors match (2015, 2020, 2022); **2018 filled 2026-09-08 (batch 32) from the Vault-recovered Records PDF + Account Transcript witness — history now complete 2012-2025** | 2022 marginal_bracket '22%' retired (was an effective rate, 21.9%); 2023-2025 filing status derived (needs_verify=1); **Schedule C forms are blank in every fetched PDF → LLC loss history not in these sources — stays OWNER-gated** |
| 12 | **Q3 — portfolio optimization** (scope per owner 2026-09-08): tax efficiency, asset location, withdrawal sequencing, structure, concentration *policy*. **Investment selection is OUT of scope — deferred to the 10x repo.** | **PARKED** (owner, 2026-09-08) | Deliverable when reopened: decision memo — each asset's named job, sequencing order, tax-location analysis on Joe's filed rates (15% LTCG + 3.8% NIIT, 32→35% ordinary), sleeve deployment rule, concentration policy options with triggers/falsifiers |
| 13 | **Financial page (dashboard)** — present the store's vital data to Joe: retirement dashboard first (owner directive 2026-09-08, architecture B + Homepage-projects hook) | **BUILT — awaiting placement nod** | Exporter: `bagend.py export finpage` → protocol-1 JSON (net worth series, annuity inputs + reference, tax years, holdings, assumptions); static page `apps/finpage/BagEnd.html` (Connect-button pattern, zero deps, zero numbers, JS/Python model parity harness `.scratch/q8/finpage_parity.js`). Pending: drop page into Homepage-projects `Bag-End-Labs/BagEnd/` + data dir `Homepage-DB/BagEnd/` per Joe |
| 15 | **Dashboard framework** — owner ruling 2026-09-08: one capability = one page, shared shell (Connect flow, theme, nav) + shared model core + one data contract | **OPEN** | Framework pass: extract shared core from BagEnd.html, page registry/nav, payload v2 with per-page sections (single finpage.json, one Connect for all pages), build-inliner so each page stays a single deployable file (Homepage-projects pattern). Future pages slot in as sections + a page file |
| 16 | **Withdrawal-simulation page** (owner example 2026-09-08): IRS withdrawal sim — RMD schedule (age 73), account-bucket withdrawals, tax at filed rates, Q2 conversion Plans A/B interactive | **QUEUED — after #15** | Second page riding the framework; sources: `position_lot`/holdings per account, `tax_year_facts` rates, `dim_tax_bracket`, Q2 scripts (`.scratch/q2/roth_path.py`) |
| 14 | **2018 IRS transcript fetch** — closes the only tax-history hole | **DONE** (2026-09-08) — fetched Records PDF + Account Transcript + Wage & Income from the recovered Tax Records tree; loaded batch 32; dual-witness verified (Records summary + Account Transcript agree on taxable 172,454 and Single) | Tax history 2012-2025 now complete — zero holes |
| 8 | Decumulation substrate design: derive `A_max` (the zero-at-age-100 ceiling withdrawal) instead of typing it; run the ladder at ceiling **and** planned-spending levels; SS base case = 78% of scheduled (2026 Trustees Report); 2032 step-change for claim-at-62 analysis | **FIRST PASS DELIVERED** (2026-09-08) — `.scratch/q8/annuity_max.py`: A_max goal-seeked from the store (balance, SS@62/@67, assumptions) per variant × yield; ceiling ≈1.5-1.76× planned spending; at plan the ladder never decumulates. Pending: escalation variants, taxes in the ladder, page integration (#13) | Retirement Balance decoded + owner-confirmed 2026-09-06 |

## Owner rulings landed this session (2026-09-06, Roth review)

- "Effective Annuity (max)" semantics confirmed: goal-seek to ~zero at age 100 —
  a ceiling, not planned spending.
- Panel independence rule adopted: the COS-chair model is excluded from pro
  review of its own sessions (deepseek-v4-pro now holds the chair).

## Changelog

- **2026-09-04 (first COS):** bootstrap drafts — retired with intent (see
  `.scratch/retired/`), superseded by 2026-09-06 ratifications.
- **2026-09-06 (second COS):** data-architecture day — Drive-canonical +
  SQLite compute ratified; panel ratified; toolkit shipped; survey + schema
  v0.1 review completed.
- **2026-09-06 (Roth review):** Retirement Balance decoded; repo reviewed and
  corrected (routing table, layouts gaps, stale defect statuses, handoff
  figure-scrub, rejected schema moved, charter authored).
- **2026-09-08 (tax scan):** schema v0.2.4 (additive tax line-item columns,
  ALTER parity-verified against the script); 14 tax years loaded and
  panel-verified (4 flash legs, n/n); panel run logged at
  `.scratch/q2/panel/run-log.md`; Schedule C found blank in every fetched PDF.
