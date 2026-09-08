# Session Handoff — bag-end-venture · 2026-09-07

**Persona:** Roth (COS) · **Runtime:** dsh · **Model:** deepseek-v4-pro (owner
ruling 2026-09-07: the COS seat is fixed to deepseek-v4-pro — flash models do
not suffice). **Charter:** `AGENTS.md` **v1.0 RATIFIED** (2026-09-07).

> Read order for the next session: this file →
> `private/session-decisions-2026-09-06.md` (all rulings incl. this session's —
> it grew into the running decision log) → `docs/TASKS.md` →
> `docs/CODEBASE_OVERVIEW.md` → `tools/README.md` → `tools/PANEL.md`.

---

## 1. This session, in one paragraph

Roth took the COS seat, did a full review of the repo and corrected it (first
COS's superseded drafts retired, rejected schema removed, routing table and
panel protocol aligned to Joe's rulings, charter authored and ratified).
Then built the actual books: schema v0.2.1 **ratified by the three-leg panel**
(round-2 clean verdicts), the loader contract shipped as code with a
27-assertion battery, **wave-1 ingested** (spine · brokerage/checking/card
ledgers · SSA), the **first Q1 answer delivered** (2× spending: retire now —
resounding), and **wave-2 holdings loaded** (schema v0.2.2). The store now
answers Joe's questions instead of asking them back.

## 2. Owner rulings landed (all logged in `private/session-decisions`)

1. COS = deepseek-v4-pro, fixed. Worker team flash-only with priorities:
   deepseek-v4-flash + glm-5.3-flash (1) · qwen3.8-flash (2) · gpt-5.6-luna (3).
   COS-chair model excluded from pro review of its own artifacts.
2. deepseek models are app-managed (`~/.dsh/llm-deepseek`); do **not** add a
   deepseek provider block to `llm-pi-ai.providers` in settings.yaml.
3. Charter language: "provenance" kept as the term of art (defined inline);
   `[verify]` rule restated; cos-role skill §2.5/§3/§7/§9 rewritten.
4. Skills stay **global**, dotfiles-tracked (cos-role, bag-end-data,
   bag-end-team all committed/pushed by the owner).
5. Q1 inputs: plan funds **2× current spending** (figure in private/); "retiring today"
   = within 1–2 years; a **retirement package ≈ 1yr income (figure in private/)**
   arrives before stop-work; SS is **optionality, not the plan**.
6. `Summary!2022` fixed by the owner (was holding ~29 rows dated 2023).
7. Gold stance: **hold-and-ride** — owner's own thesis, falsifiers registered
   (real rates, central-bank selling, miner cost blowouts).
8. D14 resolved: IRS Income columns are real annual December figures (ingested);
   LTC = closed account, component derived by difference (presence=estimated).

## 3. Where the books stand (numbers live in `private/`, never here)

- **Schema:** `tools/schema/books.sql` = **v0.2.2** — ratified v0.2.1 +
  `dim_security.exchange` + `holding_state` (position snapshots) +
  `v_holding_current`. Harnesses: `.scratch/schema/v02_tests.py` (49) +
  `v02_1_tests.py` (panel battery) + `v021_loader_tests.py` (27, includes
  checking/card/holdings fixtures). All green.
- **Loader:** `tools/bagend/loader21.py` — batch atomicity, source-scoped
  natural keys, supersede-then-insert, carry-over dedupe with evidence,
  space-insensitive prefix vocab + digit-strip, dim-remap on curation change,
  strict date roundtrip, schema-version/FK assertion. Curation as data:
  `private/curation/v021_wave1.json`.
- **Store:** fresh v0.2.2 build, one pass, reproducible. Current rows ≈ 4.4k
  (spine + derived LTC + IRS metrics · 3,213 ledger events across three
  institutions, 99.9% classified · SSA earnings + benefit estimates ·
  holdings snapshots 2022–2026). `v_net_worth` reproduces the source's own
  totals exactly on every date. Zero conflicts. Assumptions: 8 registered
  (all owner rulings + SSA Trustees Report + owner-model parameters).
- **Q1 (verified against the store):** retire now survives at 2× spending in
  every variant except the harshest (2% yield + 2.75% spend escalation + no
  SS), which breaks at ~92 and needs age 68; with SS@78% it needs age 61.
  With the +350k package, all realistic cases clear within Joe's 1–2 year
  definition. Script: `.scratch/q1/when_can_i_retire.py`.
- **Portfolio finding (from the holdings load):** equity is ~96% one gold
  miner, ~59% of net worth — **share count constant since 2022** (average cost near the year-end 2024 low
  (figures in private/); 2025's move was pure price).
  The "invested early, too early" thesis is now quantified in the store.

## 4. Open items

**Mine (in order):**
1. Wave-2 tail: lot-level cost basis from the brokerage statement archive
   (incl. 2019–2021, which have no Data tabs); card-level detail 2022+
   (USBANK/Citi/Amex statement PDFs — PDF parsing needed; the hard rule:
   statements are native PDFs, parse text, never OCR-reconstruct).
2. Q1 depth (when Joe wants it): sequence-of-returns shock test; taxes in the
   ladder (his 2× = after-tax outflow ruling pending); the 2032 SS step-change
   for claim-at-62 sensitivity. Joe called the current depth sufficient —
   these are on tap, not queued.
3. Task #3: the 11 unresolved header tabs (proposals with evidence; Joe
   confirms). Task #7: layouts completion for `trading-*` unlisted tabs.
4. Charter §7/`cos-role` sync: confirm the "facts from data, ask only for
   rulings" protocol with Joe (he demanded it — it worked after wave-1).

**Owner-gated:**
- Commit/remote posture for this repo (still zero commits).
- Zones & inventory discussion; D9/D13 cosmetics.
- `Summary!2022` fix verified ✓ (0 non-2022 rows current).

## 5. Traps learned this session (do not rediscover)

1. **DictReader silently drops columns** when headers repeat or are blank
   (the 2022+ checking tabs' date column vanished that way) — positional
   access for any CSV with blank/duplicate headers.
2. **A curated dim row caches the old canonical** — when the vocabulary
   improves (UNMAPPED → mapped), the dim row must be remapped, not re-looked-up.
3. **The Data tab puts the first account's numbers on the ticker row** — a
   parser that treats ticker rows as headers-only loses the largest account.
4. **SQLite `date()` normalizes impossible dates** (`2024-02-31` → 03-02) —
   the roundtrip guard `date(x) = x` is mandatory, the GLOB alone is a sieve.
5. Workflow-anchor edits can orphan text (the cos-role §3 mishap) — verify
   the whole file after any anchor-based rewrite, not just the replaced span.
6. Re-check a fixture's own expectations when the loader is right and the
   test is wrong (happened twice: bad-date-in-wrong-column, 5-vs-4 rows).

## 6. Do-not-do (carried forward + new)

- Never ask Joe a fact question the store can answer — query first, rule only.
- Never guess a header or a shape: the COLA precedent (deferred, owner ruling).
- Never mutate the owner's live sheets; findings are flag-only with evidence.
- Never store a derived value without `presence='estimated'` + a note.
- Never ingest 2019–2021 "holdings" from anywhere but the statement archive.
- Never treat the flat-nominal ladder as a real-spending answer without saying
  so (Joe knows; the store's job is to keep it labeled).

## 7. Where things live

`tools/` code + ratified schema + specs · `private/` all data-bearing
artifacts (store, curation, decisions log, defects, layouts, provenance,
archive of pilot/dev stores) · `.scratch/` harnesses, schema drafts, panel
reports, q1 scripts, retired drafts · `docs/` handoffs, TASKS, North Star,
plans · Obsidian daily note for 2026-09-07 written.
