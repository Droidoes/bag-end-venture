# Panel review — structural pre-fetch artifact (Grok-4.6)

**Reviewer:** Grok-4.6 (owner-initiated pro seat; not the COS chair).
**Version reviewed:** v0.2 + v0.2.1 as a pair (highest numbered blueprint in the directory is v0.2.1). v0.1 read only as the still-living substrate: artifact schema, flow, phases, tests. No higher version exists.
**Process note:** this prompt file contains the Appendix in §8. I read the prompt first (as instructed to follow it), then formed findings from v0.2 / v0.2.1 / the committed toolkit, then compared. Findings in §2 were reached from the design + code, not copied from the Appendix. Where the prompt-read contaminated independence, it is marked in §4.

**Code checked (read-only, no `private/`):** `tools/schema/books.sql` (`fact_state.presence` CHECK), `tools/manifests/layouts.schema.md`, `tools/bagend/sheets.py` (`_typed`, `grid_structure`, `_redact_formula`), `tools/bagend/loader21.py` (CSV skip, blank-skip, `content_hash` / identical-row skip), `docs/CODEBASE_OVERVIEW.md` invariant 4.

---

## 1. Verdict

v0.2 / v0.2.1 correctly kills v0.1's load-bearing errors (flat `formula → estimated`, "no schema change", merge shadows as blanks, override self-deadlock, CSV-as-parity-canon, load-time Drive). **Do not implement this pair as written.** The presence function is not total, the artifact schema was never amended to carry the facts the new function needs, the P2/P3 migration gates fight the current loader (`content_hash` skip; blanks currently dropped; P3 promotes before P4), and D7's "re-derive header_row" reopens a rule the allow-list already settled. Collapse to a single v0.3 document that closes the blockers in §2 before asking the owner to ratify.

---

## 2. Findings

| Sev | § | Finding | What I would change |
|---|---|---|---|
| **BLOCKER** | v0.1 §4 · D1 · E3 | Artifact rule is still "empty cells are never emitted." `grid_structure` already `continue`s on empty CellData. D1/E3 then require a "genuinely empty, in-range, non-shadow cell" to become `zero_from_blank`. That cell is not in `cells[]`. The pair never says whether missing-A1 ∩ ingest-rectangle = blank, and `range` today is the survey window (`A1:` + default 60×30), not the spec rectangle. | Amend the artifact contract: either emit explicit blank records inside the ingest rectangle, or define inference (missing ∩ rectangle ∩ not-shadow = blank) **and** require `sheets snapshot` to request that rectangle, not `grid_structure`'s survey caps. Put the rectangle in the artifact (`ingest_range`, not just the request range). |
| **BLOCKER** | D1 | **Spill / array results classify as literals.** `grid_structure` sets `kind=formula` only when `userEnteredValue.formulaValue` is present; otherwise `kind=literal`. ARRAYFORMULA / IMPORTRANGE / GOOGLEFINANCE / QUERY / FILTER spill cells typically have `effectiveValue` and no entered formula. They would land as `entered/measured`. The function is not total over Google's actual grid. [unsure] whether the nine snapshot tabs use spill; the classifier is wrong either way. | Classify: entered formula → formula; else if the cell sits in another cell's fill/spill range or a merge shadow → inherit; else literal. Record `spill_of` A1. Test with an ARRAYFORMULA fixture, not a live tab. |
| **BLOCKER** | D1 copy rule | A pure reference to another **mapped** cell becomes `origin=copy`, `presence=measured`. If the source is `derived/estimated`, the copy is **upgraded to measured**. That is the same collapse v0.1 was hanged for, one hop later. `=O` as written is also not a Sheets formula (`=O3` / `$O$3` / relative copies are). | Copy inherits the source's **presence** (and `derivation_kind` if derived). `copy` is an origin, not a trust upgrade. Parse a single-ref formula with a real A1 grammar; do not string-match `=O`. Transitive copies walk to the non-copy root. |
| **BLOCKER** | D1 · D2 | The function is not total, and the CHECKs do not enforce pairs. Formula-key cells have "presence N/A" while `origin`/`presence` are `NOT NULL`. Independent CHECKs allow `entered+error`, `key+zero_from_blank`, `copy+error`, etc. Formula that returns blank / `=""` / `IF(…,"")` has entered formula and possibly no effective value — no row in the table, and `fact_state` requires exactly one of `value_num`/`value_text`. | Publish an **allowed-pairs** table and a composite CHECK (or a tiny mapping table). Keys are addressing, not fact rows: do not persist `origin='key'` on `fact_state`. Specify error rows (`value_text = error_type`, `value_num NULL`) and blank-formula rows (not ingested vs `zero_from_blank`). |
| **BLOCKER** | D5 P2 · loader | `content_hash` is `H(account\|metric\|as_of\|ordinal\|value)` and identical hashes are **skipped without superseding**. A shadow that is a **copy of `books.db`** plus a structural reload is a no-op: presence never changes, the comparison report is green, the gate lies. Separately, `load_state_spine` already **drops blank cells** (`if cell is None or not strip: continue`). A correct structural load **inserts new** `zero_from_blank` rows. v0.1's "identical except presence" and v0.2's "shadow vs live comparison" are both the wrong predicate. | Shadow is a **fresh rebuild** (empty store, full loader, new path), not `cp books.db`. Hash must include `presence` (and `origin`) so a reclassification is a new version of the same `natural_key`, superseded in the usual way. Comparison vocabulary is the P1 one: *intended fix / bug / unknown*, including "new zero rows" as an intended fix. |
| **BLOCKER** | D5 P3 vs P4 | v0.2 **promotes at P3**, then reconciles derived-vs-measured at P4 "before promotion." That is two promotions, or P4 after live cutover. v0.1 had P4 *before any store load*. The reorder is a regression: the nine inadequate specs would enter live still unreviewed. E8 fixes the 9-vs-10 count, not the order. | Order: P0 schema → P1 artifact (no store) → P4 column reconciliation (owner table) → P2 load into **empty** shadow → compare → P3 atomic promote → P5 retire CSV for native sheets. No second promotion. |
| **MAJOR** | D7 vs E4 · layouts.schema.md §Rules.1 | D7 "re-derive `header_row` / `first_data_row` / `skip_rows` from the artifact and flag disagreements" runs a second election against numbers Task #3 already ratified. The committed rule is **`header_row` is authoritative, not heuristic.** E4 (labels at declared coordinates, skip-row shape, declared merges present) is the right gate. | Delete "re-derive." P4a = E4 on the **effective** layout (allow-list after recorded overrides). Disagreement with a heuristic detector is not a defect. |
| **MAJOR** | D1 copy · consumers | Copy is stored and "no aggregation may sum a copy with its source," but there is no store-level contract. `fact_state` is what queries and the finpage read. T13 as a loader unit test does not stop `SUM(value_num)`. | A view (or documented default filter) that excludes `origin='copy'` and `presence='error'` from measurable totals. Loader test **and** a query-surface test. Record `copy_of_a1` (column or `verify_note` convention) so T13 is auditable from the store. |
| **MAJOR** | D5 P3 "file swap" | Replacing a SQLite file is not atomic if any connection is open, and is corrupt if `-wal`/`-shm` are not part of the same snapshot. WSL + a live `query`/finpage connection is the normal case. "Pre-promotion file kept as rollback" is real only if that file is a consistent backup (`VACUUM INTO` / backup API), not `cp` of a hot DB. | Promotion protocol: refuse if the live DB is open; `VACUUM INTO` shadow and rollback artifacts; `os.replace` of `{db, wal, shm}` as a set on the same filesystem; smoke `PRAGMA integrity_check` before dropping the rollback. |
| **MAJOR** | E7 | `drive_modified` is file-wide. Restricting "to tabs the spec reads" is **not implementable** with Drive `modifiedTime`. A tab has no `modifiedTime`. E7 names a property that does not exist. | Staleness = hash of that tab's grid (or of the artifact body minus `fetched_at`) vs the previous snapshot of **that tab**. File-level `modifiedTime` is only a hint to re-fetch, never a load refusal by itself. Keep the check in pre-fetch so load stays offline. |
| **MAJOR** | D3 quarantine | Quarantine-not-blocking-the-batch avoids v0.1 outages, and can promote a store whose spine spec is missing. Absent row = "not recorded." A quarantined spec looks the same as "we chose not to load it." | Quarantine is a first-class load_batch / coverage status. **Promotion refuses** if any spec in the P3 set is quarantined, unless the owner acks a named skip list. Batch continues for diagnosis; cutover does not. |
| **MAJOR** | v0.1 §4 (unamended) | v0.2.1 adds `error_type`, merge shadows, provenance fields, per-column join — and never revises the JSON schema. No `error_type`, no `sheetId`, no `drive_id` on the `grid_structure` payload that snapshot would wrap, no blank records, no `spill_of`. Two commands (`grid` vs `snapshot`) will drift. | Promote `grid_structure` into `sheets snapshot`. One reader. Snapshot = full ingest rectangle + `drive_id` + `sheetId` + `drive_modified` + `error_type` + merges + optional notes. Do not grow a parallel parser. |
| **MAJOR** | D5 P1 | "Parity against the source, not the CSV" is right about #19(c) and circular if "the source" is the same `spreadsheets.get` that wrote the artifact. | Independent probe: `values.get` UNFORMATTED (no `_typed`) vs artifact `effectiveValue`, plus formula/merge presence vs `includeGridData`. Classify every CSV divergence as intended fix / bug / unknown. Snapshot must not call `_typed` (the 20,000–80,000 serial rewrite). |
| **MINOR** | D3 identity | `(drive_id, sheet title)` still breaks on a tab rename. `sheets` metadata already has `sheetId`. Title is the human key and the allow-list pattern key; it is not identity. | Identity = `(drive_id, sheetId)`. Title/pattern is how humans point. Rename → recorded alias, not a missed join. |
| **MINOR** | D3 non-overridable | Only `key_column` is non-overridable. Geometry (`header_row`, `first_data_row`, `skip_rows`) is the frame. E5a correctly allows filling `unresolved`/missing fields. A geometry override of a **ratified** field plus a weak E4 is a silent shift. The hatch is owner-settled — do not close it — but it is gameable. | Geometry overrides of ratified fields are legal and logged, and **P3 will not promote** while any such override is in the load without an owner ack. E4 runs **after** override application, against `expected_label` at the effective coordinates. |
| **MINOR** | D1 `constant_formula` | `=n+n` as `measured` matches "the owner typed the number in a formula," and fights "derived is never measured." Acceptable if origin stays `constant_formula` so a consumer can exclude it. | Keep the origin. Default measurable view includes it (it is a stated value). Document that. |
| **MINOR** | v0.1 T2 | Frozen formula-cell counts as a gate will fail on the next legitimate sheet edit. | Assert: every mapped formula cell in-range is non-`measured` (unless `constant_formula`/`copy` inheriting measured). No audit-time integers in tests. |
| **NIT** | D5 table vs E8 | v0.2 D5 still says "Migrate the 10 specs" after E8 corrected the arithmetic. The implementer will read the table. | One document; one count: 9 snapshot specs; P4 = 8 inadequate + 1 marginal; duplicate file is a store rebuild step, not a tenth spec. |
| **NIT** | D6 `--structure-only` | Requiring `_redact_formula` is correct and already implemented. Keep it. | Snapshot `--structure-only` must call the same helper, including constant-formula literals. |

Known gaps the prompt forbade reporting as novel (acknowledged, not scored as new): notes/comments unread; Task #19(c) still open (this review only requires the new path not call `_typed`); P4 column table is owner-reviewed and deferred in intent — I scored **order**, not the deferral; `fi_balances` is a Drive CSV; charter/skills still describe dump→CSV (v1.0.2).

---

## 3. The five open questions

### Q1 — Is the total presence function total? Copy enforceable? `external_links` over `kind`?

**Not total.** Unmapped or wrongly mapped: in-range blanks (not in the artifact); spill/array fills (literal); copy-of-derived (upgraded to measured); formula-that-returns-blank; formula-key "presence N/A" vs NOT NULL; note-only cells if `--with-notes` lands. Merge-before-blank (E3) is the right order **once blanks exist**. Vertical data merges as series-unsafe is right.

**Copy** is enforceable with an A1 parser and inherited presence; it is not enforceable as specified (`=O`, always `measured`). Record `copy_of_a1`; exclude `copy` from the measurable query surface.

**`external_links` overrides `kind`:** yes, as **column-level** precedence. That is the right fix for a column that is a cross-sheet pull even when some rows look like literals (the Taxes `E`/`H` case the blueprint names). It is the wrong fix if a column is genuinely mixed entered vs imported per row — [unsure], treat as a P4 column question, not a D1 default. Membership in `external_links` should set `origin=external` (not merely `presence=estimated`) so origin stays honest.

### Q2 — Schema extension: minimum? Right dimension? Fact row vs layout evidence?

`zero_from_blank` on `fact_state.presence` is **not optional**. North Star invariant 4 already names it; the DDL CHECK is `('measured','estimated','error')`. That is a documented-vs-schema split, and v0.1's "no schema change" was false. SQLite cannot ALTER a CHECK; a versioned rebuild (the v0.2.4 path) is the real cost.

`origin` belongs on the **fact row**, not only in layout evidence: the blueprint's own reason is mixed columns, and `external_links` / per-cell formulas make column-level origin a lie. Layout holds the **default role**; the row records what that cell actually was.

`derivation_kind` is **not** the same kind of necessity. It is a P4 convenience. Put it on the row as **NULL unless `origin='derived'`**. Do not denormalize it onto entered/copy/key rows. Do not treat it as a third orthogonal axis that independently CHECKs.

Minimum shape: extend `presence` (+ `zero_from_blank`); add `origin`; add nullable `derivation_kind`; add a **pair** constraint; do not add `origin='key'` as a fact-row value.

### Q3 — Join / refusal / quarantine: holes closed or new ones?

Holes closed: override ≠ disagreement; 1(c) hatch actually usable (E5a); `(alias, tab)` too weak; `derived/scratch/worksheet/duplicate` must be acknowledged; patterns expanded against real tabs; E6 provenance check is the right instinct.

New holes: (1) identity still title-based; (2) quarantine looks like "not recorded" at cutover; (3) non-overridable set is only `key_column` — acceptable **if** E4 runs on the post-override layout and promotion acks geometry overrides; (4) E6 as specified (artifact vs `_provenance.tsv` the snapshot just wrote) is circular. Cross-check artifact `drive_id`/`alias` against the **catalog/registry**, then require the provenance row to match that pair. Filename remains non-identity.

### Q4 — Migration safety: atomic? rollback real? phase order safe?

**Phase order is not safe** (P3 before P4; shadow-as-copy; hash skip; "identical except presence" false because blanks are new rows). **File swap is not atomic** without a closed-connection + WAL protocol. **Rollback is real** only as a consistent backup artifact, not a leftover hot copy.

P0-before-P1 is right. P1 must not canonize `_typed`. P5 leaving a CSV path for Drive-CSV files is right (D4).

### Q5 — Verification sufficiency: what is still not covered?

Covered well: T8 intent, T9 merge≠blank, T10 external precedence, T12 errors, T13 copy-not-summed (as a loader test), `_redact_formula` on structure-only, T6 moved to pre-fetch.

Still missing (must add):

- T-blank: in-range empty → `zero_from_blank`, not dropped, not merge-shadowed.
- T-spill: ARRAYFORMULA fixture → non-measured.
- T-copy-inherit: copy of derived stays estimated.
- T-pairs: illegal origin/presence rejected by DDL.
- T-hash: reclassification supersedes; it does not skip.
- T-open-db: promotion refuses when the live store is connected.
- T-quarantine: promotion refuses with an unacked quarantined spec.
- T-geometry: E4 at effective coordinates after override; heuristic re-detection is **not** a fail.
- T-#19(c): snapshot of an integer in the `_typed` window stays an integer.
- T-provenance: alias/drive_id mismatch against the catalog refuses.
- T-view: `SUM` over the measurable surface does not include `copy`.

---

## 4. Appendix — independent / agree / contradict

**Independently reached (then found in the Appendix or v0.2.1):** blank rule unrepresentable; flat formula mapping; merge shadows; override deadlock; CSV parity canonizes `_typed`; `(alias, tab)` too weak; error cells missing from the artifact; load-time shape assertions; file-wide staleness; `fi_balances` not moot; per-column fields absent from `layouts.schema.md`; P3/P4 arithmetic; provenance dying at the hand-off.

**Agree with the Appendix mapping** of those round-1 findings onto D1–D7 / E1–E8 as *intent*. Several fixes do not yet **hold** (this review's blockers): blanks vs "never emit empty"; P3-before-P4; E7's imaginary tab-level `drive_modified`; D7 vs authoritative `header_row`; artifact JSON unamended.

**Contradict:**

1. **D7 is not a fix for "coordinate systems mixed."** It is a second header election. E4 is the fix. CSV-relative vs sheet-row for `fi_balances` is a CSV-path problem (D4 / Task #18), not a reason to re-detect native-sheet headers.
2. **E7 does not close T6.** You cannot scope `drive_modified` to a tab. Need a tab body hash.
3. **E8 does not close the P3/P4 hole.** Counting 9 vs 10 is not ordering P4 before promotion.
4. **"Total presence function"** is the right shape and is not total in this draft (spill, blanks, copy-upgrade, key N/A, blank-valued formulas).
5. **v0.2 D2 "exactly one CHECK plus one column"** is already false once E2 adds `derivation_kind`. That is fine if v0.3 tells the truth about the minimum (see D-1).

---

## 5. The single change that would most improve the blueprint

**Rewrite v0.1+v0.2+v0.2.1 into one v0.3 spec** that an implementer can code from: one artifact JSON schema (blanks, errors, `sheetId`, ingest rectangle), one allowed origin/presence table, one phase order (reconcile → empty-shadow load → WAL-safe promote), one reader (`grid_structure` promoted to snapshot), one query contract (`copy` never measurable). Until that document exists, ratification is a vote on a changelog.

---

## 6. Recommendations the owner can ratify (D-1 … D-4)

Recommendations only. Joe ratifies.

### D-1 — Schema extension

**Recommend:** extend `fact_state.presence` with `zero_from_blank`; add `origin TEXT NOT NULL` with the D1 vocabulary **minus `key` as a fact-row value**; add `derivation_kind TEXT NULL` allowed only when `origin='derived'` (`deterministic` / `aggregate` / `projection` / `chain`); add a composite allowed-pairs CHECK; versioned rebuild as in v0.2.4. This is a schema question: consumers filter `presence`, and mixed columns make row-level `origin` load-bearing. Layout evidence holds **defaults** (`role`, `expected_label`), not the only copy of origin.

**Strongest argument against:** origin/derivation are properties of a cell in a tab, and will be identical on almost every row of a uniform column — denormalized onto every fact. A `src_cell_class(source, tab, a1, batch)` table would be cleaner.

**What would change my mind:** evidence that every mapped column is uniform (no per-row kind mix, no `external_links` override of mixed literals). Then column-level origin in the allow-list is enough and fact-row `origin` is YAGNI.

### D-2 — `fi_balances:over-time`

**Recommend: (a)** keep it as a Drive CSV; honor `header_row` on the CSV path (Task #18). Do not ask the owner to recreate a working file as a Sheet.

**Accuracy cost of (a):** none versus today. There are no formulas or merges to lose; flattening already happened when the file became a CSV. The remaining cost is the current CSV-path bug (`header_row` inert; `csv_skip` + line 1), which (a) fixes.

**Strongest argument against:** a permanent second ingest path (CSV vs snapshot) is the half-migrated state P5 is trying to leave. One file keeps that fork alive forever.

**What would change my mind:** the owner wants that series to grow formulas/merges, or is already willing to rebuild it as a Sheet for other reasons. Then (b), COS still does not write to Drive.

### D-3 — Cell notes/comments

**Recommend:** add `--with-notes` as **opt-in, default off**. Use it only on tabs the owner has named as comment-formula tabs. **Do not store note text in `books.db`.** At classify-time, a literal cell whose note looks like a formula (`^=`) becomes `origin=derived`, `presence=estimated` (or `derivation_kind=projection`). Delegate-facing artifacts redact digits in notes the same way `_redact_formula` does.

**Strongest argument against:** comments are free text; they can hold figures and identifiers; fetching them by default expands the privacy surface of `private/raw`. A regex "looks like a formula" will both miss and over-fire.

**What would change my mind:** a structure-only survey (no values) showing comment-formulas on more than a named handful of tabs, or the owner saying those comments are the only derivation record. Then default-on for snapshot, still never persisted as fact text.

### D-4 — Per-column fields in `layouts.schema.md`

**Recommend:** add per-column objects on the allow-list with **`letter`, `expected_label`, `role` (`value` / `key` / `derived` / `external` / `scratch`)**. The loader refuses a spec letter with no allow-list column. **Do not put `metric_id` in `layouts.json`.** Metric/account/grain binding already lives in the loader spec (`spec["columns"]`). Layout = what the sheet *is*; spec = what the store *does* with a letter. The join key is the letter. `expected_label` is what makes E4 real; `role` is what makes `derived_columns` / `external_links` structured instead of parallel lists.

**Strongest argument against:** two files then own the letter→meaning map (layouts role vs spec metric), and they can drift. Putting `metric_id` in the allow-list is the "single map" the v0.1 §7 "spec only selects letters" sentence wanted.

**What would change my mind:** a count of tabs with two specs selecting different metrics from the same letter (then spec-level metric_id is required) vs many specs repeating the same letter→metric pair (then move `metric_id` into layouts and thin the spec to a letter selection). I did not inspect `private/` specs, so I am **[unsure]** which world this corpus is; the split above is the conservative one given layouts hygiene (no account structure in the committed half, data half already personal).

---

*End of review. One file written; blueprints, store, and Drive untouched.*
