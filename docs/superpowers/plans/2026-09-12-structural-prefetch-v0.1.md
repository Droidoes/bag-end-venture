# Blueprint — structural pre-fetch artifact for the loader (v0.1)

**Date:** 2026-09-12 · **Author:** Roth (COS) · **Status:** DRAFT — awaiting owner ratify
**Supersedes:** the CSV ingest path for native Google Sheets · **Absorbs:** Task #18
**Evidence:** `.scratch/csv_audit/AUDIT.md` (11/11 spec verdicts, structure-only)

---

## 1. Objective

Replace the loader's values-only CSV input with a **structural artifact**
(values + formulas + merges + formats, one file per tab), so that:

1. a **derived** cell can never enter the store indistinguishable from a
   **measured** one;
2. the layout knowledge Task #3 ratified (`group_row`, `sub_header_row`,
   `first_data_row`, `skip_rows`, `derived_columns`, `external_links`,
   `header_totals`) is actually consumed by the loader (Task #18);
3. ingest stays **offline and auth-free** — the COS pre-fetches, legs and the
   loader read local files only (charter §4).

**Non-goal:** re-fetching or re-computing values. Values are not in question; the
audit showed they are *present* but *unlabelled as derived*.

## 2. Settled vs open

**Settled by the owner (2026-09-12):** option **(ii)** — make the pre-fetch
artifact structural. Decision **1(c)** — `layouts.json` is authoritative for
layout semantics, with a per-load override escape hatch.

**Consequences already accepted:** Decision 2 (the CSV header rule) becomes moot;
the 2026-09-10 workflow/tooling question "re-extract everything?" resolves to
*structure, not values*.

**This blueprint settles:** the artifact schema (§4), cell addressing (§5), the
`presence` mapping (§6), the allow-list↔spec join (§7), and the 11-spec migration
(§8).

## 3. Flow — current vs target

```
CURRENT
  Drive Sheet --sheets dump (values.get)--> <alias>__<tab>.csv
                                              |
                              loader21: csv_skip + csv.DictReader + name map
                                              |
                                          books.db     (derived == measured)

TARGET
  Drive Sheet --sheets snapshot (spreadsheets.get + includeGridData)--> <alias>__<tab>.json
                                              |
                              loader21: A1 map + allow-list tiers + presence
                                              |
                                          books.db     (derived != measured)
```

`sheets dump` is **retained** for ad-hoc and legacy reads; it leaves the ingest
path.

## 4. Artifact schema (the interface)

Written to `private/raw/sheets/<alias>__<tab>.json` (gitignored, values included).
Written by a new `bagend.py sheets snapshot <alias> --tab T [--out PATH]`.

```json
{
  "artifact_version": 1,
  "alias": "pnl-records",
  "tab": "Gain-Loss Cost Basis",
  "spreadsheet": "Stats-Acct-PnL-Records",
  "drive_id": "…",
  "drive_modified": "2026-09-11T…Z",
  "fetched_at": "2026-09-12T…Z",
  "range": "'Gain-Loss Cost Basis'!A1:N69",
  "merges": ["B2:C2"],
  "cells": [
    {"a1":"B2","kind":"formula","formula":"=SUM(B3:B40)","effective_type":"number","value":123.4},
    {"a1":"A3","kind":"literal","effective_type":"number","format":"yyyy-mm-dd","value":"1996-01-01"}
  ]
}
```

Rules: empty cells are **never** emitted (no padding rows); `value` is the typed
effective value; `kind` is `formula | literal`. Provenance for the artifact is
appended to `private/raw/_provenance.tsv` with
`source_kind=native-google-sheet`, `obtained_via=sheets.snapshot`.

## 5. Cell addressing in the loader

- Build `cells: {(row:int, col:letter) -> cell}` from the artifact.
- **Column letters are canonical**; `A1` is derived from `(row, col)`.
- Header names come from the allow-list tiers: `header_row` gives the label row,
  `group_row`/`sub_header_row` compose composite names (`Deposit_TD`), and
  `header_totals` cells **inside** a header row are excluded from name
  composition (they are totals, not labels — the `NEAR` `C2`/`G2` case).
- Data rows = from `first_data_row` forward, minus `skip_rows`
  (grand-total rows, blank bands, pre-series label rows).
- A spec's `columns` entry references an allow-list column by **letter**, so the
  metric id is resolved once, not re-derived per load.

## 6. `presence` mapping — no schema change

The store already constrains `presence IN ('measured','estimated','error')`.

| Source cell | Result |
|---|---|
| `kind: literal` | `presence = 'measured'` (default) |
| `kind: formula` | `presence = 'estimated'` |
| cell in `skip_rows` | **not ingested** (total/blank/label — not a record) |
| cell in `external_links` | `presence = 'estimated'` + the link recorded in the layout evidence |
| absent row/period | unchanged: absence is recorded in `coverage_calendar`, never as zero |

Illustrative impact: `pnl-records / Gain-Loss Cost Basis` moves ~539 cells from
`measured` to `estimated`; the five `holdings` tabs move 47–77 cells each.

## 7. Integration boundary — the allow-list↔spec join (decision 1(c))

Join key: **`(alias, tab)`**.

1. The loader resolves the allow-list entry in `private/layouts/layouts.json`
   **first**. No entry → **refuse to load**, naming the missing `(alias, tab)`.
2. The spec keeps only loader-specific fields: artifact path, `family`,
   `columns` (selection), `date_format`, `month_end`, `precedence`, `amount_mode`,
   `parser`.
3. If a spec also carries a layout field, it must be expressed as an explicit
   **override with a reason** (`override: {header_row: 4, why: "…"}`). An override
   **without** an allow-list entry is refused.
4. Any disagreement between a spec layout field and the allow-list entry is
   **refused and reported**, never silently resolved in either direction.

This is what makes drift impossible rather than merely unlikely.

## 8. Migration of the 11 CSV-backed specs

| Spec | Action |
|---|---|
| `pnl_records:cost-basis` | snapshot — 97.8% of cells become `estimated` |
| `stats:net-worth-data` | snapshot — 194 formula cells reclassified |
| `ss_earning:official-data` | snapshot — column G derived |
| `holdings:2022 … 2026` (×5) | snapshot — live-quote columns become `estimated`; `T1` header formula excluded from names |
| `ss_earning:payment-estimates` | snapshot — `Age 67` slot reclassified |
| `ss_earning:cola` | **RETIRE** — Task #3 already ruled it out (public data, web-pullable) |
| `fi_balances:over-time` | **UNCHANGED** — `source_kind: drive-file`; it *is* a CSV in Drive, no sheet exists. Revisit only if the owner re-creates it as a Sheet. |
| `stats__Net-Worth Data.csv` vs `stats__Net_Worth_Data.csv` | **clean up** the stale duplicate; one identity via provenance |

## 9. Implementation plan (phases + gates)

| Phase | Work | Gate |
|---|---|---|
| **P1** | `sheets snapshot` command + provenance row | Artifact for one tab; its values diff **exactly** against that tab's existing CSV |
| **P2** | Structural reader in `loader21`, additive behind a spec flag; allow-list join + refuse rules | One source loaded both ways → fact rows identical **except** `presence` |
| **P3** | Migrate the 10 snapshot specs; retire COLA; dedupe the stale file | Parity harness + existing loader battery + schema harnesses green |
| **P4** | Per-column derived-vs-measured reconciliation for the 9 inadequate specs | A per-column table reviewed before any store load; no unreviewed `estimated` |
| **P5** | `sheets dump` leaves the ingest path; README + North Star + ledger | Doc truth-up; changelog entry |

## 10. Test plan

- **T1 parity** — per migrated source: structural load vs CSV load agree on row
  count, natural key and values; only `presence` may differ.
- **T2 derivation** — `pnl-records` yields exactly the formula-cell count as
  `estimated` (539 at audit time).
- **T3 tiers** — `stats / Inv Income` composes `group_row`+`header_row` names and
  excludes the grand-total row and the `header_totals` cells.
- **T4 no padding** — empty cells never become rows; row counts match the source's
  real extent.
- **T5 privacy** — no values reach any committed file; hygiene gate 2/2.
- **T6 staleness** — a snapshot whose `drive_modified` predates the sheet's
  current `drive_modified` is **refused** (new capability: today's CSV can be
  silently stale).
- **T7 regression** — loader battery (30 assertions) + both schema harnesses green.

## 11. Risks

| Risk | Mitigation |
|---|---|
| A snapshot bundles values, so a delegate pointed at it sees figures | Delegates keep structure-only reads; the "no figures in briefs/prompts" rule stands; P1 exposes `--structure-only` for delegate-facing use |
| Sheet changes mid-audit invalidate comparisons | artifact carries `drive_modified`; T6 refuses stale artifacts |
| Larger local artifacts | JSON per tab, ~same order as today's CSV; `private/` is gitignored |
| Half-migrated state (some specs structural, some CSV) | P2 is additive behind a per-spec flag; P3 completes the set; a spec may not mix both in one load |

## 12. Out of scope

Re-fetching values for tabs whose content has not changed; the four layout
questions already settled in Task #3; any write toward Drive (flag-only stands).
