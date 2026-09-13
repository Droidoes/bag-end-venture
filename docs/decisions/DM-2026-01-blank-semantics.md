---
id: DM-2026-01
date: 2026-09-12
desk: accounting
status: decided
review-by: at P3 (before the live store is rebuilt)
---

# Decision Memo — what a blank cell means, column by column

## Decision

A blank numeric cell **inside an existing live row means 0**, recorded as
`presence='zero_from_blank'` — **except** where the column declares
`blank_means='not_applicable'`, meaning the cell has no meaningful value at that
row and **no row is written**. The default is `zero`; the exception is declared
per column, never inferred.

## Context

The 2026-09-12 structural load of the first wave (`stats / Net-Worth Data`,
`ss_earning / Official Data`) materialised blanks as `zero_from_blank` for every
mapped column, as the ratified rule directed. It produced 298 asserted zeros for
an **annual** metric on a month-end spine:

| metric | live rows | shadow rows | of which `zero_from_blank` |
|---|---|---|---|
| `IRS_INCOME` | 27 | 328 | 298 |
| `TOTAL_ASSETS` | 969 | 1705 | 738 |

Both used the same rule; they are not the same situation. `TOTAL_ASSETS` zeros
are correct — an account not yet open (or already closed) contributes 0 to a
total, and the store's existing invariant is that it reproduces the source's own
Total Assets. `IRS_INCOME` is an *annual* figure: a blank in a non-December month
means there is no observation there, not that income was zero.

The owner's ruling of 2026-09-10 was written for 401k catch-up contributions,
where a blank before 2019 genuinely is 0, and its own text scopes it: *"this is
CELL-level only. An absent ROW or PERIOD is still 'not recorded', never zero."*
The rule was sound; applying it unconditionally to every column was not.

## Alternatives considered

1. **Global zero — keep the status quo.** Simplest, no curation, and it still
   reconciles `TOTAL_ASSETS`. But it asserts roughly 300 zeros per annual metric
   that the source never stated, and it does so **invisibly**: the pre-declared
   diff reported "intended 1760 · bug 0 · unknown 0" while masking exactly this.
2. **Infer from `period_grain` — COS's first proposal; the owner rejected it.**
   Mechanical and curation-free, since `fact_state.period_grain` and
   `src_tab.grain` already exist. Rejected because it (a) couples two independent
   properties — how often a thing is measured vs what a blank means; (b) creates
   exceptions to a ratified rule by inference, invisibly; (c) uses a
   **metric-level** field to answer a **cell-level** question, the same
   grain-mismatch this project has spent the session unpicking; and (d) fails
   silently when grain is `unknown`.
3. **Per-column declaration `blank_means` — CHOSEN.** `zero` (default) or
   `not_applicable`, declared in the allow-list per column. Block-scoped for free
   because `src_column` hangs off `tab_id`. Cost: one declaration per column that
   needs the exception, plus the per-column allow-list fields (v0.3 §E5b) that
   were already owed.

## Rationale

Doctrine (`AGENTS.md` §2): *"Reported / derived / planned stay distinguishable;
unknown is not zero"* and *"Ranges, never false precision."* Fabricating 298
stated zeros per annual metric is false precision manufactured by the loader.

The owner's principle, applied consistently with the schema's existing design:
`src_tab.header_state` and `src_tab.grain` are already **declared** fields, not
inferred ones. `blank_means` follows that pattern — **declare, don't infer**.

Minor ambiguities resolved here: (i) the vocabulary is two values, not three — a
cell-level `not_recorded` would contradict the ruling's own cell/row boundary and
its home is `coverage_calendar` (`expected` + `absent-in-source` / `loaded-empty`
/ `not-loaded`); (ii) token spelling is words (`zero`, `not_applicable`) rather
than the literal `0`, so the field reads as a rule rather than a value.

## Numbers used

| Figure | Value | As-of | Source |
|---|---|---|---|
| `IRS_INCOME`: live rows → shadow rows | 27 → 328 | 2026-09-12 | `private/books-shadow.db` (row counts only) |
| `IRS_INCOME`: `zero_from_blank` rows | 298 | 2026-09-12 | same |
| `TOTAL_ASSETS`: live rows → shadow rows | 969 → 1705 | 2026-09-12 | same |
| `TOTAL_ASSETS`: `zero_from_blank` rows | 738 | 2026-09-12 | same |
| `src_column` rows written (first ever) | 18 | 2026-09-12 | same |

Structural counts only — **no financial values appear in this memo**, so the
committed copy needs no scrubbing. The counts are already published in the P2
commit message and the audit evidence.

## What would change this decision

- A column declared `blank_means='zero'` whose zeros **break the total
  reconciliation** against the source's own stated total (the `TOTAL_ASSETS`
  invariant). That is the arbiter, and it is mechanical.
- The source beginning to state explicit zeros where it previously left blanks —
  which would make the rule moot for that column.
- `not_applicable` proving to hide a gap: if an **anchored** period (December for
  an annual metric) is blank and is silently skipped. This is why the
  implementation must wire `not_applicable` against `coverage_calendar.expected`
  so an anchored gap fails loudly rather than becoming another hiding place.

## Follow-ups

- **Roth:** add `blank_means` to `tools/manifests/layouts.schema.md`; teach the
  loader to honour it; **report per-column zero counts at load** so an undeclared
  `not_applicable` column is visible rather than discovered by hand; re-load the
  shadow and re-run the diff with `zero_from_blank` **derived per column instead
  of pre-declared**.
- **Roth, later:** E5b per-column allow-list fields (`metric_id`,
  `expected_label`, `role`); block activation (`src_tab.block` is designed,
  dormant); Slice B views; then P3 promotion.
- **Joe:** none — the ratification is this memo.
