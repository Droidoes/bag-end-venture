# Blueprint v0.2.1 (addendum to v0.2) — third review leg folded in

**Date:** 2026-09-12 · **Author:** Roth (COS) · **Status:** DRAFT — awaiting owner ratify
**Reviews folded in:** `gpt-5.6-luna`, `qwen3.8-flash`, `glm-5.3-flash` — all three at
`.scratch/csv_audit/review/leg-*.md`
**Read with:** `2026-09-12-structural-prefetch-v0.2.md` (the design) — this file is
only the delta from it. If a higher-numbered version exists, review that one.

---

## 0. Convergence — three independent legs, graded

All three judged **v0.1 fails as written**. None defended it.

| Finding | Grade | Fix here |
|---|---|---|
| The ratified blank rule (`zero_from_blank`) is unrepresentable; "no schema change" false | **n/n** | v0.2 §D2 |
| `formula → estimated` collapses distinct semantics; a presence *ontology* is needed | **n/n** | v0.2 §D1 + **E2** |
| Merge-covered cells are indistinguishable from blanks; blank→0 would zero merged spans | **n/n** | v0.2 §D1 + **E3** |
| §7 override ≠ disagreement (self-deadlock); blanket refusal blocks legal gap-filling | **n/n** | v0.2 §D3 + **E5** |
| P1's "diff against the CSV" canonizes the `_typed` serial→date bug (#19(c)) | **n/n** | v0.2 §D5 |
| Error cells unrepresentable in the artifact → `presence='error'` unreachable | **n/n** | **E1** |
| `(alias, tab)` insufficient identity; patterns and provenance not carried | **n/n** | v0.2 §D3 + **E6** |
| No load-time shape assertions; one inserted row silently drops or re-points data | **2/3** | **E4** |
| T6's staleness guard needs live Drive; `drive_modified` is file-wide | **2/3** | v0.2 §D6 + **E7** |
| Decision 2 not moot (`fi_balances` stays CSV) | **2/3** | v0.2 §D4 |
| Coordinate systems mixed with no audit gate | **2/3** | v0.2 §D7 |
| P3/P4 arithmetic inconsistent (9 vs 10 snapshot specs); P4 omits the marginal spec | **1/n** | **E8** |
| `layouts.schema.md` defines no per-column fields for the letter-join | **1/n** | **E5b** |
| Provenance not cross-checked in the target flow ("filename is never identity") | **1/n** | **E6** |

`n/n` = load-bearing, must resolve. `(n−1)/n` = strong consensus. `1/n` = unique
catch, surfaced anyway.

## E1 — Error cells in the artifact

The v0.1/v0.2 artifact schema carries no error representation, so `presence='error'`
was unreachable. Add `error_type` to a cell record (from `effectiveValue.errorValue`)
and map `error_type != null → presence='error'`, `origin='derived'`. Error cells are
**never** silently ingested as values.

## E2 — `derivation_kind` (glm's "single change", adopted)

`presence='estimated'` currently carries four meanings. Add `derivation_kind` for
`origin='derived'`: `deterministic` (e.g. `=D3+1`) · `aggregate` (SUM over a span) ·
`projection` (LOOKUP/GOOGLEFINANCE) · `chain` (depends on another derived cell).
This makes transitive derivation visible instead of hidden, and gives P4 a real
contract to reconcile against.

## E3 — Merge resolution happens *before* blank logic

Order is now explicit: resolve merges first, then classify blanks.
1. A cell inside a merge range that is **not** the anchor is a **shadow**: it is
   **not blank** and must never be zeroed. It inherits the anchor's origin/presence.
2. Only a genuinely empty, in-range, non-shadow cell inside a live row is
   `zero_from_blank`.
3. **Vertical data merges** (the NEAR-class tabs, 7 per Task #3) are flagged
   series-unsafe and excluded from time-series ingestion unless the allow-list
   says otherwise.

## E4 — Load-time shape assertions

The artifact supports cheap validation that v0.2 never used. Before ingesting a
spec, assert:
- the **expected label** at each declared header cell (`header_row`/`group_row`/
  `sub_header_row`) matches the allow-list;
- `skip_rows` and `first_data_row` land on rows whose **shape** matches what was
  ratified (blank band, total row, label-only row);
- declared merges are present.

Any mismatch → **quarantine the spec and report**, never silently load a shifted
frame. This is the safeguard that catches an inserted row or column.

## E5 — Per-column fields, and gap-filling overrides

**(a)** §D3's refusal list now explicitly permits an override where the allow-list
entry **lacks the field or holds `unresolved`** — the ratified 1(c) hatch must be
exercisable, which v0.1 forbade outright.

**(b)** For letter-based addressing to resolve, the allow-list schema needs
per-column fields. `layouts.schema.md` has none. Add, per column:
`metric_id`, `expected_label`, `role` (value/key/derived/external). The loader
refuses a letter that has no allow-list column.

## E6 — Provenance in the target flow

The loader must cross-check the artifact's embedded `alias` / `tab` / `drive_id`
against `private/raw/_provenance.tsv` and **refuse on mismatch**. The charter's
"a filename is never trusted as identity" rule currently dies at the hand-off from
extraction to load; the structural artifact makes it enforceable.

## E7 — Staleness scope

`drive_modified` is **file-wide**, so any unrelated tab's edit would refuse a
legitimate load. Restrict the staleness check to tabs the spec actually reads, and
keep the check in the **pre-fetch** step so load stays offline (v0.2 §D6).

## E8 — Arithmetic corrected

11 specs − 1 retired (`ss_earning:cola`) − 1 unchanged (`fi_balances`, Drive CSV)
= **9 snapshot specs**, not 10. P4's reconciliation covers **10** rows: the 8
inadequate, the 1 marginal (`payment-estimates`, which has a mapped derived
column), plus the duplicate-file cleanup — and the `stats__Net-Worth Data` /
`stats__Net_Worth_Data` duplicate needs a named store-level dedupe/rebuild step,
not just a file deletion.

## Open for the owner (unchanged from v0.2, plus one)

1. **Ratify the schema extension** — now `presence` (+`zero_from_blank`) and
   **two** new columns (`origin`, `derivation_kind`) in a versioned rebuild.
2. **`fi_balances`** — CSV rule (A), or re-create as a Sheet?
3. **Cell notes/comments** — add `--with-notes`?
4. **New:** ratify the **per-column fields** (`metric_id`, `expected_label`,
   `role`) into `layouts.schema.md` — without them the letter-join has nothing to
   resolve against.
