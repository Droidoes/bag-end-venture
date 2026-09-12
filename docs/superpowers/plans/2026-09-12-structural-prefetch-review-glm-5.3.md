# Panel review — structural pre-fetch artifact blueprint

**Reviewer:** glm-5.3 (external pro review, separate session, owner-convened)
**Date:** 2026-09-12 · **Version reviewed:** the **v0.2 + v0.2.1 pair** (v0.2 is the
design; v0.2.1 the E1–E8 amendment; together they are the current design). No
higher-numbered blueprint existed in this directory at review time.
**Evidence base:** the blueprint pair; v0.1 (context only); the panel-review
prompt; `.scratch/csv_audit/AUDIT.md`; `tools/bagend/loader21.py`;
`tools/bagend/sheets.py`; `tools/bagend.py`; `tools/schema/books.sql`;
`tools/manifests/layouts.schema.md`; `tools/PANEL.md`; `docs/TASKS.md`;
`docs/CODEBASE_OVERVIEW.md`.
**Boundaries honored:** nothing under `private/` was opened (curation specs and
layouts data could not be consulted — noted where it matters); the round-1 leg
reports (`.scratch/csv_audit/review/leg-*.md`) were deliberately **not** read;
no financial values appear below; this is the only file written.
**Disclosure:** v0.2.1 folds in a `glm-5.3-flash` round-1 leg (E2 is credited to
it). I am the same model family at pro tier and did not read that leg — where my
findings overlap it, that is convergence, not independence. This seat cannot
claim family-level independence from round 1.

---

## 1. Verdict

The pair is the right architecture carrying a wrong-scoped keystone. The
structural artifact, the origin×presence split, merge-resolution-before-blank-
logic, the provenance cross-check, override≠disagreement, and
quarantine-not-outage are all correct answers to round 1, and E1–E8 land their
findings cleanly. But the design **fails its own first objective as written**:
the presence function is given a schema home only in `fact_state`, while six of
the nine snapshot specs — all five holdings tabs plus `ss_earning:official-data`,
with `payment-estimates` partially covered — write to tables that have **no
`presence` or `origin` column at all** (`holding_state`, `ss_earnings_annual`,
`ss_benefit_estimates`). After full migration, a live `GOOGLEFINANCE` market
value still enters the store indistinguishable from a typed measurement, which
is precisely the audit's headline defect. To that add one phase-order
contradiction (promotion precedes the owner-reviewed reconciliation it is
supposed to gate) and three mechanisms that are asserted but not specified
(copy enforcement, quarantine visibility, per-tab staleness). Recommendation:
**revise to v0.3 before ratification.** One blocker, five majors, eight minors,
three nits — the rest is refinement of a fundamentally sound design.

---

## 2. Findings

| # | Severity | § | Finding | What I would change |
|---|---|---|---|---|
| 1 | **BLOCKER** | v0.2 §D2, v0.2.1 §E2 | **The presence function has no destination in most of the tables the 9 specs write.** D2 extends `fact_state` only and calls it "the only place v0.2 touches the store's shape." But the loader maps: holdings ×5 → `holding_state` (no presence/origin — `books.sql:609–625`, `loader21.py:1014–1019`); `ss_earning:official-data` → `ss_earnings_annual` (none — `books.sql:267–284`, `loader21.py:512–543`); `payment-estimates` → `ss_benefit_estimates` (only `is_estimate`, hardcoded by year at `loader21.py:572`, not derivation-driven). v0.1 §8 itself promises "holdings … live-quote columns become `estimated`" — a table that cannot express it. `loader21.py:1002–1003` already stores a loader-side derivation (`mv = shares*price`) with no marker. [`pnl_records:cost-basis`'s target table is not verifiable without `private/` — likely `fact_state`.] | D2 must enumerate every fact family the 9 specs write and extend each (nullable `origin`/`derivation_kind` plus `presence` or equivalent), **or** explicitly descope those specs with the owner's eyes open. The "minimum schema change" claim must be re-derived either way. |
| 2 | **MAJOR** | v0.2 §D5 | **P3 promotes before P4's owner review.** P3's gate: "Comparison passes → **atomic promotion**." P4's gate: "Owner-reviewed table **before promotion**" — yet P4 is the later phase. v0.1's own P4 gate said "no unreviewed `estimated`" before any store load, and AUDIT.md: "Still required before the next load: per-column derived-vs-measured reconciliation." As ordered, unreviewed `estimated` rows go live. | Make the P4 reconciliation table a precondition *inside* P3's gate (review, then swap), or renumber the phases. E8 fixed the arithmetic, not the order. |
| 3 | **MAJOR** | v0.2 §D1 | **The copy rule is asserted, not enforceable.** "The loader records its source cell" — no column or table is designated to hold it (D2 adds none), so "no aggregation may sum a `copy` together with its source" is invisible to `v_state_current`/`v_net_worth` and T13 is untestable at store level. Worse, the rule covers only **same-tab** pure refs (`=O`): a cross-tab pure ref is classified `external` and gets **no** copy protection — yet the same number in two tabs is this corpus's default double-count vector (layouts.schema.md's own warning). | Name the enforcement point: a load-time mapping check refusing/quarantining a spec that maps a copy column and its source to overlapping `(account, metric)`; add a `copy_of` cell-ref column if the linkage must be auditable later; extend copy semantics to cross-tab pure refs (treat as declared duplicates). |
| 4 | **MAJOR** | v0.2 §D1, v0.2.1 §E3 | **Totality gap: the formula that evaluates to empty.** `=IF(cond,"",value)` is a real state in financial sheets. The cell is emitted (it has a `formulaValue`) but carries no value — whether the API returns `stringValue:""` or omits `effectiveValue`. It is not `zero_from_blank` (that ratification is for genuinely blank cells, and E3's shadow rule doesn't apply), it cannot be stored as `estimated` (the CHECK demands exactly one of value_num/value_text), and today it is **silently dropped** (`coerce_num("")→None`) — indistinguishable from absence. Also: a merge shadow whose **anchor is itself blank** contradicts "never read as blank"; ARRAYFORMULA spill cells (value with no formula of their own) are unnamed [unsure whether they occur in this corpus]. | Add the row to the D1 table. My recommendation: `origin='derived'`, and either the owner ratifies formula-blank-as-zero (→ `zero_from_blank`) or the cell is "not ingested, reason logged" with the reason visible in the load report — never a silent drop. Resolve the empty-anchor case explicitly; state a spill policy. |
| 5 | **MAJOR** | v0.2 §D3 | **Quarantine is invisible downstream.** A quarantined spec does not block the batch — but nothing marks the gap *in the store*. `v_net_worth` sums whatever loaded; a quarantined holdings or net-worth tab silently shrinks totals while looking complete. That trades an outage for silent partial data, the exact failure mode PANEL.md §6 ("fail loudly") exists to prevent. `coverage_calendar` was built for precisely this. | Quarantine must write `coverage_calendar` rows (status `not-loaded`, note naming the rule that fired) and set `load_batch.status='partial'`; add a test that a quarantined spec leaves a store-visible trace. |
| 6 | **MAJOR** | v0.2.1 §E7 | **Per-tab staleness is unimplementable as written.** `drive_modified` is the only timestamp the API gives and it is **file-wide**; it cannot be "restricted to tabs the spec actually reads." Related: today's dump path records `modifiedTime: ""` in provenance (`bagend.py:144–146`) — the guard's input is not even captured. | Either accept file-wide granularity (on any `drive_modified` change at pre-fetch, re-fetch the tabs the specs need — over-read, correct, cheap since pre-fetch is online anyway), or record a **per-tab content fingerprint** in the artifact and compare that. Name the provenance capture fix as P1 work. |
| 7 | MINOR | v0.2 §D5 | **Atomicity conditions unstated.** A single-file rename swap is atomic on POSIX only with no open connections and no WAL sidecars. The repo does not set WAL today (default rollback journal), so this is specification completeness, not a live bug — but "is the promotion genuinely atomic" is exactly what the owner is being asked to trust. | Write the preconditions into the gate: close all connections; checkpoint or refuse under WAL; swap journal files if hot. Add a **rehearsal test**: promote → load → roll back → verify parity. Without a rehearsal, "rollback" is a hope, not a capability. |
| 8 | MINOR | v0.2.1 §E4 | **E4's label assertions depend on unratified D-4.** "Expected label at each declared header cell matches the allow-list" requires per-column fields that `layouts.schema.md` does not have and that exist only as a pending owner decision. The "shape" vocabulary (blank band, total row, label-only row) is also undefined. | Mark the dependency and phase E4: row-shape and merge assertions now; label assertions after D-4 ratification **and** after the per-column entries are authored — an uncosted backlog of dozens of entries across 9 specs that should appear in the plan. |
| 9 | MINOR | v0.2.1 §E5(b), D-4 | **Three overlapping per-column vocabularies.** layouts already carries `derived_columns`, `external_links`, `key_column`; E5(b) adds per-column `role`. A tab could declare `derived_columns:["E"]` and `columns.E.role:"value"` with no precedence rule. Putting `metric_id` in the allow-list also duplicates the curation-spec → `src_column` binding (books.sql:100–110 exists for exactly this), creating a second authority for the same mapping — the drift this design set out to kill. D3's "fields the allow-list marks non-overridable" is itself undeclared schema. | Let `role` **subsume** (and deprecate, or be derived from) the two old fields; keep metric binding in curation + `src_column`; update `layouts.schema.md` in the same blueprint, including the non-overridable mechanism. |
| 10 | MINOR | v0.2 §D1 | **`origin='key'` is loader-internal vocabulary in a store CHECK.** Key cells feed `as_of`/`natural_key` construction; no `fact_state` row's *value* originates as a key. As specified, the CHECK admits a value that should never be written, and nothing asserts which `(origin, presence)` pairs are legal on stored rows. | Drop `key` from the stored CHECK (keep it in the cell classifier), or define when a stored row may carry it; extend T8 with the stored-row legality invariant. |
| 11 | MINOR | v0.2 §D1 | **Provenance inversion: `GOOGLEFINANCE`=derived, `IMPORTRANGE`=external.** A live market quote is the most externally-sourced fact in the book (the audit's own words: "live external quote formulas") yet reads as internally derived; a cross-tab pull — a *copy* of data that exists elsewhere in the corpus — reads as `external`. | Either a doc note defending the split, or a fifth origin for live quotes. At minimum, ensure quote columns are declared in `external_links` so the override precedence catches them; undeclared quote columns default to `derived` and understate provenance. |
| 12 | MINOR | v0.2.1 §E2 | **`derivation_kind` values are not mutually exclusive.** `SUM` over derived cells is both `aggregate` and `chain`. `chain` requires resolving intra-tab cell dependencies — a real algorithm (topological pass, cycle handling) the blueprint does not acknowledge. `external`-origin cells carry no kind at all, though `GOOGLEFINANCE` (a projection) sits under `derived` and does. | Give a precedence rule (e.g., `chain` only when the formula is otherwise `deterministic`), or split into kind + a derived-from-derived flag/depth; decide whether `external` carries kinds; acknowledge the dependency-graph cost. |
| 13 | MINOR | v0.2 §D6 | **Stale and missing tests.** T2 ("exactly the formula-cell count as `estimated`", 539 at audit time) is wrong under the new ontology — the 539 now split across `copy`/`constant_formula`/`derived`/`external`, so the estimated count is no longer the formula count. No tests are named for E4, E6, E7, D3's refusal/override/quarantine behavior, the promotion+rollback rehearsal, or the snapshot's `--structure-only` redaction (grid_structure already redacts — `sheets.py:232` — but the new snapshot writer needs the same gate tested). | Re-derive T2 from the artifact's classification (formula cells → k/c/d/e breakdown; estimated = d+e); add one named test per new mechanism. Every E-fix should carry a test. |
| 14 | MINOR | v0.2.1 §E8 | **The duplicate-file cleanup is unscheduled.** E8 says the `stats__Net-Worth Data` / `stats__Net_Worth_Data` duplicate "needs a named store-level dedupe/rebuild step, not just a file deletion" — but no phase in D5 carries it. Until it lands, E6's provenance cross-check hits a two-rows-one-identity ambiguity. | Schedule the dedupe/rebuild in P1 or early P3, before structural loads begin. |
| 15 | NIT | v0.2 §D2 | **"Exactly as v0.2.4 was handled" mischaracterizes the precedent.** v0.2.4 was the *sanctioned ALTER exception* (additive columns, sqlite_master parity); a CHECK change is a 12-step table rebuild needing different parity (row-count and content preservation). books.sql's application rules say fresh-store-only — the migration script needs its own sanctioned-exception entry. | Say which operation, and define its parity: preserved row counts + content + new-schema match. |
| 16 | NIT | v0.2 §D3 | **Role vocabulary drift.** `layouts.schema.md`'s shape block omits `worksheet` (its own roles table and `src_tab`'s CHECK include it); D3's orphan-acknowledgment list `{derived, scratch, worksheet, duplicate}` omits `deferred`. | Align the schema doc and the list. |
| 17 | NIT | v0.1 §4 | **Snapshot range sizing unstated.** `grid_structure` defaults (60 rows × 30 cols) would truncate wider tabs; the snapshot command must size its range from `metadata()` (rowCount/columnCount). | One sentence in the artifact schema section. |

### 2.1 Independence map

- **Reached independently from the artifacts and code:** findings 1–8, 10–17.
  None of them appear in the prompt's Appendix (§7a/§7b) in the form stated —
  they are about v0.2/v0.2.1's *own answers*, which is where this round was
  asked to look.
- **Agree with the Appendix:** all of §7a's round-1↔fix pairings are fair
  characterizations; §7b's known-gaps list is accurate (I did not report those
  as novel). Two refinements, see §5.
- **Contradict:** nothing in the Appendix outright. One internal contradiction
  *within* a §7a fix (merge-shadow vs blank anchor, finding 4) and one
  arithmetic note: the audit's own headline "9 of 11 / inadequate 9" disagrees
  with its verdict table (8 INADEQUATE + 1 MARGINAL); E8 reconciles the
  *blueprint* to 8+1, but AUDIT.md retains the inconsistency — cosmetic, worth
  a one-line correction so future readers don't re-derive it.

---

## 3. The five open questions

**1. Is the presence function total? Which state is unmapped? Is the copy rule
enforceable? Is `external_links` overriding `kind` right?**
Not total. The unmapped state is the **formula evaluating to empty** (finding 4)
— common in guarded financial sheets, silently dropped today. Secondary gaps:
blank-anchored merge shadows, ARRAYFORMULA spills [unsure]. The copy rule is
*not* enforceable as specified — no schema home for the source-cell record, no
queryable linkage, and cross-tab pure refs (the likelier double-count vector)
are classified `external` and escape it entirely (finding 3). The
`external_links`-over-`kind` precedence is the **right call** — it is the only
mechanism that keeps a paste-valued external column (Taxes `E`/`H`) from
reading `measured` in one row and `estimated` in the next — but it should be
documented as overriding `copy` and `constant_formula` too, and the cross-tab
copy hazard needs an explicit rule.

**2. Is the schema extension the minimum? Is `origin` the right dimension?**
`origin` on fact **rows** is the right placement — per-column layout evidence
cannot express the mixed-origin columns this corpus actually has (net-worth's
interleaved A/H formula pattern; Taxes E/H literal-valued externals). But it is
**not the minimum and not the right scope** as written: the extension reaches
only `fact_state` while six of nine specs write elsewhere (finding 1), and the
copy rule's source-cell record is missing (finding 3). `zero_from_blank` as a
presence *value* is right — stewardship honesty requires the distinction, and
`v_net_worth` treating it as a contributing zero is the ratified semantics.
`derivation_kind` is defensible but needs the precedence fix (finding 12).

**3. Do the repaired join and refusal rules close the holes without opening new
ones? Can the non-overridable list be gamed? Is quarantine safe?**
The narrowing is right, and the entry-missing (refuse) vs field-missing
(override allowed, per E5(a)) distinction is coherent with
`layouts.schema.md`'s "unresolved" convention. Gaming: the non-overridable
*mark* is new undeclared schema (finding 9), and the real vector is not the
list but **extent-defining fields** — an override of `first_data_row` or
`skip_rows` silently re-points more data than a `key_column` override ever
could. Wire overrides **through E4**: an override of an extent field must pass
the shape assertions before it applies. Add an override-debt rule (an override
must be ratified back into the allow-list within N loads, or the load refuses).
Quarantine is safe **only** with a store-visible trace (finding 5); as written
it converts outages into silent partial loads.

**4. Is promotion genuinely atomic, is the rollback real, is the phase order
safe?**
Order: **no** — P3 promotes before P4's owner review (finding 2). Atomicity:
conditional — a file swap is atomic given no open connections and no WAL
sidecars; the preconditions are unstated (finding 7). Rollback: the kept
pre-promotion file makes it *possible*, but without a rehearsed
promote→load→rollback drill it is unproven (finding 7). The P1
parity-against-source with intended-fix/bug/unknown classification is the
strongest part of D5 — with one addition: the snapshot writer now **owns date
typing** (serial + numberFormat) that the CSV path did via `_typed`; that
conversion rule must be specified or every date divergence will be
misclassified (see §5b).

**5. What does verification still not cover?**
Quarantine visibility (finding 5); the promotion/rollback rehearsal (finding 7);
E4/E6/E7 mechanics (findings 6, 8); D3's refusal/override behavior; T2's
re-derivation under the new ontology (finding 13); the stored-row
`(origin, presence)` legality invariant (finding 10); snapshot range coverage
(finding 17). The listed T8–T13 are good tests for what they name — the gap is
that the newer mechanisms (E4–E7, D3's behavior space, promotion) have no tests
at all.

---

## 4. Decisions requested (D-1 … D-4)

**D-1 — Schema extension. Recommend: extend `presence`/`origin`/
`derivation_kind` to every fact family the 9 specs write** — `fact_state`,
`holding_state`, `ss_earnings_annual`, `ss_benefit_estimates` (and
`position_lot` only if the P4 table shows pnl-records lands there). Nullable
columns with narrow CHECKs; one versioned rebuild. Row-level placement stands
(finding 1's evidence). *Strongest argument against:* it triples the rebuild
surface and touches `holding_state` — a hot table the owner already queries —
for a distinction nothing consumes yet; a layout-evidence-only home would be
cheaper. *Evidence that would change my mind:* a P4 reconciliation showing the
holdings/SS derived columns are excluded from mapping anyway — then the smaller
scope suffices, because those columns simply never load.

**D-2 — `fi_balances:over-time`. Recommend (a): keep it CSV-only and honour
`header_row` on the CSV path.** The accuracy cost is **zero for structure**: a
Drive CSV has no formulas or merges to lose; its fetch path (`files.get
alt=media`, written as-is — `bagend.py:185–189`) never passes through
`sheets._typed`, so it inherits no #19(c) risk; and drive-file provenance
already captures a real `modifiedTime`, so a staleness guard is available.
Residual costs: the dual ingest path persists (Task #18 rule (A) removes the
`csv_skip`/`header_row` state duplication) and the file gains no structural
future-proofing. Option (b) spends owner effort modifying his own Drive for no
recoverable structure. *Strongest argument against (a):* the CSV path is a
second ingest code path to maintain forever for exactly one spec. *Evidence
that would change my mind:* the file being a lossy export of a Sheet that still
exists with merges/formulas that matter — then (b) recovers real structure.

**D-3 — Cell notes/comments. Recommend: add `--with-notes`, with two
conditions.** `note` is a CellData field on the same `spreadsheets.get
includeGridData` call — one fields-mask token, no second endpoint, modest size
cost. The privacy class is unchanged in kind (the artifact already carries
values; `private/` is gitignored). Conditions: (1) `--structure-only` must
**omit or redact notes** — free text can carry figures, and the delegate-facing
redaction gate must cover it exactly as `_redact_formula` covers constant
formulas; (2) notes are **evidence, not structure** — the loader must never
parse them; surface them in P4's reconciliation and the layout evidence.
*Strongest argument against:* artifact bloat plus storing free text we must
then govern, on the strength of an anecdote about one tab. *Evidence that would
change my mind:* a fields-mask test showing response-limit blowups on the
largest tabs, or the notes proving formula-free.

**D-4 — Per-column fields in `layouts.schema.md`. Recommend: add per-column
`expected_label` and `role`; do **not** add `metric_id` there.** `role` must
subsume (and deprecate, or be derived from) `derived_columns`,
`external_links` and `key_column` — three overlapping vocabularies is how the
next correlated-error incident happens (finding 9). Metric binding stays where
it already lives: curation specs → `src_column` (books.sql:100–110). While
touching the schema doc, declare the non-overridable-field mechanism D3
already relies on. The loader refusing a letter with no allow-list column is
right. Budget the backfill: per-column entries for 9 specs is real authoring
work and belongs in the plan (finding 8). *Strongest argument against:* two
files must change when a column is added; `metric_id` in the allow-list would
make it self-contained for joins. *Evidence that would change my mind:* a
decision to make the allow-list the single mapping authority — a larger
redesign than this blueprint claims to be, and worth doing openly if at all.

---

## 5. Disagreements with the Appendix (§8)

No outright contradictions. Two refinements and one amplification:

- **(a) §7a, merge-shadows row:** "shadow inherits the anchor, never blank" is
  the right fix but is internally contradictory when the **anchor itself is
  blank** (an empty merged range) — the shadow would inherit a blank while the
  rule forbids reading it as blank (finding 4). One sentence resolves it; it
  should be in E3.
- **(b) §7a, parity row:** parity-against-the-source is the right call, but the
  answer is incomplete — the artifact writer inherits responsibility for
  **date typing** (serial + `numberFormat`), which the CSV path performed via
  the (buggy) `_typed` heuristic. Without a specified conversion rule, every
  date divergence lands in the "unknown" bucket and the gate evidence becomes
  noise.
- **(c) §7b, doc-drift bullet:** the drift is broader than stated —
  `docs/CODEBASE_OVERVIEW.md` invariant #1 hard-codes "`sheets dump` → typed
  CSV" as *the* native read, not just AGENTS.md and the two skills. The pending
  charter amendment should sweep all of them in one pass.

---

## 6. The single change that would most improve the blueprint

**Scope the schema extension to every fact family the nine snapshot specs
actually write (finding 1).** Everything else in this review is refinement;
this one decides whether the design achieves its own stated objective. As
written, the artifact faithfully records that a market value is a live quote —
and then the store drops that fact on the floor for six of the nine specs it
was built for. Fix the destination, and the rest of the design (presence
function, P4 reconciliation, verification) has something to be right *about*.
