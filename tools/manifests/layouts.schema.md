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
