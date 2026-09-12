# Blueprint v0.3 — structural pre-fetch artifact: the executable contract

**Date:** 2026-09-12 · **Author:** Roth (COS) · **Status:** DRAFT — awaiting owner ratify
**Supersedes:** v0.1, v0.2, v0.2.1 (kept for the revision record)
**One document, one sequence.** The panel's unanimous recommendation was to stop
issuing deltas and publish a single implementable contract. This is it.

---

## 0. Review basis, and how much each voice is worth

| Round | Reviewer | Verdict | Independence caveat |
|---|---|---|---|
| 1 | `gpt-5.6-luna` | v0.1 fails | clean |
| 1 | `qwen3.8-flash` | v0.1 fails | clean |
| 1 | `glm-5.3-flash` | v0.1 fails | clean |
| 2 | **GPT-5.6 Sol** | **Reject** — revise before ratification | clean |
| 2 | **Grok 4.6** | **Reject** — collapse into one v0.3 | clean |
| 2 | **Qwen3.8-Max** | **Reject** — not ready to ratify | **weakened**: read the appendix before starting (self-disclosed) |
| 2 | **GLM-5.3-Max** | Accept-with-changes → v0.3 | **not family-independent** from the round-1 glm leg (self-disclosed) |

Both impaired-independence flags were volunteered by the reviewers, unprompted.
Convergence from those two carries less weight than from GPT-5.6 Sol and Grok 4.6,
and is graded accordingly.

**Corrections already made to the evidence base:** the audit was re-read at full
extent after a reviewer showed the original sweep used an 80-row window
(`Net-Worth Data`: 194 → **1125** formula cells). See
`.scratch/csv_audit/AUDIT.md`, which now carries the correction and the lesson.

## 1. Objective and non-goals

Replace the loader's values-only CSV input with a **structural artifact** so a
**derived** cell can never enter the store indistinguishably from a **measured**
one, and so the ratified layout knowledge (`header_row`, `group_row`,
`sub_header_row`, `first_data_row`, `skip_rows`, `derived_columns`,
`external_links`, `header_totals`) is actually consumed (Task #18).

**Non-goals:** re-computing values; writing to the owner's Drive (flag-only
stands); fixing task #19(c) (separate task).

## 2. Scope decision — where the semantics live

The keystone finding: **only `fact_state` has a `presence` column**, while the
nine snapshot specs write to four families. Extending `presence` per-row across
every family was the v0.2 answer and it was wrong on two counts — it cost a
rebuild, and it put **column-grain** facts on rows.

**Decision (panel majority):**
- **Derivation lives on `src_column`** — `origin`, `derivation_kind`,
  `formula_shape`. `src_column` already declares `metric_id` (FK `dim_metric`),
  `header_text`, `col_index`, `account_id`, `unit` with
  `UNIQUE (tab_id, col_index, header_occurrence)` — **and nothing has ever written
  to it**. Additive and nullable: **no CHECK rebuild for derivation.**
- **`presence` stays per-row, only where a family needs it** —
  `fact_state` (has it), plus `holding_state`, `ss_earnings_annual`,
  `ss_benefit_estimates` (do not). `holding_state` also lacks `needs_verify` and
  gets it regardless of this decision.
- **`zero_from_blank`** is a `presence` value, so the one CHECK change is limited
  to the tables that actually carry `presence`.

## 3. The artifact — complete schema

`private/raw/sheets/<alias>__<tab>.json`, written by `bagend.py sheets snapshot`.
Values included (it is the ingest input); `private/` only.

```json
{
  "artifact_version": 1,
  "alias": "stats", "tab": "Net-Worth Data",
  "spreadsheet": "Stats", "drive_id": "…", "sheet_id": "<int>",
  "requested_range": "'Net-Worth Data'!A1:GR100,000",
  "returned_bounds": {"rows": 329, "cols": 19},
  "tab_extent": {"rows": 329, "cols": 19},
  "truncated": false,
  "drive_modified": "2026-09-11T…Z", "fetched_at": "2026-09-12T…Z",
  "artifact_sha256": "…",
  "merges": ["B2:C2"],
  "cells": [
    {"a1":"H5","kind":"formula","formula":"=SUM(H6:H50)","error_type":null,
     "numfmt_type":"number","numfmt_pattern":"#,##0","value":123.4},
    {"a1":"A6","kind":"literal","numfmt_type":"date","numfmt_pattern":"yyyy-mm-dd",
     "value":"1996-01-01"},
    {"a1":"C4","kind":"formula","error_type":"#NAME?","value":null},
    {"a1":"E9","kind":"spill","spill_of":"E2","value":null},
    {"a1":"K3","kind":"literal","note":{"has_note":true,"note_is_formula":true,"formula_masked":"=n+n"}}
  ]
}
```

**Hard rules**
- `truncated` is computed against `tab_extent` from `metadata()`; **a truncated
  artifact is refused by the loader**, never partially loaded. All three v0.2.1
  shape assertions were previously satisfiable on a truncated read.
- **Blanks are emitted explicitly inside the ingest rectangle** (below), so
  `zero_from_blank` never rests on an absence inference.
- `numfmt_pattern` is mandatory: without it the serial→date behaviour cannot be
  replaced and typed-value parity cannot be proved.
- `spill` cells carry `spill_of`; an **indeterminate spill extent refuses**.
- `note` is present only under opt-in and never enters fact rows.
- **ingest rectangle** = the declared data rectangle from the allow-list
  (`first_data_row` … last row, mapped columns). Blank *inside* it = a cell;
  outside it = absent.

## 4. The classifier — ordered, total, with legal states

Column-grain derivation, row-grain presence. Applied **after** merges are
resolved and **after** the rectangle is established.

**Order:** (1) resolve merges → (2) establish rectangle → (3) classify each cell →
(4) refuse on any unmapped state.

| Cell state | `origin` | `derivation_kind` | `presence` |
|---|---|---|---|
| typed literal | `entered` | — | `measured` |
| in-rectangle blank, live row | `entered` | — | `zero_from_blank` |
| merge anchor | as the anchor cell | as the anchor | as the anchor |
| **merge shadow** | inherits anchor | inherits anchor | inherits anchor |
| formula → pure reference | `copy` | `copy` (+`copy_of`) | **the source's presence** (a copy never raises trust) |
| formula, all operands literal | `entered` | `constant` | `measured` |
| deterministic arithmetic on measured input | `derived` | `{deterministic}` | `estimated` |
| aggregate over a span | `derived` | `{aggregate}` | `estimated` |
| lookup / projection | `derived` | `{projection}` | `estimated` |
| depends on another derived cell | `derived` | `{…, chain}` | `estimated` |
| cross-sheet / external | `external` | `{…, chain}` | `estimated` |
| formula → error | `derived` | — (+`error_type`) | **`error`** |
| formula → empty string | `derived` | — | **not ingested, reason logged** |
| array spill | inherits `spill_of` | inherits | inherits; indeterminate → **refuse** |
| key/date column | `key` | — | **not a fact row** (row addressing) |
| unparseable formula | `derived` | `{unknown_formula}` | `estimated` **+ quarantine** |

**`derivation_kind` is a set, not a partition** — an aggregate over derived inputs
is `{aggregate, chain}`. `refuse` means quarantine, never a default to `measured`.

**Legal `(origin, presence)` pairs** are enforced by a composite CHECK; every
other pair is rejected at insert.

## 5. Store contract

- **Errors**: canonical token in `value_text` with `presence='error'` **and** a
  typed `error_type` column — the one-of value CHECK currently makes an error row
  unrepresentable.
- **`content_hash` must include `presence` and `origin`.** Today a measured `0`
  and a `zero_from_blank` `0` hash identically, so the reclassification would be
  silently skipped — two reviewers found this independently.
- **The dedupe probe is scoped to current rows**, so a reversion to a superseded
  value is not dropped.
- **Copy contract**: `copy_of` persists the lineage; `v_state_current` exposes
  `presence`/`origin`; `v_net_worth` gains a composition breakdown
  (`n_measured`/`n_estimated`/`n_copy`/`n_zero_from_blank`/`n_error`), and
  **additive totals exclude `copy` and `error`**. Today `v_net_worth` sums
  unfiltered and its `n_error` counts `value_num IS NULL`, so the anti-double-count
  rule has no enforcement point at the consumer.
- **Measurable = `presence='measured'`**, everywhere, by definition.

## 6. Identity and provenance

- Join on **`(drive_id, sheet_id)`**; tab title and alias are *validated
  metadata*, not keys (a rename must not create a new tab).
- A provenance record **keyed by `artifact_sha256`** carries `drive_id`,
  `sheet_id`, tab title, alias, artifact version, range, and fetch time.
  `_provenance.tsv` cannot support the promised cross-check today — it holds none
  of these — and parsing alias/tab from the filename would reinstate the
  filename-as-identity rule the charter forbids.
- **Staleness**: a per-tab **structural fingerprint** from the artifact; file
  `modifiedTime` is a coarse re-fetch hint only, and a mismatch **warns and
  re-fetches — it never refuses a load**. (A tab-scoped `modifiedTime` does not
  exist; `sheet_modified` is file-wide.)

## 7. Quarantine and completeness

Quarantine must be **visible**, or it trades an outage for silent partial data —
`v_net_worth` would simply look thinner and complete.

- A quarantined spec writes `coverage_calendar` rows (`not-loaded`, naming the rule
  that fired) and sets `load_batch.status='partial'`.
- **Promotion is refused** while any required spec is quarantined, unless an
  owner-acked skip list names it.
- **Non-overridable fields are fixed in code**, not self-declared by the spec; an
  override requires an owner-ruling reference, and a free-text reason is not
  authorization.
- Specs are marked **required vs optional**, with a batch completeness threshold.

## 8. Phases and gates — correct order

Reconciliation now precedes promotion. v0.2 had it backwards.

| Phase | Work | Gate |
|---|---|---|
| **S** | Scope: derivation on `src_column`; per-family presence (§2) | This document ratified |
| **P1** | Artifact writer + reader; **no store write** | Coverage asserted against `metadata()`; `truncated=false`; `numfmt_pattern` emitted; **typed-value parity** against independent probes (not the same call), classified *intended fix / bug / unknown*; `_typed` serial→date **not** reproduced |
| **P0** | Schema: `presence` + `zero_from_blank` where needed, `error_type`, `origin`/`derivation_kind`/`formula_shape`/`copy_of` on `src_column`, `holding_state.needs_verify`, composite legal-pair CHECK, hash recipe | Rebuilt table compared against a **freshly created** table (a CHECK change has no ALTER to diff); store rebuilds clean |
| **P2** | Positions onto the declarative layout (Task #7 prerequisite); load into a **fresh empty shadow** | Shadow vs live diff under the same three-way classification, with `zero_from_blank` **pre-declared** as intended divergence |
| **P4** | Per-column derived-vs-measured reconciliation | **Owner-reviewed table** accepted |
| **P3** | Promotion | WAL-safe cutover: writers closed, checkpoint, FK + integrity checks, fsync, same-filesystem `os.replace`, reopen + smoke test, checksummed rollback retained |
| **P5** | CSV path leaves ingest; docs truth-up | Ledger + North Star close |

## 9. Verification

Carried from v0.2.1 and repaired: total-function assertion (every state classified
or refused) · merge-shadow ≠ blank · external precedence · error mapping ·
`copy` never summed with its source **at the view layer, not just the loader** ·
`zero_from_blank` distinct from a measured zero **through the hash** ·
quarterly/regression fixtures for unchanged-value reclassification · crash and
fault-injection tests at each cutover boundary · **the two-zeros harness case**.

## 10. Prerequisites and first wave

- **Task #7 is a hard prerequisite for the five holdings specs**: their sole
  cross-sheet column pulls from the per-account state tabs #7 is about, and
  `load_holdings` is **positional** (hardcoded ordinals), so the join, the
  coordinate audit, the shape assertions and the inclusion diff would never fire
  on them.
- **First wave = `stats` + `ss-earning` only.** Small, already allow-listed,
  fully read.

## 11. Decision status

| | Position |
|---|---|
| **D-1** scope | **Answered by §2**: derivation column-grain on `src_column`, presence per-row only where needed. Far smaller than v0.2 claimed. |
| **D-2** `fi_balances` | **Settled — unanimous: keep CSV**, honour `header_row`. Rows must not be stamped `origin='entered'`; record `structural_coverage='none'`. No owner action. |
| **D-3** notes | **Yes, opt-in**, scoped by allow-list, redacted in structure-only, **never parsed into fact rows**. Note ≠ threaded comment (a separate, unsupported resource). |
| **D-4** per-column | **Use `src_column`**; do not add fields to the allow-list JSON. |

## 12. Deferred / out of scope

Task #19(c) needs `numfmt_pattern`, delivered in P1 but the fix itself is separate ·
Task #7 · charter amendment v1.0.2 (the `AGENTS.md` native-read rule and both Bag
End skills still describe the values-only path) · Drive comment threads.
