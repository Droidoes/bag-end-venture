# Session Handoff — bag-end-venture · 2026-09-06

**Persona:** Roth (Chief of Staff / Steward of Bag End) · **Runtime:** dsh 0.1.2-rc.1
· **Model at handoff:** `qwen3.8-flash` @ high (earlier turns of this session ran on
GLM-5.3-flash before an owner-initiated model switch) · **Repo state: zero commits**,
everything untracked. **Charter not yet ratified** (no `AGENTS.md` — only `to-be-*` drafts).

> Read order for the next session: this file → `private/session-decisions-2026-09-06.md`
> → `.scratch/survey/RECONCILIATION.md` → `.scratch/schema-review/CONVERGENCE.md`
> → `tools/README.md` → `tools/PANEL.md` → `private/layouts/layouts.json`.

---

## 1. Accomplished

### Decisions (owner-ratified)
- **Repo** stays `bag-end-venture`; sibling research repo is **10x** (`~/Droidoes/10x-learning-machine`). Hobbit cipher (Pantry/Hearth/Study, "the road") retired.
- **Persona** **Roth**; advisor relationship, first-name basis; the household's principal is **Joe** — Roth works for the household, never the reverse.
- **Three desks, plain names:** Accounting · Retirement · Portfolio.
- **Household:** single owner + **single-member LLC** (pass-through, Schedule C) → schema carries an `entity` dimension (Joe / LLC), not a spouse dimension.
- **Doctrine pillars:** DCF as master lens · margin of safety · inversion (avoid ruin first) · circle of competence; plus fees/taxes compound, Mr. Market is a quotation, stewardship honesty. Named-investor flourishes cut.
- **Data architecture:** Drive = canonical custody; **SQLite = compute layer** (`private/books.db`, rebuildable, gitignored); **git = method only, zero numbers ever**.
- **Native Google Sheets are read natively, never exported to xlsx** (see §4 trap 6 — this rule exists because violating it produced false defects and nearly caused correct data to be "fixed").
- **Interactivity is universal for a COS**; per-project charters govern *sub-agent posture* only.
- **Account numbers never appear anywhere** — including committed comments. `tools/` holds code, specs, and DDL only.

### Panel operating model (flash-only build, pro tier external)
- `cos-role` (global skill) · `bag-end-team` · `bag-end-data` · `tools/PANEL.md` ·
  `tools/panel_routes.json` · `tools/workflows/{preflight_ping,survey_fanout}.workflow.js`.
- Seats: COS = current model; team = `qwen3.8-flash` clone + `glm-5.3-flash` +
  `gpt-5.6-luna` (DeepSeek-V4-Flash not configured here). Rules: explicit provider on every
  call, pre-flight ping **up to 3 attempts before condemning a leg**, identity read back from
  each child's own system prompt, `send_message` to steer live legs, **parallelize
  investigation / serialize authorship**, convergence grades n/n · (n-1)/n · 1/n.
- Pro review (Qwen3.8-Max · GLM-5.3 · DeepSeek-V4-Pro · Grok-4.6 · GPT-5.6-Sol) is
  **owner-initiated**, post-hoc, and deliberately outside COS control.

### Data discovery (census + inventory)
- Live tree `My Drive/My Info/Investment` = **3,058 rows** (610→610 folders; 2,459→2,448 files)
  with **13 native Sheets**; `Computers/My Computer/Documents/My Info/*` is the **PC backup
  mirror** (no native Sheets, may lag) — both same-named, previously conflated. IDs verified by
  ID-qualified parent chains and pinned in `tools/bagend/config.py`.
- `My Drive/My Info/Tax Records`: **tax-prep app returns 2011–2025** + **IRS transcripts 2013–2022**
  (Wage & Income / Account / Record of Account / Tax Return), recovered by the owner from
  a cloud-storage Personal Vault during the final Office365 exit (Google Tasks filed as a record).
- **11 xlsx mirrors deleted by the owner** after per-pair freshness proof (native Sheet newer
  in all 11) — verified by post-deletion census, exactly −11 rows. One source of truth per dataset now.
- Ledger-vs-state measured over 13 tabs: ledgers carry **many rows per date** (up to 43);
  state series are 1:1 (`.scratch/ledger_vs_state_scan.tsv`).
- 29 survey sources fetched to `private/raw/`, all validated; **`private/raw/_provenance.tsv`**
  records `source_kind` / `obtained_via` for every local file (filename ≠ identity).

### Toolkit (`tools/bagend.py`)
`catalog drive|find|merge-registry` · `fetch` · `sheets tabs|dump` · `inspect [--header-row]`
· `ingest xlsx|csv` · `query`. Plus `tools/check_hygiene.sh` (digit-run + blocklist scan against
`private/hygiene-blocklist.txt`). **Guards, all negative-tested:** `fetch` refuses to export a
native Sheet; `ingest xlsx` refuses an exported-native artifact and refuses an unresolved header;
`_run_gws` raises when a 0 exit produced no file; FK pragma set on every toolkit connection.
**8 defects fixed** in inspect/ingest (6 found by survey legs, 2 by my own negative tests).

### Survey + allow-list
- 5-leg structural survey complete and reconciled (`.scratch/survey/RECONCILIATION.md`).
- **`private/layouts/layouts.json`** — 25 sources / 59 tab entries with explicit `header_row`,
  `grain`, `dedupe`, and `role` (raw 37 · derived 11 · scratch 8 · worksheet 2 · duplicate 2 ·
  documentation 1 · reference 1 · deferred 1); spec committed as
  `tools/manifests/layouts.schema.md`.
- Defect inventory `private/defects/inventory.md`: **zero open data defects.** Two items fixed by
  the owner and verified (`Summary!2015/2016` stray-2019 dates; impossible `4/31/2020`).
  Three items reclassified as **not defects** (padding rows, chart-tab crashes, timestamped
  dates — all export artifacts). Two cosmetic suggestions left to the owner (D9 rename a
  misleadingly-named tab; D13 show the year in date display).
- First artifact loaded: `net_worth_monthly` 328 rows **1996-12-31 → 2026-08-31** (rebuilt from
  the native CSV after the export guard landed).

---

## 2. Where the schema stands — v0.1 REJECTED, v0.2 required

Three independent legs reviewed `tools/schema/books.sql` (v0.1): **semantics REJECT ·
adversarial REJECT (executed tests) · purpose RATIFY-WITH-CHANGES**. Full detail in
`.scratch/schema-review/CONVERGENCE.md`. Verdict: **the shape is right, the keys are wrong,
the enforcement is decorative.** Nothing was ever applied to `books.db`, so no harm is baked in.

Must-fix before any fact rows land:
- **C1** state resolution by `MAX(seq)` across sources is positional, not authoritative
  (measured: a tie summed 237 against a truth of 137; a stale file outranks a corrected
  re-export; TIPS's legitimate same-day pair gets silently reduced).
- **C2** the net-worth view lacks aggregation and grain filter, and **returns zero rows when a
  dimension is missing** — a missing label masquerading as missing money.
- **C3** guards were ornamental: FK off per connection, `CREATE TABLE IF NOT EXISTS` making
  re-application a no-op, enums living only in comments, `is_informational` duplicated with no
  constraint (one `Balance Forward` row → two different cash-flow totals).
- 2/3: dedupe keys include `source_id` while duplication is *across* sources; the allow-list
  can't be stored (`role` CHECK rejects derived/scratch/worksheet/duplicate/deferred;
  `header_row='unresolved'` lands as text in an INTEGER); single-column year PKs **destroy
  competing evidence** (exactly the two-source case we already litigated); nullable provenance.
- 1/3 unique catches worth keeping: append-only vs UNIQUE have no non-destructive resolution
  (`superseded_at`/`is_current` absent); `seq` doesn't survive re-ingest and **row order is
  ascending in one family, descending in another**; `CHECK(date(x)=x)` accepts `4/31/2020`
  because CHECK rejects only on FALSE (use GLOB + `date(x) IS NOT NULL`); `period_grain`'s
  CHECK is lossier than the corpus.
- **Fix order:** identity model → state precedence by declared source recency → allow-list
  storage + column maps → cheap invariants → only then missing tables.

**Store today (quarantined pilots, to be rebuilt not migrated):** `fi_history_txn` 656 ·
`td_txn_2010` 59 · `td_txn_2015` 45 · `net_worth_monthly` 328. My control table
`fi_history_txn2` (656 content-identical duplicates) was found by review, verified, and dropped.

---

## 3. The owner's three questions are now the spec

The 8-question list the panel graded was **mine, not his**. His actual asks supersede it:

1. **Can I retire right now?**
2. **What's the optimal path to move 401(k)/rollover money into Roth?**
3. **How can the portfolio be used better to increase return?**

Consequences: per-security harvestable-loss ranking and fee-drag ranking are **demoted** (he
declined them); **bracket bounds** and a **decumulation/withdrawal substrate** are **promoted**,
because Q1 and Q2 both run through them.

**Critical finding about his own model** (`Social-Security-Earning!Retirement Balance`): the
live-pull rows are real (Balance 2024–26; yield/P&L/tax/spending actuals live for 2024–25 via
`IMPORTRANGE`, 2026 not yet posted), but **future balances are typed targets** (2027+;
figures live in `private/session-decisions`) and — most importantly —
**`Go-broke year (est)` and `Go-broke rate (est)` are hand-typed constants, not formulas.**
So the model currently stores conclusions rather than computing them. Its tension: actual
spending vs. rent with a fixed annual escalation rate (DCV capitalized at a fixed rate),
against the assumed long-term yield and effective tax rate (figures: `private/session-decisions`).
> **Figure-scrub note (Roth, 2026-09-06):** this file lives in `docs/` (a commit-able path)
> and must hold method only — personal amounts, rates and balances were replaced with
> pointers to `private/session-decisions-2026-09-06.md`, which keeps the figures.

> **CORRECTION (2026-09-06, later — owner clarified + primary-source verification):** the
> two `Go-broke` rows are **NOT personal conclusions**. They are the **SSA OASI trust-fund
> depletion assumptions** from the 2026 Trustees Report: OASI pays 100% of scheduled benefits
> through Q4 **2032**, then continuing income funds **78%** of scheduled (OASDI combined:
> 2034/83%; Medicare HI: 2033/89%). Typed constants are the correct representation for an
> external annual-report figure — my "stores conclusions" framing was wrong. The observation
> that stands: 2027+ balances (4.5M/5.0M/5.5M) are typed assumptions. Consequence for Q1:
> SS must be modeled at **78% of scheduled as base case** (owner claims at 67 ≈ 2035, after
> depletion), and the claiming-age analysis gains a 2032 step-change (claiming at 62 in 2030
> = ~2 years at 100%, then 78%). Sources: 2026 Trustees Report via NARSSA (ssa.gov blocks
> direct fetch).

---

## 4. Traps learned the hard way (do not rediscover)

1. `gws files.download` returns **metadata, not bytes** → binary fetch needs `files.get` + `alt=media`.
2. `gws` refuses `-o` paths **outside the current directory** → fetch into the repo, never `/tmp`.
3. **A 0 exit code is not proof of success** — a silent empty write once let 19 failed fetches pass.
4. **`/tmp` is not durable between harness calls** → work in `private/` or `.scratch/`.
5. Never pipe batch **stderr to `/dev/null`**; it converts loud failures into quiet ones (bit me twice, including one failed probe that produced a blank result I nearly misread as "no data").
6. **Never export a native Sheet to xlsx for analysis**: injects ~1,000 padding rows, crashes on chart tabs, and **re-infers the year** on year-less text dates. Three "source defects" were artifacts of exactly this.
7. **Filename ≠ identity** — provenance file is the only authority (a local `Stats.xlsx` was an *export* of the live `Stats` sheet; the deleted mirror was a different object).
8. **A metric without its definition is not a finding** (2,577 date-typed vs 2,731 populated rows in one tab; both true; my "resolution" was wrong and I retracted it).
9. **Never mutate a file a running background job owns** (I clobbered a merge that way).
10. **A validator that never rejects anything isn't validating** — negative-test every guard.
11. **Don't put the owner's data or identifiers in `tools/`**, and don't ask him to review SQL — his authority is over *what the numbers should answer*, not key design.
12. `/tmp` cleanup aside: unquoted SQLite identifiers break on names like `TRANSACTION ID`.
13. `sqlite3` FK enforcement is **per connection**; a DDL `PRAGMA` applies only to the connection that ran it.

---

## 5. Outstanding — what to work on

### Needs the owner (nothing else is blocked by these)
1. ~~Go-broke year/rate semantics~~ **ANSWERED 2026-09-06**: SSA trust-fund depletion (2032) and payable rate (78%) per the 2026 Trustees Report — external assumptions, correctly typed. Base-case SS in the plan = 78% of scheduled.
2. **Spending level the plan must fund** (actual 2024–25 spending per the live actuals; include LLC money? taxes? — figures in `private/session-decisions`).
3. **Target stop-working age**, and whether SS at 67 (≈2035) is a decision or a variable to test.
4. The five money questions from `tools/PANEL.md` discussion (same-day events kept · year-relative merge prohibition · which labels are non-cash · duplicate-export policy · gap-vs-zero for empty years). I proposed defaults; none objected to yet.
5. Commit/remote posture (local-only vs private GitHub) + tracking the three new skills in the dotfiles bare repo.
6. Zones & inventory discussion (Records zone; static vs active cadence — `2026-Trading-Performance` is live and still edited).
7. Cosmetic discretion: D9 tab rename, D13 year-visible date format.

### Mine, in order
1. **Schema v0.2** — single-threaded authorship, identity model first, per the fix order above; then **re-run the three-leg panel** and require a clean verdict before loading facts.
2. Resolve the **11 `header_row: unresolved`** tabs (propose with evidence; owner confirms before ingest).
3. Apply v0.2 to a fresh store; load wave 1 (spine → TD ledgers → SSA → checking/card) honoring dedupe/`seq`/absence rules; then build the **first real decumulation answer to Q1**.
4. **Charter writing**: `AGENTS.md` (three desks · doctrine · Drive-canonical + native-read rule · account-number hygiene · `cos-role` layering) · `README.md` · `docs/TASKS.md` · `docs/CODEBASE_OVERVIEW.md` (North Star) · retire the `to-be-*` drafts *with intent*.
5. Obsidian daily note for 2026-09-06 (deferred by owner until progress landed — it has).
6. Later, in **10x** (not here): propose amending its charter §5 so "zero interaction" governs sub-agents only, not owner availability.
7. Do not let `net_worth_monthly` (table) and a future net-worth **view** coexist as competing headlines — one or the other, decided in v0.2.

### Do-not-do list
- Never ingest `derived` / `scratch` / `worksheet` / `duplicate` tabs, or any Gain-Loss working paper (its summary is `Gain-Loss Cost Basis`).
- Never combine TIPS's same-day dividend + contribution rows (ΔMV equals the contribution **exactly**; merging destroys income-vs-basis).
- Never merge year-relative columns (P/L, cost basis) across copy-forward seams.
- Never treat absence as zero; never store a derived value that can rot.
- Never write back into the owner's live Sheets — flag-only, with evidence pointers.
- Never trust a single number that a tolerant re-parse can change.

---

## 6. Where things live
`tools/` code, schema DDL, specs, hygiene gate · `private/` data-bearing artifacts
(censuses, layouts, defect inventory, provenance, pilots DB — gitignored) ·
`.scratch/` ephemeral leg reports and draft schema (wipeable) ·
`docs/` currently holds only `to-be-TASKS.md` until charter writing ·
skills: `~/.agents/skills/{cos-role,bag-end-data,bag-end-team}/SKILL.md`.
