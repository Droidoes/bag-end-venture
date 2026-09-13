# layouts.json — format spec (this file is method; the data file is not)

**Why the data file lives outside `tools/`:** `tools/` means *tooling only*. A
layout entry names your tabs, columns, plans and account structure — that is
personal data, so the populated file lives at **`private/layouts/layouts.json`**
(gitignored). This spec is the committed half. Owner ruling, 2026-09-06, after a
brokerage account number was found inside a `tools/` file — see §Hygiene below.

## Shape

```jsonc
{
  "sources": {
    "<alias>": {                       // alias, never a filename (see aliases)
      "source_kind": "native-google-sheet | drive-file",
      "role": "raw | duplicate | deferred",     // source-level override
      "rule": "…",                              // e.g. year partition comes from tab name
      "data_defect": "…",                       // known defects in this source
      "tabs": {
        "<tab title or pattern like '<year>'>": {
          "role": "raw | derived | scratch | reference | documentation | duplicate",
          "header_row": 1 | 2,
          "group_row": 1,                        // optional: group/banner tier ABOVE header_row
          "sub_header_row": 3,                   // optional: second label tier BELOW header_row
          "key_column": "A",                     // optional: row-key column when it carries no label
          "first_data_row": 6,                   // optional: when data starts below the header block
          "header_totals": {"C2": "=SUM(C5:C187)"}, // optional: totals sitting INSIDE header cells
          "skip_rows": [3, 4, 5],                // optional: non-record rows (grand totals, spacers)
          "derived_columns": ["E", "J"],         // optional: formula columns — never summed with inputs
          "external_links": { "K": "Buybacks" }, // optional: cells whose values come from another tab
          "grain": "one row per …",
          "dedupe": "disjoint | natural_key_prefer_latest",
          "columns": {                        // per-column shape declarations (§E5b):
            "A": { "expected_label": "Date",  //   letter -> what it IS, never a metric
                   "role": "value" } },       //   value|key|derived|external|copy|scratch
          "warning": "…", "must": "…", "note": "…", "needs": "…"
        }
      }
    }
  },
  "_cross_cutting": { "…": "…" }
}
```

### Fields added 2026-09-10 (native structure read)

`group_row`, `key_column`, `first_data_row`, `skip_rows`, `derived_columns` and
`external_links` exist because `sheets dump` (values only) cannot show a merged
group band or a derived column. The first two-tier tab resolved after the
structure read (`stats / Inv Income`) had **unlabelled subtotals sitting outside
every merge** and a grand-total row directly under the header — neither is
expressible with `header_row` alone. The fields are optional and only meaningful
where the tab really has that shape; unresolved entries keep
`header_row: "unresolved"` until a human confirms.

### Fields added 2026-09-12 — per-column shape declarations (`columns`, v0.3 §E5b)

Every other per-column field on this list says what a column MEANS to the store. This
one says what the column **IS** in the sheet — and it exists because §E4's load-time
shape assertion ("the expected label at each declared header cell matches the
allow-list") was **vacuous**: nothing declared any per-column expectation, so the
assertion had nothing to fail against. A renamed header, a column inserted into a
mapped tab, or a duplicate label reaching for a mapped metric would have loaded the
wrong figures into the wrong metrics silently — proved on the real first-wave artifact
before this field existed (a shifted frame loaded with `status='complete'`).

```jsonc
"tabs": {
  "<tab>": {
    "role": "raw",
    "header_row": 1,
    "columns": {
      "<LETTER>": { "expected_label": "Date",     // required: the header text this
                    "role": "key",                //   LETTER must carry at header_row
                    "note": "why / the evidence"  // optional, as everywhere here
      }
    }
  }
}
```

**Rules (v0.3 §E4 + §E5b — implement, do not re-derive):**

- **The join key is the LETTER.** The label is what gets ASSERTED, never what gets
  joined on: a label that has MOVED is exactly the defect only a position pin can
  see. Keying the map by label would have made `expected_label` a tautology.
- **`expected_label`** is the header text the column must carry at
  `{letter}{header_row}`, compared with the same whitespace-collapsed, case-folded
  normalisation the rest of the join uses. `null` is a real assertion — it says this
  letter must carry **NO** label (the unlabelled helper column, the spacer that must
  stay a spacer); a label appearing there is a frame change and refuses the load.
- **`role`** is the vocabulary `src_column.role` already CHECKs: `value`, `key`,
  `derived`, `external`, `copy`, `scratch`. It describes the column, not the metric.
- **NO `metric_id` here.** Metric/account binding lives in the curation spec and
  reaches `src_column` from there (v0.3 §D-4; DM-2026-01 follow-up). A declaration
  carrying `metric_id` is refused outright, so the split cannot rot back.
  Layout = what the sheet IS; spec = what the store DOES with a letter.
- **The bijection is both directions.** (i) Every column the curation spec MAPS must be
  declared — an undeclared mapped column is an unchecked column, and an unchecked
  column is not a check. (ii) Every label the artifact carries inside the returned
  bounds must be declared, mapped or not: a skipped column pinned as `derived` costs
  one line and means a column inserted ANYWHERE in the band breaks a pin. A letter
  carrying no label and no observations needs no declaration — there is nothing to
  ratify.
- **Observed character must match the declared role** (counts and kinds over the
  declared rectangle's live rows — never a value):
  | role | assertion |
  |---|---|
  | `key` | this letter IS the row-addressing column (`rect.key_col`), and no other declared column may be it. Kind is NOT asserted: a ratified spine may be a generated series (`=EOMONTH`), which is precisely why "key" is a claim about addressing, not about cells. |
  | `value` | entered measurable literals predominate (> formula-bearing cells). |
  | `derived` | formula-bearing cells predominate — **or** the derivation is STATED in curation (`mode: derive_from_delta`, like the closed-account component); the exemption exists only because the derivation is declared, and the converse is enforced too: a `derive_from_delta` mapping must be declared `derived`. |
  | `external` | cross-sheet / `IMPORT*` cells predominate — **or** the letter appears in `external_links` (a declared-external column may carry measured literals; §4 precedence). |
  | `copy` | pure-reference formulas predominate. |
  | `scratch` | never a fact source: the spec must bind no account/metric to it. No cell-kind claim (junk can be anything). |
- **Absence is not a mismatch.** A column with no observation inside the rectangle
  contradicts nothing: blanks are DM-2026-01's business (`blank_means`,
  `series_start`, `coverage_calendar`), never a shape finding. Silently refusing an
  empty column would make the loader's refusions unlearnable.
- **Refusals.** A role outside the vocabulary, a non-letter key, two keys folding to
  one letter, a missing/typed-non-string `expected_label`, an `int` map, `metric_id`
  present → **`LoadError`**: a broken allow-list is a curation bug and must stop the
  load, not quarantine a frame that was never describable. Label/character/bijection
  findings against a well-formed declaration → **`Quarantine`** (`column-undeclared`,
  `column-label-mismatch`, `column-role-mismatch`), which follows §7's existing
  visible path: `coverage_calendar` `not-loaded` rows naming the rule, and
  `load_batch.status='partial'`. Never a silent load under a shifted frame.
- **Proof, not trust.** Each structural load prints a per-column `column shape` report
  (letters, roles, kind COUNTS — never values) so a reader can see the assertions
  RAN, the same visibility rule that made the zero report mandatory.
- **Malformed-declaration refusals and shape quarantines are different channels on
  purpose**: `LoadError` aborts, `Quarantine` stays visible in the store. Both are
  covered by `tools/tests/column_shape_tests.py`, whose negative tests (rename,
  insertion, duplicate label, role contradiction, undeclared column) are what keep
  §E4 from going vacuous again.

### Fields added 2026-09-12 — per-column blank semantics (`blank_means`, DM-2026-01)

A blank numeric cell **inside an existing live row** means **0** by default —
the loader records it with `presence='zero_from_blank'`. A column may declare
the exception on the tab entry:

```jsonc
"tabs": {
  "<tab>": {
    "role": "raw",
    "header_row": 1,
    "grain": "month-end",
    "blank_means": {
      "<header label>": { "value": "not_applicable",   // object form: value + evidence
                          "note": "why this column is the exception" },
      "<header label>": "not_applicable"               // plain form is accepted too
    }
  }
}
```

**Rules (decided in `docs/decisions/DM-2026-01-blank-semantics.md` — implement,
do not re-derive):**

- **Two values only.** `zero` — the default, may be omitted entirely — and
  `not_applicable`. There is **no cell-level `not_recorded`**: that concept's
  home is `coverage_calendar` (`expected` + `absent-in-source` / `loaded-empty`
  / `not-loaded`).
- **Cell-level, nothing more.** It answers one question — what does a blank
  cell inside an existing live row mean? `zero` → the blank is a stated 0;
  `not_applicable` → the cell has no meaningful value at that row and **no row
  is written**. Absent rows and absent periods are NOT this field's business —
  `coverage_calendar` owns them, and they are never zeroed.
- **Declared, never inferred.** Each declaration carries its evidence in the
  entry's `note` (typically: the metric's period grain is coarser than the
  tab's row grain, evidenced from already-declared fields — curation
  `grain`, `dim_metric.methodology`, stored `period_grain` vs `src_tab.grain`).
  Deriving the exception from grain fields was proposed and rejected.
- **Block-scoped.** The map hangs off the tab entry because a column hangs off
  `src_column.tab_id`. A tab MAY be registered as multiple blocks —
  `src_tab.block` (`''` = whole tab; `UNIQUE (source_id, tab, block)`) already
  exists in the store schema for exactly this and is currently **dormant**;
  when blocks activate, each block's spec resolves the declarations against its
  own header labels. Documented here for completeness; no behaviour change
  today.
- **Loader behaviour.** `zero` behaves exactly as before;
  `not_applicable` writes no row for that cell. At load the loader prints a
  **per-column zero report** (column → n zeros materialised) so an undeclared
  `not_applicable` column is visible in the report instead of being discovered
  by hand.
- **The anchored-gap guard.** A `not_applicable` column that ALSO declares
  `series_anchor_month` (next section) is **armed**: if an anchor period is
  *expected* (`coverage_calendar.expected = 1`) and its cell is blank, that is
  a **missing observation**: the loader reports it by column and period and
  the load exits non-zero — it is never silently skipped as N/A. The only
  silence is a period deliberately declared `expected = 0` in
  `coverage_calendar`, which is itself a visible declaration. (Arming is
  declaration-driven — see `series_anchor_month` — never inferred from the
  metric's grain.)
- **Refusals.** A value outside the two, a declaration naming no column the
  spec resolves, or `blank_means` on a family whose rows carry row-grain
  presence across several value columns (`ssa_earnings`) all fail the load
  loudly. A formula that copies a blank cell is a formula observation, not a
  blank; only artifact blanks (and spills of blanks) carry the column's
  `blank_means`.

### Fields added 2026-09-12 — per-column series start (`series_start`)

A column's series may not begin with the tab. The same tab entry may DECLARE
where it begins, per column:

```jsonc
"tabs": {
  "<tab>": {
    "role": "raw", "header_row": 1, "grain": "month-end",
    "series_start": {
      "<header label>": { "value": "1999-12",           // object form: value + evidence
                          "note": "why the series starts here" },
      "<header label>": "1999-12"                        // plain form is accepted too
    }
  }
}
```

**Rules (DM-2026-01 owner confirmation, 2026-09-12 — implement, do not re-derive):**

- **It is a declaration, not an inference.** The value is one `YYYY-MM` month; a
  value that is not a calendar month, or a label that no column of the spec
  resolves, fails the load loudly (same refusals as `blank_means`).
- **Before the start a column contributes nothing.** A blank cell in a period
  strictly before the declared start is neither a stated `0` nor a missing
  observation: no row is written, and it is counted (report only) as a
  pre-start skip. This is the column-grain application of the already-ratified
  precedent for the Tax Rates rows 4–8 — *the layout declares where the series
  begins*.
- **The anchored-blank guard does not expect an anchor before the start.**
  `coverage_calendar` keeps declaring the tab's expected periods (unchanged, and
  still per tab, never per column); `series_start` is the per-column floor the
  guard reads. At or after the start the guard is unchanged: a blank December
  anchor still fails the load loudly with a non-zero exit. The only silence is a
  period the declaration puts before the start — visibly.
- **Why not a per-column coverage table.** The tab's period coverage and a
  column's series span are different grains; the memo's own boundary keeps
  `coverage_calendar` at the tab/period grain. A start declared on the column is
  the smallest honest statement, and it needs no schema change.
- **Loader behaviour.** The per-column zero report prints `series_start` and
  `pre_start_skips` per column, and the shape detector (below) prints a
  report-only line for any column whose populated rows all fall in one calendar
  month.

### Fields added 2026-09-12 — per-column anchor month (`series_anchor_month`)

A `not_applicable` column is only GUARDED if the layout says which month is
meaningful. The same tab entry may declare that month, per column:

```jsonc
"tabs": {
  "<tab>": {
    "role": "raw", "header_row": 1, "grain": "month-end",
    "series_anchor_month": {
      "<header label>": { "value": 12,                  // object form: value + evidence
                          "note": "why this month is the meaningful one" },
      "<header label>": 12                               // plain form is accepted too
    }
  }
}
```

**Rules (DM-2026-01 follow-up, COS decision 2026-09-12 — implement, do not
re-derive):**

- **The three per-column fields divide the question three ways.**
  `series_anchor_month` says *which month is meaningful* for a
  `not_applicable` series; `series_start` says *from when*; `blank_means` says
  *what a non-anchor blank is*. None of them answers another's question.
- **It arms the anchored-blank guard, and arming is column-grain.** A column
  is armed **iff** it declares `blank_means='not_applicable'` AND a
  `series_anchor_month`, and the period is **at or after** its `series_start`.
  The EXPECTATIONS the armed guard is tested against stay **tab-grain**, read
  back from `coverage_calendar.expected` — that division is deliberate, and no
  per-column expectation table exists (`coverage_calendar` is unchanged, and
  still per tab, never per column).
- **Declared, never inferred.** The value is an integer calendar month 1–12
  (plain or `{value, note}` object, evidence in the `note` — typically:
  populated points are 100% in that month, counts already published). A value
  outside 1–12, one that is not an integer, a declaration naming no column the
  spec resolves, a declaration on a column that is not `not_applicable`
  (silently inert), or the declaration on the `ssa_earnings` family all fail
  the load loudly (same refusals as `blank_means` / `series_start`).
- **Why the declaration replaced grain-inference arming.** Arming used to be
  inferred from the column mapping's grain (an annual metric on a month-end
  spine → December). That inference could not fire for a column whose mapping
  carries no grain — `Deposit (L)` on `stats / Net-Worth Data` — so a blank
  December there was silently treated as N/A and never tested against the
  expectations: **a guard that cannot fire for a column is not guarding it**
  (the same vacuity class found four times already in this work). The
  declaration is the fix.
- **Loader behaviour.** Armed findings keep flowing to the `ANCHORED BLANK`
  report line, the batch note and the CLI's non-zero exit; each finding names
  the declared anchor month.

### Fields added 2026-09-12 — series shape report (`SERIES SHAPE`)

At load the loader also prints one line per mapped column whose populated cells
all fall in a **single calendar month** (and number at least 8), naming the
column, the count, the share in that month, and whether `blank_means` is
declared:

```
SERIES SHAPE  Deposit (L): 27 populated, 100% December -> annual-in-practice; blank_means declared not_applicable
```

It reads only **which** rows are populated and their calendar month — never a
value. Its purpose is diagnostic: the counts-only zero report could not tell
`Deposit (L): zeros=301` (wrong) from a full-spine balance column
`Plan 401K (G): zeros=300` (right); the shape can. **Report only** — it never
changes what is loaded and is never a failure.

## Roles — what the ingest tool does with each

| role | behaviour |
|---|---|
| `raw` | eligible for ingestion |
| `derived` | **never ingest** — computed view of a raw tab (pivot, flat, `*-Table`, `Sheet1`); double-counting is this corpus's default failure mode |
| `scratch` | **never ingest** — junk/model/tab-parameter blocks; auto-headers on these are gibberish |
| `worksheet` | **never ingest** — a working paper (stacked tables, scratch computation); its summary tab is the source |
| `reference` | ingest into a dimension table (e.g. a category vocabulary, public lookup data) |
| `documentation` | read for methodology provenance, never tabulated |
| `duplicate` | **never ingest** — content-identical to a canonical source |
| `deferred` | recognized but parked — explicit re-open decision before any use |

## Rules the survey established (all five legs unanimous)

1. **`header_row` is authoritative, not heuristic.** Auto-detection may *propose*
   a row; it must be confirmed and recorded here. Anything unconfirmable is
   written as `"unresolved"` and the tool refuses to ingest rather than guessing.
2. **Aliases, never filenames.** Manifests and layouts reference sources by alias;
   the alias→filename/ID mapping lives in `private/`.
3. **`dedupe` is declared, not inferred.** Some sources are disjoint by year,
   others are overlapping cumulative exports of one ledger — a corpus can contain both,
   so a single global rule is wrong; `dedupe` is declared per source.
4. **`grain` varies and must be stored per row** where it can change (`period_grain`),
   never assumed from the source name.

## Hygiene — enforced by check, not memory

Layouts and manifests must contain **no** financial values, **no** account
numbers (including last-four), and **no** institution account IDs. Verify before
committing anything under `tools/`:

```bash
grep -rnoE "[0-9]{5,}" tools/ | grep -vE ":(19|20)[0-9]{2}" || echo "clean"
```

Numbers that look like years are fine; long digit runs are not. This check exists
because a 5-digit plan code and a 9-digit brokerage account number once reached `tools/`.
