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
- **The anchored-gap guard.** A `not_applicable` column whose metric grain is
  coarser than the tab's row grain (e.g. an annual metric on a month-end
  spine) has an **anchor period** (December). If an anchor period is *expected*
  (`coverage_calendar.expected = 1`) and its cell is blank, that is a **missing
  observation**: the loader reports it by column and period and the load exits
  non-zero — it is never silently skipped as N/A. The only silence is a period
  deliberately declared `expected = 0` in `coverage_calendar`, which is itself
  a visible declaration.
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
