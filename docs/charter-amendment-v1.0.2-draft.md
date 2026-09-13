# Charter amendment v1.0.2 — DRAFT for owner ratification

**Date:** 2026-09-12 · **Author:** Roth (COS) · **Status:** **RATIFIED AND APPLIED**
— owner ratification 2026-09-12 · this file is the ratification record.
**Governance:** `AGENTS.md` §6 — the charter changes only by explicit owner
ratification, and every change is logged in §8 (done: see the v1.0.2 entry).

**Applied:** `AGENTS.md` §4 (rule replaced, coverage bullet added), the version
line moved 1.0.1 → 1.0.2, the §8 changelog entry added, and both skills updated.
§5 hard boundaries untouched, per the owner's explicit ruling of 2026-09-12.

---

## 1. Why this amendment exists

The §4 **native-read rule** was written on 2026-09-06 and names exactly one read
path: `tools/bagend.py sheets tabs|dump` → **typed CSV**. Four things have
happened since, and the charter has not caught up:

| Date | Event |
|---|---|
| 2026-09-10 | `bagend.py sheets grid` shipped — a real **structure** read (merges, formulas, formats). It appears in no charter or skill. |
| 2026-09-10 | The same session recorded that values-only input made survey legs *agree on wrong layout readings* — correlated error. |
| 2026-09-12 | An audit of all 11 CSV-backed ingest specs found **8 inadequate + 1 marginal**: they read tabs where formula-derived cells are pervasive (one tab 97.8% formulas). A values-only read cannot tell derived from measured, so computed values entered the store as observations. |
| 2026-09-12 | `sheets snapshot` shipped (P1) — the **structural ingest artifact**: values plus formulas, merges, number formats, errors and explicit blanks, with asserted coverage. |

**The net problem:** the charter's own rule still points a future session at the
values-only path, and both Bag End skills still instruct ingest from `sheets dump`.
The rule also covers only *xlsx* corruption — it never prohibited the
**values-only flattening** that caused the actual damage.

## 2. What this amendment does NOT change

- **§5 hard boundaries: untouched**, per the owner's ruling of 2026-09-12.
- The **xlsx prohibition**: unchanged, and reinforced.
- Vault read-only (§5.4), flag-only toward sources, the three zones, the
  `[verify]` rule, the entity model, the panel protocol: all unchanged.
- The provenance invariants: **extended**, not replaced.

## 3. AGENTS.md §4 — exact replacement

**REPLACE this bullet:**

> - **Native-read rule.** Native Google Sheets are read through the Sheets API
>   (`tools/bagend.py sheets tabs|dump` → typed CSV). Exporting one to xlsx for
>   analysis is prohibited — it corrupts the data (padding rows, re-inferred
>   years, crashed chart tabs).

**WITH:**

> - **Native-read rule (v1.0.2).** Native Google Sheets are read through the
>   Sheets API, never through a converted export. There are two read paths and
>   the choice is not optional:
>   - **Structure is required — for layout and for ingest.** `bagend.py sheets
>     grid` (merges, formulas, formats) for inspection; `bagend.py sheets
>     snapshot` (values **plus** formulas, merges, number formats, errors and
>     explicit blanks) as the ingest artifact. A values-only read cannot tell a
>     formula-derived cell from a measured one, and cannot see a merged header at
>     all — its anchor looks like a label and its siblings look like blanks. The
>     2026-09-12 audit found 8 of 11 ingest specs reading tabs where derivation is
>     pervasive for exactly this reason.
>   - **Values-only (`sheets tabs|dump` → typed CSV) is ad-hoc and legacy only.**
>     It is **not** an ingest path.
>   Exporting a Sheet to xlsx for analysis remains prohibited — it corrupts the
>   data (padding rows, re-inferred years, crashed chart tabs).
> - **Coverage is declared and asserted (v1.0.2).** Every structural read records
>   the requested range, the returned bounds and the tab's extent, and a
>   truncated read is refused rather than used. A 2026-09-12 sweep read an 80-row
>   window and published partial counts as measurements — understating the largest
>   tab by nearly six times. Coverage is a property to be proven, not assumed.

## 4. `bag-end-data` skill — exact replacement

**REPLACE the read-path block** (the three-line `bash` block and the paragraph
that follows it) **with:**

> **Three read paths — choose by purpose, never by convenience:**
>
> ```bash
> # 1. INGEST (default): structural artifact — values + formulas + merges +
> #    number formats + errors + explicit blanks, with asserted coverage.
> python3 tools/bagend.py sheets snapshot <alias> --tab NAME [--with-notes]
> #    -> private/raw/sheets/<alias>__<tab>.json
>
> # 2. LAYOUT / inspection: structure only, no values (delegate-safe)
> python3 tools/bagend.py sheets grid <alias> --tab NAME [--max-rows N]
>
> # 3. AD-HOC / legacy only: values as typed CSV — NOT an ingest path
> python3 tools/bagend.py sheets dump <alias> [--tab NAME]
> ```
>
> A values-only read **cannot** distinguish a formula-derived cell from a measured
> one, and cannot see a merged header. On 2026-09-12 that cost an audit its own
> headline numbers: 8 of 11 ingest specs read tabs where derivation was pervasive,
> and the first sweep understated the largest tab by nearly six times because it
> read an 80-row window while reporting its counts as measurements.
>
> **Coverage is asserted, not assumed.** `sheets snapshot` records the requested
> range, the returned bounds and the tab extent, and flags truncation; the loader
> refuses a truncated artifact.

**KEEP unchanged** the xlsx-corruption rationale and the `fetch` / `ingest xlsx`
refusal guards that follow it — both remain correct and were negative-tested.

## 5. `bag-end-team` skill — exact replacement

**REPLACE:**

> Native Sheets arrive as **typed CSV dumps** (`sheets dump`), never as xlsx
> exports; xlsx on disk may only be a drive-file.

**WITH:**

> Native Sheets arrive as the **structural artifact** (`sheets snapshot`) — never
> as an xlsx export, and never as a values-only CSV dump. Delegates receive the
> artifact **path**, and the no-figures rule still bars values from every brief.

## 6. AGENTS.md §8 — changelog entry to add on ratification

> - **v1.0.2 (2026-09-12, owner ratification)** — native-read rule strengthened:
>   structure is required for layout **and** ingest (`sheets grid`, `sheets
>   snapshot`); values-only CSV (`sheets dump`) is demoted to ad-hoc/legacy and is
>   no longer an ingest path; every structural read must declare and assert its
>   coverage. Triggered by the 2026-09-12 audit (8 of 11 ingest specs read tabs
>   where formula-derived cells are pervasive, so derived values entered as if
>   measured) and confirmed across two review rounds. **§5 hard boundaries
>   unchanged.**

Also on ratification: the version line at the top of `AGENTS.md` moves from
**1.0.1** to **1.0.2**.

## 7. What applying this looks like

One change set, after an explicit owner "ratify":
1. `AGENTS.md` — §4 replaced per §3, version line to 1.0.2, changelog entry added.
2. `bag-end-data` skill — read-path block replaced per §4.
3. `bag-end-team` skill — the Native Sheets line replaced per §5.
4. Hygiene gate, then one commit covering the charter + both skills.

**Not included:** `cos-role` (global). Its §2.5 principle — *read every source
through its native read path* — is already correct and repo-agnostic; the
Bag-End-specific paths belong in the two Bag End skills, not in a shared contract.
