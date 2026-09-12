# Blueprint v0.2 (delta from v0.1) — structural pre-fetch artifact

**Date:** 2026-09-12 · **Author:** Roth (COS) · **Status:** DRAFT — awaiting owner ratify
**Supersedes:** `2026-09-12-structural-prefetch-v0.1.md` (kept for the record)
**Incorporates:** two independent flash reviews — `gpt-5.6-luna`, `qwen3.8-flash`.
`glm-5.3-flash` still running; folded at v0.2.1 if it adds anything material.
Reviews: `.scratch/csv_audit/review/leg-{luna,qwen}.md`

---

## 0. Review outcome

**Both legs returned "fails as written."** No leg defended v0.1's core claims.
Everything below is a response to a specific finding, and v0.1's errors are
stated rather than quietly patched.

| # | Finding (convergence) | Fix |
|---|---|---|
| 1 | "No schema change" is false — `books.db` cannot express the ratified blank rule (`n/n`) | **D2** |
| 2 | `formula → estimated` collapses distinct semantics (`n/n`) | **D1** |
| 3 | Merge shadows unhandled; `merges` used for nothing (`n/n`) | **D1** |
| 4 | §7 override vs refusal self-deadlocks; identity too weak (`n/n`) | **D3** |
| 5 | No shadow store, atomic promotion or rollback (`n/n`) | **D5** |
| 6 | P1's "diff against the CSV" canonizes a known bug (`1/n` — qwen) | **D5** |
| 7 | T6 staleness needs live Drive, contradicting offline ingest (`1/n` — qwen) | **D6** |
| 8 | Decision 2 is not moot (`1/n` — qwen) | **D4** |
| 9 | Coordinate systems mixed with no audit gate (`1/n` — qwen/luna) | **D7** |

## D1 — §6 replaced by a **total presence function** (the core fix)

A cell has **two orthogonal facts**: what it *is* (origin) and how much it should
be trusted (presence). v0.1 overloaded one column with both. Every mapped cell
resolves to exactly one pair, or to "not ingested" — asserted in code and tested
(T8).

| Cell state | `origin` | `presence` |
|---|---|---|
| literal value cell | `entered` | `measured` |
| literal key cell (year/date series) | `key` | `measured` |
| **blank inside a live row** (in range, row exists) | `entered` | **`zero_from_blank`** |
| **merge shadow** (inside a merge range, not the anchor) | inherits the anchor | inherits the anchor — **never** read as blank |
| formula = pure reference to another mapped cell (`=O`) | `copy` | `measured` |
| formula whose operands are **all literals** (`=4777.21+6289.94`) | `constant_formula` | `measured` — it *is* a stated value |
| formula = deterministic arithmetic on a measured input (`=D3+1`) | `derived` | `estimated` |
| formula = aggregate / projection (`SUM`, `LOOKUP`, `GOOGLEFINANCE`) | `derived` | `estimated` |
| external reference (`IMPORTRANGE`, cross-sheet pull) | `external` | `estimated` |
| formula → text/date used as a **key** | `key` | (presence semantics do not apply to keys) |
| formula → error | `derived` | **`error`** |

**Precedence rule:** membership in `external_links` **overrides** `kind` — this is
what stops a literal-valued external column (Taxes `E`/`H`) reading `measured` in
one row and `estimated` in another.

**Copy rule (anti-double-count):** a `copy` column is stored but is a *declared
duplicate* — the loader records its source cell, and no aggregation may sum a
`copy` together with its source.

**Merge rule:** `merges` is now load-bearing. A shadow cell is neither blank nor a
value; vertical data merges (NEAR's seven) are flagged as series-unsafe.

## D2 — Schema: exactly one CHECK extension plus one column

```sql
presence TEXT NOT NULL DEFAULT 'measured'
  CHECK (presence IN ('measured','estimated','zero_from_blank','error')),
origin   TEXT NOT NULL DEFAULT 'entered'
  CHECK (origin IN ('entered','copy','constant_formula','derived','external','key'))
```

- `zero_from_blank` is **owner-ratified** (`layouts.json._cross_cutting.blank_cell_is_zero`)
  and currently unrepresentable — v0.1's "no schema change" was simply wrong.
- `origin` is required because a cell can be measured-in-value while
  formula-in-origin.
- **SQLite cannot ALTER a CHECK** — this is a table rebuild, done as a versioned
  DDL step with an ALTER-parity harness, exactly as v0.2.4 was handled.
- Carried by a **new phase P0** (v0.1 had no phase carrying it).

## D3 — §7 repaired: override ≠ disagreement

- **Identity:** join on `(drive_id, sheet title)` with `(alias, tab)` as the human
  key; allow-list tab **patterns** (`'<year>'`) are expanded against the artifact's
  real tab list rather than matched literally.
- **Overrides are legal.** An override must name the field, carry a reason, and is
  recorded in the load log. It is *not* a disagreement.
- **Refusal is reserved for three cases:** no allow-list entry; an override with no
  allow-list entry to override; and an attempt to override a field the allow-list
  marks **non-overridable** (`key_column`).
- **Orphan hole closed:** an entry whose `role ∈ {derived, scratch, worksheet,
  duplicate}` must be *explicitly acknowledged* by the spec — it can no longer pass
  the join silently.
- **Quarantine, not outage:** a spec failing any rule is quarantined and reported
  loudly; it does not block the batch. (Both legs flagged blanket refusal as an
  outage risk.)

## D4 — Decision 2 un-mooted

`fi_balances:over-time` stays on CSV (§8: it is a Drive CSV with no sheet), so a
CSV path survives. **Adopt rule (A): honor `header_row` on the CSV path** for
CSV-backed specs. Alternative, owner's call: re-create that file as a Sheet and
retire the CSV path entirely.

## D5 — Phases repaired (shadow store, atomic promotion, rollback)

| Phase | Work | Gate |
|---|---|---|
| **P0** | Schema: presence CHECK + `origin` column, versioned rebuild | ALTER-parity harness green; store rebuilds clean |
| **P1** | Artifact writer + reader; **no store write** | Parity against **the source**, not the CSV. Compare **coordinates, types, inclusion, duplicate keys, and values** — not values alone |
| **P2** | Loader path behind a flag, writing to a **shadow store** (copy of `books.db`) | Shadow vs live per-table comparison report |
| **P3** | Migrate the 10 specs into the shadow | Comparison passes → **atomic promotion** (file swap); pre-promotion file kept as **rollback** |
| **P4** | Per-column derived-vs-measured reconciliation (the 9 inadequate specs) | Owner-reviewed table before promotion |
| **P5** | CSV path leaves ingest for native sheets; docs truth-up | Ledger + North Star close |

**P1's trap, fixed:** exact parity against the existing CSV would canonize
`sheets.py:94` — every integer in 20,000–80,000 rewritten as a date (**task
#19(c)**). The new path must **not** reproduce that behavior; every divergence
from the CSV is classified as *intended fix* / *bug* / *unknown*, and the
classification is part of the gate evidence.

## D6 — Tests repaired

- **T6 relocated:** the staleness guard belongs to the **pre-fetch** step, which
  compares `drive_modified` before writing the artifact. Load stays offline and
  auth-free (§1.3 preserved).
- **New:** T8 total-function assertion (no cell state unmapped) · T9 merge shadow
  ≠ blank · T10 external-link precedence over `kind` · T11 coordinate audit (below)
  · T12 error cells → `presence='error'` · T13 `copy` never summed with its source.
- `--structure-only` **must** run `_redact_formula`: a constant formula's literals
  otherwise leak in structure-only mode.

## D7 — Coordinate-system audit (new P4a)

Layout row numbers were ratified across **two coordinate systems** — some from
structural reads, some CSV-relative (`fi_balances`: `header_row: 3` vs
`csv_skip: 2`). New gate: **re-derive `header_row` / `first_data_row` /
`skip_rows` from the structural artifact and flag every disagreement** with the
ratified numbers before any load. One off-by-one `skip_rows` silently loses or
invents a row, and nothing in v0.1 would have caught it.

---

## Open for the owner (decisions, not work)

1. **Ratify the schema extension (D2)** — one CHECK value (`zero_from_blank`, already
   ratified in intent) plus one new column (`origin`). This is the only place v0.2
   touches the store's shape.
2. **`fi_balances`** — adopt CSV rule (A), or re-create the file as a Sheet?
3. **Cell notes/comments** — add `--with-notes`? You have said formulas can live in
   comments, and the reader currently ignores them.
