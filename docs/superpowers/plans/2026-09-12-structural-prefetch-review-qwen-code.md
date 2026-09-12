# Panel review — structural pre-fetch blueprint v0.2.1 (+ v0.2)

**Reviewer:** `qwen-code` (owner-directed review session, 2026-09-12)
**Version reviewed:** `2026-09-12-structural-prefetch-v0.2.1.md` **read together with**
`...-v0.2.md` — the pair is the current design, per the version rule in the review prompt.
No higher-numbered blueprint exists in this directory.
**Method:** findings derived from the toolkit source and the structure-only audit
evidence, not from the blueprint's own summaries. Every load-bearing claim below was
checked against a file; citations are given.

> **Reviewer identity — flag for the COS.** The prompt asks that the filename carry the
> reviewer's model name. My exact model id is not exposed to me in this session, so I
> have used `qwen-code` rather than claim a seat from `tools/PANEL.md` §2 that I cannot
> verify. Re-suffix if a specific seat name is required for the convergence grade.
> I am not `deepseek-flash`, so the chair exclusion (`tools/PANEL.md` §2) is satisfied.

> **Contamination disclosure.** §4 of the prompt asks the reviewer to form findings
> before reading the Appendix (§8). I read §8 during session catch-up, before starting,
> so that ordering is not available to me. Mitigation: every finding below is grounded
> in a source-file citation or a measurement over `.scratch/csv_audit/grid/*.json`, and
> §4 of this review states explicitly which findings are mine, which I merely agree
> with, and which I contradict. Treat the *independence* of this leg as **weakened**,
> not absent.

**Boundaries honoured:** nothing under `private/` was opened. No financial values
appear below — cell counts, row/column extents, column letters and formula *shapes*
only, all taken from committed method files or the already structure-only audit.
Read-only apart from this file.

---

## 1. Verdict

**NOT READY TO RATIFY — 20 findings (R1–R20): 3 blockers · 11 majors · 5 minors · 1 nit.**
*Counting rule:* R16 is dual-graded `MINOR→MAJOR` and is counted here as a **major**,
because it is load-bearing for R7a; as a hygiene matter alone it would be a minor.

v0.2's semantic repair is good work. The two-fact model (`origin` × `presence`), the
merge-before-blank ordering, override≠disagreement, quarantine-instead-of-outage and
the shadow-store/promotion/rollback spine all answer real round-1 findings, and E1–E8
are the right instincts. As a *semantics* document the pair is close.

It fails on a different axis than round 1 did: **coverage and scope, not meaning.**
Three problems dominate.

1. **The artifact is smaller than the data.** The structural read covers 60 rows × 30
   columns by default; the values read it replaces covers 100,000 × 200. Nothing in
   v0.2/v0.2.1 states the artifact's bounds or asserts completeness — and the audit
   that justifies the whole design was itself collected inside an 80-row window, with
   **four tabs, including spec #1, truncated by it** (R1, R2).
2. **The schema change lands on the wrong table, at the wrong grain.** `fact_state` is
   the **only** table in the schema with a `presence` column, so at most **1 of the 8
   inadequate specs** can receive the proposed semantics — including none of the five
   holdings tabs, whose target `holding_state` carries no `presence`, no `quality` and
   not even `needs_verify` (R3). Meanwhile `src_column` — which already declares exactly
   the per-column `metric_id`/label binding that E5b and D-4 propose to invent in JSON —
   has **never been written by any tool** (R4).
3. **The safety net does not reach the largest family in the audit.** `load_holdings`
   addresses cells by hardcoded ordinal and consults no allow-list, no `header_row`,
   no `skip_rows`. E4's shape assertions, E5b's letter-join, D7's coordinate audit and
   P1's inclusion diff are all specified in allow-list coordinates, so **five of the
   eleven specs migrate with none of them firing** (R11).

If only one thing is fixed before ratification, make it R1+R2: a truncated artifact
silently ingests a fraction of the data while passing every gate this blueprint
proposes. Everything else is a semantics argument that can survive another iteration.

---

## 2. Findings

| ID | Sev | § | Finding | What I would change |
|---|---|---|---|---|
| **R1** | **BLOCKER** | D5/P1, D2, E4 | **The structural read covers 60 rows × 30 columns; the values read it replaces covers 100,000 rows × 200 columns — three orders of magnitude apart.** `grid_structure(max_rows=60, max_cols=30)` (`tools/bagend/sheets.py:181-182`); CLI default `--max-rows 60` (`tools/bagend.py:310`). `read_tab` — the path that produces today's CSVs — defaults its row bound five orders of magnitude higher (`sheets.py:99-100`). The blueprint swaps one for the other and never states the artifact's bounds. None of E4's three assertions — expected labels at the declared header cells, `skip_rows`/`first_data_row` row *shapes*, and presence of declared merges — tests the **extent** of the data below `first_data_row`, so **all three pass on an artifact truncated at row 60**. | P1 asserts the artifact covers the tab's used extent, taken from `metadata()` (`rowCount`/`columnCount`, already returned) and refuses on shortfall. The artifact records requested range, effective range, and row/col counts. `--max-rows` for the loader path defaults to the tab extent, not 60. |
| **R2** | **BLOCKER** | evidence base, D5/P1, E8 | **The audit was collected inside an 80-row window and four tabs are truncated by it.** `.scratch/csv_audit/run_sweep.py:64` uses `max_rows=80, max_cols=30`. Measured extents over `grid/*.json`: `stats__Net-Worth_Data` maxrow **80** (row 79 = 4 cells, row 80 = 5 cells — populated *at* the boundary), `pnl-records__Gain-Loss_Fidelity_Rollover` maxrow **80** (15 cells in row 79 *and* 15 in row 80), `pnl-records__Gain-Loss_TD` maxrow **80**, `stats__Net-Worth_P-Table` maxrow **80**. So "194 formula cells / 295 non-empty" for spec #1 is a **lower bound on a truncated window**, presented in AUDIT.md and in the prompt §2 as a measurement. (`Gain-Loss Cost Basis` stops at row 69, maxcol 8 — the 97.8% worst-case number **is** sound.) Columns are fine: max observed 29 of 30, but with one column of headroom and no assertion. | Re-run the sweep at full extent before P4 is scoped, and restate every count in AUDIT.md **with its window**. leg-qwen's round-1 B2 raised the range-cap risk as a hypothetical and recommended exactly this assertion; it is not hypothetical, and neither B2 nor its remedy appears in the §8 appendix. |
| **R3** | **BLOCKER** | D2, E2 | **`fact_state` is the only table in the schema with a `presence` column — so at most 1 of the 8 inadequate specs can receive the proposed semantics.** `grep -n presence tools/schema/books.sql` returns exactly one column definition, `books.sql:188` (`fact_state`). Every other fact family lacks it: `fact_event` and `meter_reading` have `quality`, `ss_benefit_estimates` and `tax_year_facts` have `is_estimate`, `position_lot` and most others have only `needs_verify`, and **`holding_state` (`books.sql:609-624`) has none of the three** — no `presence`, no `quality`, not even `needs_verify`. It is the least-governed fact table in the store and the target of the `holdings` family, i.e. 5 of the 11 specs (the `GOOGLEFINANCE` tabs). Family dispatch is `run_wave1` (`loader21.py:580`). Consequence: this holds **whichever** family the two specs I could not resolve belong to (R18), because no table but `fact_state` has the column. D2's "this is the only place v0.2 touches the store's shape" therefore delivers derivation semantics for **at most 1 of 8** inadequate specs; the 97.8%-formula worst case and all five live-quote tabs get nothing. | Either extend `presence` (+ the new columns) across every fact family the artifact feeds — and price that into the rebuild — or adopt R4 and put derivation at column grain on `src_column`, which reaches every family without touching any of them. Separately: `holding_state` missing `needs_verify` looks like an oversight in the wave-2 DDL and should be fixed whatever D-1 decides. |
| **R4** | MAJOR | D2, E2, E5b, D-1, D-4 | **`src_column` already declares the per-column binding E5b/D-4 propose to invent — and no tool has ever written to it.** `books.sql:100-111`: `src_column(tab_id, col_index, header_text, header_occurrence, account_id → dim_account, metric_id → dim_metric, unit)`, `UNIQUE(tab_id, col_index, header_occurrence)`. `grep -rn src_column tools/` returns **only the DDL and one comment** — zero INSERTs. It already carries `metric_id` and `header_text` (= E5b's `expected_label`), and is FK'd to `dim_metric`. Derivation in this corpus is a **column-grain** property: the audit speaks in columns ("column G in every data row", "interleaved A/H formula pattern", "47–77 formulas incl. `I/J/K/O/P/Q/W`"). | Put `origin`, `derivation_kind` and a `formula_shape` digest on `src_column` — **additive, nullable, no CHECK rebuild, no table migration**. Keep `presence` per-row, extended only on families that need it. Populate `src_column` from the artifact in P1. This removes D-1's table rebuild entirely and gives P4's per-column reconciliation a real table to reconcile *against*. |
| **R5** | MAJOR | D5/P2 | **P2's shadow-vs-live gate has no divergence rule, and a large intentional divergence is already known.** Today `load_state_spine` *skips* blank cells (`loader21.py:302`) and hardcodes `presence="measured"` on every insert (`loader21.py:334`). Materializing `zero_from_blank` turns every blank-in-live-row cell into a **new fact row**. The shadow store will differ from live by a large, *correct* row-count increase. D5 classifies P1 divergences (intended fix / bug / unknown) but says nothing for P2, so the gate either fails by design or gets waved through. | Apply the same three-way classification to P2, with `zero_from_blank` materialization **pre-declared and counted** as an intended divergence, so the gate measures only the unexpected residue. |
| **R6** | MAJOR | D1, D2, D5/P0 | **`content_hash` excludes `presence`, and the dedupe probe is not scoped to current rows.** Recipe is `make_hash(acct, met, as_of, seq, val)` (`loader21.py:317`); `books.sql` documents it as a LOADER CONTRACT "enforced by the harness". A measured `0` and a `zero_from_blank` `0` therefore hash **identically** — while the entire point of the new value is that they mean different things. Separately, the skip probe `SELECT 1 FROM fact_state WHERE content_hash=?` (`loader21.py:318`) has **no `superseded_by_batch_id IS NULL` filter**, though its comment says "already current"; a value that reverts to a previously-superseded number is silently dropped. Materializing many zeros raises the collision rate sharply. `[unsure]` how often reversion bites in this corpus. | Include `presence` (and `origin`, if per-row) in the hash recipe and scope the probe to current rows. Both are **contract** changes and belong in P0 — discovering them in P3 means re-running the migration. Add a harness case: same `(acct, metric, as_of, seq, 0)` arriving once `measured` and once `zero_from_blank`. |
| **R7** | MAJOR | D1, E2, E1, D-3 | **The total function is not total.** Three unmapped states, one of them a *dropped round-1 finding*: **(a)** `grid_structure` classifies by `userEnteredValue.formulaValue` presence and otherwise emits `kind="literal"` — an array-spill cell has an effective value and no entered formula, so it maps to `origin='entered', presence='measured'`, the exact failure §1 exists to prevent. **leg-qwen m1 raised this in round 1; it appears in neither D1's table nor the §8 appendix.** Empirically, all 15 `ARRAYFORMULA` instances in this corpus are wrapped in `ARRAY_CONSTRAIN`, so their output is bounded — **but the constraint arguments are masked to `n,n` by `_redact_formula`, so the actual extent is not determinable from the structure-only evidence** (this is R16, and it makes R16 load-bearing rather than cosmetic). Whether any tab spills is therefore **unknown**, not "no"; the classifier fail-opens either way. **(b)** The owner has said some formulas live in **cell comments**; `sheets.py` never requests `notes` (grep: zero hits). A literal cell whose derivation is documented in a note maps to `entered`/`measured` and is simply wrong — this makes D-3 a *correctness* requirement, not a completeness option. **(c)** A formula cell with no `effectiveValue` (uncalculated) is emitted `kind="formula"` with no `effective_type`; D1 has no row for it. **(d)** `derivation_kind` is **not a partition**: E2's `aggregate` and `chain` overlap. Verified in `trading-2026__Data.json`: `I6 = SUM(I2:I4)` where `I2:I4` are cross-sheet `LOOKUP`s — simultaneously aggregate *and* chain, in a single-valued column. | Add an `unclassified`/`spill` bucket that **refuses** rather than defaulting to `measured` (this also answers leg-qwen m1's "any unclassifiable cell must refuse, not default"). Make `derivation_kind` either a set, or three kinds + an orthogonal `depends_on_derived` boolean, or state a precedence order among the four. Adopt D-3 (see §5). |
| **R8** | MAJOR | E7, D6 | **E7's remedy does not fix the problem leg-glm F8 identified, and F8's actual recommendation was dropped.** `src_ref.sheet_modified` is one **file-wide** timestamp, and Sheets exposes no per-tab modified time. "Restrict the staleness check to tabs the spec actually reads" cannot work: any edit anywhere in the file still bumps the only timestamp available, which is precisely the over-refusal F8 named. leg-glm F8 recommended the correct thing — *"per-tab change detection … uses a content hash of the tab's structural payload, not modifiedTime"* — and v0.2.1 substituted a different, non-functional rule. | Adopt F8 as written. A structural fingerprint (tab list + merges + formula-shape map, values redacted) is computable from the artifact at pre-fetch, is offline and auth-free, detects the changes that matter (structure moved) and ignores cosmetic edits. Keep `drive_modified` as a coarse first-pass signal only, and make a mismatch **warn + re-fetch**, never refuse. |
| **R9** | MAJOR | D1 (copy rule), D6/T13 | **The `copy` anti-double-count rule has no enforcement point in the store.** `v_state_current` (`books.sql`) does not expose `presence`, and would not expose the proposed `origin`. `v_net_worth` does `SUM(value_num)` over `v_state_current` with no filter, and its `n_error` counts `value_num IS NULL` — **not** `presence='error'`. So the only aggregating view in the schema cannot see the distinction D1 exists to create, and T13 would test loader code while the store's own view still sums copies. The view's header comment claims P07: "a total can never look complete while a component is missing" — that principle is currently implemented on the wrong signal. | Expose `presence` and `origin` through `v_state_current`, and give `v_net_worth` a composition breakdown (`n_measured` / `n_estimated` / `n_copy` / `n_zero_from_blank` / `n_error` keyed on `presence`). This extends P07 to "a total can never look *measured* while a component is not." Cheap, and it is what makes D1 queryable rather than merely recorded. |
| **R10** | MAJOR | D3, D5, E6 | **Five of the eleven specs depend on Task #7, which is OPEN and is not named as a prerequisite.** In every one of the five holdings `Data` artifacts the sole cross-sheet formula column is **`I`**, pulling from three per-account state tabs — the same three named in `ACCOUNT_TOKENS` (`loader21.py:959`). Those are exactly the "per-account state tabs" Task #7 exists to allow-list. D3's refusal case 1 ("no allow-list entry") and E6's provenance cross-check would therefore **fire on the holdings specs** the moment P2 runs. | Add Task #7 as an explicit P2/P3 prerequisite for the holdings family, or scope the first migration wave to specs whose dependencies are already allow-listed (`stats`, `ss_earning`) and say which. A dependency this concrete belongs in the phase table, not in a risk register. |
| **R11** | MAJOR | D3, D7, E4, E5b, D-4 | **The holdings loader is positional and consults no allow-list, so most of the proposed safety net does not reach it.** `load_holdings` (`loader21.py:962-1010+`) reads `r[0]`, `r[1]`, `r[3]`, `r[5]`, `r[6]`, `r[7]`, `r[8]`, filters on module-level `ACCOUNT_TOKENS` (`:959`) and a hardcoded ticker list, and reads **no** `header_row`, `first_data_row`, `skip_rows` or allow-list column. Consequences: **(i)** E5b's letter-join and D-4's per-column fields have no bearing on 5 of 11 specs; **(ii)** D7's coordinate audit cannot fire on a column insertion there — `r[6]` silently becomes a different quantity and nothing asserts; **(iii)** E4's shape assertions have no declared coordinates to check; **(iv)** P1's "inclusion" diff would flag every deliberate skip (INDEX rows, watchlist block, annotation rows, dividend-ladder columns, `Sub Total`) as a divergence, swamping the report. | Either bring the holdings path onto the declarative layout **before** migrating it, or require its skip set to be declared so P1 can classify it as intended. Do not let the blueprint assume one join mechanism covers all eleven specs — it covers at most six. |
| **R12** | MAJOR | D5, D1, E1 | **The artifact emits the number-format *type*, not its *pattern* — which blocks D5's own remedy for #19(c).** `grid_structure` requests `userEnteredFormat(numberFormat)` but reads only `.get("type")` (`sheets.py`, the `nf = …` line), so `rec["format"]` is an enum (`DATE`, `NUMBER`), never `yyyy-mm-dd`. D5 promises "the new path must **not** reproduce" the `_typed` serial→date heuristic (`sheets.py:90-94`, Task #19(c)), and leg-glm F7 recommended typing dates **from format, not from a range heuristic**. Without `pattern` the loader cannot distinguish `yyyy-mm-dd` from `mm/dd/yyyy`, so the heuristic cannot actually be replaced. **leg-qwen m2 raised this in round 1; it is not in the §8 appendix and not in D1–D7/E1–E8.** The pattern is already in the API response — it is fetched and discarded. | Emit `numberFormat.pattern` alongside `type` (a one-line change to the `nf` extraction). Make "date typing derives from `pattern`, never from a numeric range" an explicit P1 gate, and add the regression test that #19(c) currently lacks. |
| **R13** | MAJOR | D3, E5a | **D3's narrowed refusal list drops North Star invariant 5.** Invariant 5: "header rows are confirmed by a human (Joe), never guessed; **unresolved headers are refused loudly**." D3 narrows refusal to three cases — no entry, override with no entry, override of a non-overridable field — and `unresolved` is not among them. E5a then *explicitly permits* an override where the entry "lacks the field or holds `unresolved`". That is the gap-fill hatch leg-glm F2(iii) asked for, and it is right — but as written a loader author's `reason` string satisfies it, which is **not** a human confirmation. **leg-qwen m6 raised this in round 1; it is not in the appendix.** | Keep E5a's hatch but require the gap-fill override to carry an **owner ruling reference** (a decision-memo id or a dated ledger row), and log it to the load evidence. Restate invariant 5 as a fourth refusal case: an `unresolved` header with no owner-referenced override refuses. |
| **R14** | MINOR | E8, AUDIT.md | **E8's arithmetic is right but its source document is still wrong, and neither states the definition.** Enumerating AUDIT.md's verdicts table gives **8** substantively inadequate specs (#1, #2, #5-worst-case, #6–10) + 1 marginal + 1 obsolete + 1 not-a-sheet = 11 ✓. Its count line says "inadequate **9** · marginal 1 · obsolete 1 · not-a-sheet 1" = 12, with a parenthetical that admits overlap without resolving it. Its headline "**9 of 11** read tabs where formula-derived cells are pervasive" is 8 inadequate + 1 marginal. E8 correctly uses 8 but does not say it is correcting AUDIT.md. Per JOURNEY §5 the definition must ship with the number. | Correct AUDIT.md's count line to 8, and state the definition: *"formula-pervasive = 9 (8 inadequate + 1 marginal); inadequate = 8."* Otherwise a reviewer reconciling P4's scope against AUDIT.md concludes a spec is missing. |
| **R15** | MINOR | D6 | **"`--structure-only` must run `_redact_formula`" is already implemented.** `grid_structure` does `rec["formula"] = raw if with_values else _redact_formula(raw)`. The requirement is stated as new work. | Strike it, or — better — convert it into a regression test, since it is a hygiene control and currently untested. Note leg-qwen's NIT still stands: `_redact_formula` protects quoted strings, so an `IMPORTRANGE` file id inside a formula echoes to any structure-only consumer. That **is** unaddressed and is a delegate-facing leak vector. |
| **R16** | MINOR→MAJOR | D1, D6, R7a | **`_redact_formula` masks *shape* parameters, not just financial literals.** The redactor masks every unquoted numeric, so `=ARRAY_CONSTRAIN(x,1,1)` → `=ARRAY_CONSTRAIN(x,n,n)`. **Observed:** the corpus's `ARRAY_CONSTRAIN` calls appear in `grid/trading-2026__Data.json` as `(…,n,n)` — the extent is gone, which is why R7a cannot be settled from structure-only evidence. The same loss applies to thresholds (an `IF` comparing against a literal in the 20,000 band) and to date arguments. Graded MINOR for hygiene, **MAJOR for anything that must classify array behaviour** — i.e. it is load-bearing for R7a and should be resolved before P1. | Emit a `formula_shape` digest (function names + arity + reference pattern, literals removed) alongside the masked string, **or** compute the few structural booleans the loader needs — `single_cell_constrained`, `has_cross_sheet_ref`, `has_external_func` — *before* masking, so the values never enter the artifact. This also supplies R4's `formula_shape` column for free. |
| **R17** | MINOR | D2 | **"Exactly as v0.2.4 was handled" does not transfer to a CHECK change.** v0.2.4 was an `ALTER TABLE … ADD COLUMN` of nullable columns — `books.sql`'s own header calls it "the one sanctioned exception" to rebuild-from-Drive. A CHECK constraint cannot be ALTERed; the operation is create-new / copy / drop / rename. An "ALTER-parity harness" has **no ALTER statement to compare**, so the cited precedent does not cover the operation. | Specify the parity harness for a CHECK change as *rebuilt table vs freshly created table* (row counts, `sqlite_master` SQL text, per-column typeof census). Or adopt R4 and drop the rebuild from scope — then D2 is additive and the v0.2.4 precedent genuinely applies. |
| **R18** | MINOR | process, D2, §5 boundaries | **The spec→family→target-table mapping is method, but it lives under `private/`.** A reviewer honouring §5 ("do NOT read anything under `private/`") cannot verify D2's scope claim, which is the single most load-bearing question in D-1. I resolved the target family for **9 of the 11** specs from the dispatch in `run_wave1`; `pnl_records:cost-basis` and `fi_balances:over-time` remain **`[unsure]`** — I could not determine their target tables without opening the curation file. (R3 does not depend on resolving them: no table but `fact_state` has a `presence` column, so either way the answer is the same.) | Publish the spec→family→target-table mapping in `tools/` (it names no values and no account numbers, so `check_hygiene.sh` is satisfied) or inline it in the blueprint. A schema-scope claim that no bounded reviewer can check is a claim the panel is being asked to ratify on trust. |
| **R19** | MINOR | D3, E5b | **`src_column` is keyed by `col_index` + `header_occurrence`; D3/E5b switch addressing to letters, with no migration row.** `src_column.col_index` is `INTEGER >= 0` and the UNIQUE key includes `header_occurrence` — which exists for the repeated-label case Task #3 found (`NEAR`'s totals inside header cells). Letter addressing is 1-based and has no occurrence dimension. **leg-qwen m5 raised this in round 1; it is not in the appendix.** | If R4 is adopted, state the letter↔index conversion explicitly (`A ↔ 0`), keep `header_occurrence` as the tiebreak for repeated labels, and require the composed label to be **unique per tab** — refuse on collision rather than silently overwriting a `metric_id` (leg-luna #7's collision concern). |
| **R20** | NIT | adjacent, out of scope | **`trg_src_audit` misreports what changed.** The trigger on `UPDATE OF precedence, sheet_modified` inserts **two** rows unconditionally — one labelled `'precedence'`, one `'sheet_modified'` — regardless of which column actually changed. Pre-existing and out of scope for this blueprint; flagged rather than fixed per the flag-only rule. Relevant because E7/D6 propose to reason about `sheet_modified`. | Separate trigger per column, or one row with `column_changed` derived from `OLD`/`NEW` comparison. File against Task #19(d) (doc/tooling drift) rather than this blueprint. |

---

## 3. The five open questions

**Q1 — Is the total presence function actually total? Which cell state is still unmapped? Is the `copy` rule enforceable? Is `external_links` overriding `kind` the right precedence?**

Not total. Unmapped: **array-spill cells** (fail-open to `entered`/`measured` — R7a, a
dropped round-1 finding); **note-borne derivation** (R7b); **a formula with no
`effectiveValue`** (R7c). `derivation_kind` is additionally **not disjoint** — verified
`I6 = SUM(I2:I4)` over three cross-sheet `LOOKUP`s, which is both `aggregate` and
`chain` (R7d).

The `copy` rule is enforceable in the loader and **not** in the store: no view exposes
`origin`, and `v_net_worth` sums regardless (R9). "No aggregation may sum a `copy`
together with its source" is currently a sentence, not a control.

`external_links` overriding `kind` is the **right precedence** — leg-qwen M2's
pasted-literal-external case is real and this resolves it. But it depends on a
hand-curated map that the artifact can now derive mechanically, and v0.2 does not.
Evidence: the cross-sheet column in all five holdings tabs is `I`, in every case
targeting the same three account tabs. **leg-luna #12 recommended storing resolved
dependencies and validating them against the declared map; v0.2 adopted the precedence
but dropped the validation.** Add it as a D7-shaped gate: derive cross-sheet reference
candidates from the artifact, reconcile against `external_links`, flag every
disagreement. It is the same trick D7 already applies to coordinates, aimed at a field
D7 forgot.

**Q2 — Is one CHECK value plus one column the minimum? Is `origin` the right dimension?**

No, and it is arguably the wrong **layer**. `origin`/`derivation_kind` are structural
facts about a *source column*, stable across loads, and the audit's own evidence is
column-grain. Replicating them per row costs a CHECK rebuild across a schema where
`presence` exists on exactly one table (R3) — so the per-row choice buys almost nothing
and delivers almost nothing. `src_column` already exists, already carries `metric_id`
and `header_text`, and is already empty (R4).

The minimum is: **derivation → `src_column`** (additive, nullable, no rebuild);
**`presence` + `zero_from_blank` → per-row, on the families that actually need it**,
because `presence` genuinely varies within a column (a blank here, an error there).
Note that the corpus already proves mixed-grain columns: `ss_earning:payment-estimates`
has formulas at `H16` and `H25:H31` only. So the design needs a **column default with a
per-cell exception**, not one or the other.

`presence` itself is the right dimension and `zero_from_blank` is correctly owner-
ratified. Two contract details must move with it: `content_hash` must include it (R6),
and the views must expose it (R9).

**Q3 — Does D3 close the holes without opening new ones? Can the non-overridable list be gamed? Is quarantine safe?**

Override≠disagreement is right and genuinely dissolves the self-deadlock. Role-gating
(`derived`/`scratch`/`worksheet`/`duplicate` must be explicitly acknowledged) closes
leg-qwen M4's hole through invariant 6. Pattern expansion is necessary — the five
holdings specs are the per-year case.

Three holes remain. **(i)** The non-overridable list is a single field, `key_column` —
thin, and meaningless for the holdings family, which declares no key column at all
(R11). **(ii)** E5a's gap-fill hatch can be satisfied by a loader author's `reason`
string, which regresses invariant 5's "confirmed by a human (Joe), never guessed" (R13).
**(iii)** Refusal case 1 collides with Task #7's unlisted tabs (R10).

**Is quarantine safe?** Only conditionally, and the blueprint does not state the
condition. The question that matters is what happens to rows **already loaded** from a
spec that is now quarantined: if they stay current, the store keeps publishing data
whose layout just failed validation — a silent-staleness path worse than an outage,
because it is invisible. Specify: a quarantined spec's prior rows either stay current
**with a visible quarantine marker surfaced by every consumer view**, or are marked
superseded. My recommendation is the former plus a `load_batch.status='partial'`
(note the CHECK already allows `'partial'`) and a standing report — an outage is
recoverable, a silently stale published total is not.

**Q4 — Is promotion genuinely atomic, is rollback real, is the phase order safe?**

**Rollback is real** — a kept pre-promotion file is the strongest available mechanism,
and it beats rebuild-from-Drive here because rebuild means re-parsing 372 statement
PDFs plus Drive quota. Keep it.

**Atomicity is under-specified.** "File swap" needs to say `os.replace` (atomic rename)
rather than copy, and needs to address #19(a): the query path now opens `mode=ro`, and
on Linux a rename leaves an already-open reader bound to the **old inode**. That is
*safe* — a long-lived reader finishes on a consistent store — but it should be stated,
because "atomic promotion" reads as "all readers see the new store immediately," which
is false.

**Phase order is not safe as written.** P0 rebuilds the schema before Q2/R3's scope
question is answered, so the most expensive and least reversible phase commits first to
a shape that may be wrong. P1's parity gate is the weakest link in the plan (R1, R2,
R11, R12). P2's gate has no divergence rule (R5). Reorder: settle R3/R4 (which tables,
which grain) → P1 artifact + completeness assertion → re-measure the audit (R2) → *then*
P0 schema, now correctly scoped.

**Q5 — What is still not covered by the verification plan?**

In rough order of cost-if-missed:

1. **Range completeness** (R1) — the single most important missing assertion, and the
   cheapest to add: compare the artifact's extent against `metadata()`.
2. **The row-count increase from `zero_from_blank`** (R5) — a known, large, intentional
   divergence with no classification rule.
3. **Hash behaviour on zeros** (R6) — no test asserts that a measured 0 and a
   blank-derived 0 are distinguishable, or that reversion is not dropped.
4. **The positional holdings path** (R11) — no proposed test can fire on it.
5. **View-level enforcement of the copy rule** (R9) — T13 tests the loader; nothing
   tests that `v_net_worth` excludes copies.
6. **Format-pattern-driven date typing** (R12) — the regression test #19(c) never got.
7. **Unresolved-header refusal** (R13) — invariant 5 has no test in T8–T13.
8. **Count pinning.** leg-qwen m4 asked that formula counts be asserted *within the
   artifact being loaded*, not against an audit-time constant. With R2 showing those
   constants are truncated lower bounds, this matters more now: any test pinned to
   "539" or "194" is pinned to a number measured on the wrong window (the 539 is sound;
   the 194 is not).

---

## 4. Relationship to the Appendix (§8) and to the three round-1 legs

Reached **independently** (not in the appendix, not in any leg): R2 (the truncation is
*measured*, not hypothetical), R3 (`presence` exists on one table only; `holding_state`
has no `needs_verify`), R4 (`src_column` is declared and never written), R5, R6, R9,
R10, R11, R14, R16, R17, R18, R20.

**Agree, and note that v0.2/v0.2.1 adopted them correctly:** merge-before-blank
ordering (glm F3 / qwen M1 / luna #6 → E3); error cells (glm F7 / qwen M6 / luna #5 →
E1); override≠disagreement (glm F2 / luna #10 → D3); provenance cross-check (glm F11 /
luna #11 → E6); shadow store + atomic promotion + rollback (luna #14 → D5); parity
against the source rather than the CSV (qwen B3 → D5); coordinate audit (qwen M5 → D7);
quarantine instead of blanket refusal (luna #9 → D3); the arithmetic correction
(glm F12 → E8).

**Agree, and note that they were raised in round 1 and are still unaddressed** — the
appendix's implied completeness is wrong on these four:

| Round-1 finding | Leg | Status in v0.2 + v0.2.1 |
|---|---|---|
| Range must be asserted ≥ the tab's grid extent (B2, 2nd bullet) | qwen | **Unaddressed** — and now empirically violated (R1, R2) |
| Array-spill cells fail-open to `literal`/`measured` (m1) | qwen | **Unaddressed** — absent from D1's table (R7a) |
| `format: "yyyy-mm-dd"` not obtainable from the field mask (m2) | qwen | **Unaddressed** — blocks D5's own #19(c) remedy (R12) |
| `src_column` keyed by index vs letter addressing (m5) | qwen | **Unaddressed** (R19) |
| `header_row: "unresolved"` refusal not restated (m6) | qwen | **Unaddressed** — and E5a now permits overriding it (R13) |
| Per-tab change detection via structural content hash, not `modifiedTime` (F8) | glm | **Mis-adopted** — E7 substitutes a rule that cannot work (R8) |
| Validate resolved dependencies against the declared external-link map (#12) | luna | **Partly adopted** — precedence yes, validation no (Q1) |

**Contradict the appendix:** its claim that round-1 findings were comprehensively folded
in. Six items above were not, and one (F8) was folded in *incorrectly*. None of the six
appears in §7b's "known gaps v0.2 does not close" either, so a reader trusting the
appendix would believe they were resolved.

**Contradict leg-glm F4's framing** (adopted as D1's `constant_formula`): the fix is
right, but glm's premise that this mislabels "nearly a whole table" rests on the 539/551
count for `Gain-Loss Cost Basis`. That count **is** sound (row 69, col 8 — inside the
window), so the conclusion holds; I note it only because the *sibling* counts in the
same argument are not sound (R2), and a reviewer should not generalize from them.

---

## 5. Recommendations on the four owner decisions (§7 of the prompt)

### D-1 — Schema extension

**Recommend:** derivation (`origin`, `derivation_kind`, `formula_shape`) → **`src_column`**,
additive and nullable. `presence` → per-row, extended with `zero_from_blank` on the
families that need it, plus a per-cell exception mechanism for mixed-grain columns.
No CHECK rebuild, no table migration, and P4's per-column reconciliation gets a real
table to reconcile against.

**Strongest argument against:** `presence` genuinely varies *within* a column, so a
purely column-grain model cannot express it — and the corpus already proves the point
(`payment-estimates` column `H` is a formula at `H16` and `H25:H31` only). If the
per-cell exception path is not built, column-grain derivation will be wrong for exactly
the partial-column case the audit flagged as MARGINAL.

**Evidence that would change my mind:** a load-bearing query that needs to filter or
aggregate on `origin` per row rather than per column — e.g. a net-worth total that must
exclude derived components row-by-row. If that query exists, `origin` belongs on the
fact row and the rebuild is justified; note that R9's view work is required either way.

### D-2 — `fi_balances:over-time`

**Recommend (a):** keep it CSV, and honour `header_row` on the CSV path (which also
settles Task #18's "pick one rule" in the direction of fewer code paths).

Two arguments the blueprint does not make, both against (b): re-creating the file as a
Sheet **requires the owner to modify his own Drive** — the COS may never write there
(`AGENTS.md` §5.1) — and it would leave **two copies** of the same data in Drive, which
is the duplicate-source hazard invariant 6 exists to prevent and would need its own
`duplicate` role ruling.

**What (a) costs, stated honestly:** the CSV path can never carry structural evidence,
so `fi_balances` rows must **not** be stamped `origin='entered'` as though validated.
Record `structural_coverage='none'` (or set `needs_verify` with a reason) so the store
never claims a structural check that did not happen. That is the whole cost, and it is
a labelling cost, not an accuracy cost — a plain CSV has no formulas and no merges, so
there is genuinely nothing structural to lose.

### D-3 — Cell notes/comments

**Recommend: yes — but reframe it as a correctness requirement, not a completeness
option.** D1 claims the presence function is total over cell states. A literal cell
whose derivation is recorded in a note is a cell state that maps to `entered`/
`measured` and is **wrong** (R7b). Without `--with-notes` the totality claim is false
for a case the owner has already told us exists in this corpus.

**Shape it narrowly:** fetch notes; store only `has_note` (boolean) plus any note text
that parses as a formula, masked through `_redact_formula`. Never ingest free text into
the store.

**Strongest argument against:** notes are free text that may carry personal content, so
they enlarge both the fetch and the hygiene surface — and unlike `tools/`, artifacts in
`private/` are not gated by `check_hygiene.sh`. The real leak path is a delegate brief:
a leg quoting "structure" could quote a note. Mitigate by emitting only
`has_note` + `note_is_formula` + the masked formula to any structure-only consumer.

**Evidence that would change my mind:** a sweep showing zero notes on the tabs behind
the 11 specs. That is cheap to run and would make this decision moot — run it before
building the feature.

### D-4 — Per-column fields in `layouts.schema.md`

**Recommend: do not add them to the JSON. Populate `src_column`** (R4), which already
declares `metric_id` and `header_text` (= `expected_label`) and is FK'd to `dim_metric`;
add `role` there. The allow-list stays the **human-confirmed gate** (header rows, tiers,
skip rows, dedupe, grain); the store holds the **machine-joined column map**, generated
from allow-list + artifact at load and never hand-edited.

**Strongest argument against:** two places then describe columns, which is exactly the
"duplicating state across curation" problem Task #18 already names for `header_row` vs
`csv_skip`. The answer is to make the relationship strictly **one-directional** —
`src_column` is derived output, the allow-list is authored input — and to assert that
in the loader rather than trusting it.

**Evidence that would change my mind:** if `private/layouts/layouts.json` *already*
carries a per-column map, then `src_column` should be generated from it and this
objection dissolves. I could not check — §5 forbids opening `private/`. **This is a
question for the COS, not for me**, and it should be answered before D-4 is ratified
(R18).

---

## 6. The single change that would most improve this blueprint

**Make range completeness a P1 gate, and re-measure the audit at full extent (R1 + R2).**

Concretely: the artifact records requested range, effective range, and the tab's
`rowCount`/`columnCount` from `metadata()`; P1 refuses when the artifact does not cover
the used extent; and `run_sweep.py` is re-run at full extent with every count in
AUDIT.md restated against its window.

Why this over the (architecturally larger) R4: house doctrine is *inversion — avoid ruin
first*. R4 changes where a field lives; a wrong answer there costs a re-migration, which
the shadow store and rollback are specifically designed to absorb. A truncated artifact
**silently ingests a fraction of the data while passing every gate this blueprint
proposes** — E4's assertions all sit near the top of the tab, P1's parity compares what
was captured against what was captured, and P4's reconciliation is scoped by counts that
are themselves truncated lower bounds. It is the only finding here that defeats the
verification plan rather than merely being unverified by it. It is also the cheapest fix
in this document: one assertion against a value `metadata()` already returns.

It has already happened once. Spec #1 — `stats:net-worth-data`, the tab the blueprint's
own problem statement leads with — was measured on a window that ran out at row 80, with
five populated cells in the boundary row.

**Runner-up, and the change that most improves the *design* rather than its safety:**
R4 — move derivation to column grain on the already-declared, never-populated
`src_column`. It removes D-1's table rebuild, reaches all nine inadequate specs instead
of one, and gives P4 a table to reconcile against.

---

*Boundaries: nothing under `private/` was opened. No financial values appear above —
cell counts, row/column extents, column letters and formula shapes only, sourced from
committed method files and the structure-only audit. Read-only apart from this file.*
