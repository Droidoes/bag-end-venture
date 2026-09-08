# Session Handoff — bag-end-venture · 2026-09-08

**Persona:** Roth (COS) · **Runtime:** dsh · **Model:** deepseek-v4-pro (owner
ruling: COS seat fixed). **Charter:** `AGENTS.md` v1.0 RATIFIED.

> Read order for the next session: this file →
> `private/session-decisions-2026-09-06.md` (running decision log — includes
> this session's rulings) → `docs/TASKS.md` → `docs/CODEBASE_OVERVIEW.md` →
> `tools/PANEL.md` + `tools/panel_routes.json`.

---

## 1. This session, in one paragraph

Full tax-return scan 2012–2025: fetched 14 IRS/tax-prep PDFs, bumped the
schema to **v0.2.4** (five additive tax line-item columns, live store migrated
with exact-parity verification), built a parser for transcripts + tax-prep
summary pages + the Tax History Report grid, loaded **14 year rows** into
`tax_year_facts`, and had the panel independently re-verify the entire
extraction (**4 flash legs, n/n, zero discrepancies**). All three owner
anchors matched. Q2 refresh and Q3 were scoped then **parked by the owner**.
The gpt-5.6-luna route failure was diagnosed (COS) and fixed (owner):
canonical ping now PONG with identity verified — all four flash routes live.

**Morning session (same date):** 2018 fetched from the recovered Tax Records
tree and loaded (batch 32, dual-witness) — tax history complete, zero holes.
Task #8 first pass: `A_max` ceiling derived from the store
(`.scratch/q8/annuity_max.py`). **Financial page shipped**:
`bagend.py export finpage` + `apps/finpage/BagEnd.html` (static, Homepage-DB
connect pattern, zero committed numbers, JS/Python parity harness). Owner
framework ruling: one capability = one page, shared shell + one data contract
(ledger #15/#16). Data file placed at Homepage-DB/BagEnd/finpage.json
(local only).

## 2. Owner rulings landed (logged in `private/session-decisions`)

1. **Q3 scope:** portfolio *optimization* only — tax efficiency, asset
   location, withdrawal sequencing, structure, concentration policy.
   **Investment selection is deferred to the 10x repo.**
2. **Q2 refresh and Q3 are PARKED** (ledger #10 note, #12). Reopen on owner
   signal; deliverables are pre-scoped in the ledger.
3. **Luna fix (owner's):** gpt-5.6 routes resolve to the Responses API;
   effort-less requests send the reasoningEfforts `off` value verbatim
   (`minimal` 400s — `none` is correct; `max` natively accepted); a
   route-level `compat.maxTokensField` broke route resolution. COS's staged
   settings edit was superseded by the owner's mapping and is not in effect.
4. Panel discipline enforced mid-session: the COS must fan out the parse and
   verification legs (workflow fan-out) rather than absorb them — owner
   caught it, COS corrected; 4-leg verification ran n/n clean.

## 3. Where the books stand (figures live in `private/`, never here)

- **Schema:** `tools/schema/books.sql` = **v0.2.4** — v0.2.3 + `tax_year_facts`
  gains `taxable_income`, `total_tax`, `std_deduction`, `ss_wages`,
  `state_income_tax` (nullable REAL, typeof guards). Live store migrated and
  parity-checked (exact `sqlite_master` match). All three harnesses green.
- **Tax facts:** 14 years (2012–2025) in `tax_year_facts`, batch 31, zero
  conflicts, under dedicated transcript and tax-prep sources. 2023–2025
  filing status derived (needs_verify=1; 2023/2024 are exact std-deduction
  proofs). 2018 carries status/bracket/std only — its numbers aren't printed
  in any fetched file (one transcript closes it). The previously loaded 2022
  marginal '22%' was an effective rate — retired.
- **Schedule C finding:** every fetched package contains only BLANK Schedule C
  forms (the preparer prints empty official forms). LLC loss history is not in
  these sources — remains owner-gated.
- **Panel routes:** all four flash routes PONG (luna verified 2026-09-08).
  Run log + leg reports: `.scratch/q2/panel/`.

## 4. Open items

**Mine (in order of value):**
1. Task #8 — decumulation substrate (A_max derivation, ladder at ceiling +
   planned spending, SS 78% base, 2032 step). Recommended next.
2. Task #3 — 11 unresolved header tabs (proposals with evidence; owner
   confirms). Task #7 — layouts allow-list for `trading-*` unlisted tabs.
3. 2018 IRS transcript fetch — closes the only tax-history hole.

**Owner-gated:**
- Task #6 rulings (spending level · stop age + SS@67 · five money questions ·
  commit/remote posture · zones & inventory · D9/D13).
- Card + broker CSV exports into Drive (loaders ready).
- Schedule C / LLC loss source-of-truth decision.
- Q2 refresh / Q3 reopen signals.

## 5. Traps learned this session (do not rediscover)

1. **Tax-prep Records PDFs print BLANK official forms** (1040, Schedule C) —
   amounts live on summary pages and the Tax History Report, not on the forms.
2. **Tax History Report grid:** value cells are left-aligned ~19pt off the
   centered year labels; map cells to year columns by label x-span (widened),
   never by exact x-clustering. Labels wrap ("Total itemized/" +
   "standard deduction + values" on the second line). Windows overlap —
   cross-check duplicates across PDFs.
3. **Transcript label drift:** 2019/2020 print "WAGES, SALARIES, TIPS, ETC";
   the 2022 redesign prints bare "WAGES:" (Box 1) + MEDICARE WAGES (Box 5);
   itemized years print "NO STANDARD DEDUCTION PER COMPUTER" (a real 0, not a
   parse artifact). No transcripts print Box-3 SS wages — `ss_wages` carries
   Box 5 by documented convention.
4. **Workflow `agent(schema)` null ≠ dead route:** a null structured result
   can mask a live route. Discriminate with a schema-less plain probe before
   condemning (the 3-attempt rule applies to the schema path too).
5. **A marginal_bracket can silently be an effective rate** (the 2022 '22%'
   mislabel) — label brackets with their source (the preparer's own bracket
   row) or leave NULL; never derive-and-store without saying so.
6. Provider effort maps are app-level and owner-owned; the `off` value is
   sent verbatim on effort-less requests — `none`, not `minimal`.

## 6. Do-not-do (carried forward + new)

- Never ask Joe a fact question the store can answer — query first, rule only.
- Never mutate the owner's live sheets; findings are flag-only with evidence.
- Never treat a blank official form page in a tax PDF as data.
- Never re-enter extracted figures without the panel cross-check on new
  parser families.
- Never edit `~/.dsh/settings.yaml` provider blocks beyond the owner's
  pattern — effort/compat semantics are load-bearing for the whole app.
- Never store a derived value without `needs_verify`/`presence` labeling.
- Never introduce a blocklisted vendor name into committed docs — the hygiene
  gate flags it (this session's vendor-name mentions were scrubbed from all
  committed files).
- When a bug's root cause is an already-planned deployment (e.g., finpage
  persistence failing on file:// while GitHub Pages hosting was pending),
  lead with the root cause and the planned fix — offer workarounds only
  after, never instead.

## 7. Where things live

`tools/` code + ratified schema + panel protocol · `private/` all data-bearing
artifacts (store, curation, decisions log, defects, layouts, provenance) ·
`.scratch/` harnesses, panel reports + run log, q1/q2 scripts incl.
`.scratch/q2/tax_scan.py` (the tax parser, `--load` mode) · `docs/` handoffs,
TASKS, North Star, plans.
