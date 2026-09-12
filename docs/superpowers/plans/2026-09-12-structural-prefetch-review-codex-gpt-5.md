# Independent panel review — structural pre-fetch blueprint

**Reviewer:** Codex / GPT-5
**Version reviewed:** `2026-09-12-structural-prefetch-v0.2.md` together with
`2026-09-12-structural-prefetch-v0.2.1.md`
**Verdict:** **FAILS AS WRITTEN — revise before ratification.**

## 1. Verdict

The structural-artifact direction is correct, and v0.2/v0.2.1 repairs most of
v0.1's conceptual omissions. The pair is nevertheless not safe to implement.
Its advertised total classifier is not total; its categories overlap; error and
copy states have no complete store contract; the current loader will skip some
semantic reclassifications when the effective value is unchanged; P3 promotes
before P4's owner-reviewed reconciliation; and neither tab-scoped staleness nor
the promised provenance cross-check is implementable from the metadata currently
specified. A consolidated v0.3 should close these points before the owner is
asked to ratify schema or migration decisions.

## 2. Findings

| Severity | Section | Finding | What I would change |
|---|---|---|---|
| **BLOCKER** | D1, D2, E1 | The presence function is not total over ingestible cell states. A formula that evaluates to an empty value, an explicitly entered empty string, and a formula-key cell have no valid `(origin, presence, stored value)` contract. D1 says presence does not apply to keys although `presence` is `NOT NULL`. E1 maps an error but does not say how it satisfies `fact_state`'s exactly-one-of-`value_num`/`value_text` CHECK (`tools/schema/books.sql:178-200`). | Define an ordered classifier over the complete Sheets `ExtendedValue` state space, with an explicit conservative `unknown_formula` fallback. State whether keys are merely row addressing and therefore not fact rows. For errors, either store a canonical error token in `value_text`, or amend the value CHECK and add a typed error field. Add a composite allowed-state CHECK, not independent enums alone. |
| **BLOCKER** | D1, D2, E2 | `origin` is not one dimension. `external`, `copy`, `key`, `constant_formula`, and `derived` can overlap. Likewise, `derivation_kind` is not mutually exclusive: an aggregate can be deterministic and can also depend on derived cells; a lookup is not necessarily a projection. "External overrides kind" makes trust conservative but erases the observed cell kind and can hide a copy relation. | Preserve orthogonal evidence: entered kind (`literal`/`formula`/`blank`), lineage relation (`direct`/`copy`/`external`), fact role (`key`/`value`), and optional formula classification. If the store remains denormalized, publish a precedence table plus every allowed pair and retain `copy_of`/external evidence separately. Unknown formulas must conservatively remain derived rather than fail classification. |
| **BLOCKER** | D1 copy rule, D2, D6/T13 | The copy rule is not enforceable. The blueprint says the source cell is recorded, but D2 adds no source-coordinate or copy-edge field; E5's column role vocabulary does not include `copy`; and the current published views do not expose `presence` or the proposed origin. `v_net_worth` sums every numeric current row and detects errors through null numeric values, not `presence` (`tools/schema/books.sql:484-509, 568-583`). | Persist an auditable `copy_of` relation to a canonical source metric/cell, make copy a declared per-column role, and define the default query surface that excludes duplicate copies from additive totals. Test at the consumer/view layer, not only inside the loader. Merge shadows must never become duplicate facts merely because they inherit header semantics. |
| **BLOCKER** | D5 P2/P3 | A shadow copied from the current store can silently retain the old semantic label. `load_state_spine` hashes identity plus effective value and skips an equal current hash before inserting (`tools/bagend/loader21.py:316-335`). `presence`, `origin`, and `derivation_kind` are not part of that decision. An unchanged effective value can therefore remain `measured` even when the structural path proves it derived, copied, external, blank-imputed, or erroneous. | Either rebuild all affected slices into an empty/new-schema shadow, or make same-natural-key semantic changes supersede and insert even when the value hash is unchanged. Add regression cases for unchanged values whose semantic classification changes. |
| **BLOCKER** | D5 P3/P4; E8 | The phase order promotes the shadow in P3 and performs the owner-reviewed per-column reconciliation in P4. That contradicts the earlier gate that no unreconciled classification reaches the live store. Corrected spec arithmetic does not repair the ordering. | Move reconciliation, coordinate audit, provenance validation, and all consumer tests before promotion. Promotion must be the final gate after the owner accepts the reconciliation report. |
| **BLOCKER** | D5 atomic promotion/rollback | "File swap" is not yet an atomic SQLite protocol. A byte-copy of a live database may be inconsistent; WAL/SHM sidecars and open readers make replacement unsafe; and rolling back the data file may leave code expecting the new schema. | Specify shadow creation with SQLite's backup API or a clean rebuild; close writers; checkpoint or avoid WAL sidecars; run foreign-key and integrity checks; fsync the shadow; use same-filesystem `os.replace`; reopen and smoke-test; retain a checksummed rollback file; and document code/schema rollback compatibility. Add crash/fault-injection tests at each cutover boundary. |
| **MAJOR** | Artifact schema, D1, E3/E4 | The artifact does not define a trustworthy ingestion rectangle. The existing reader defaults to a bounded range, omits empty cells, and reports the requested range rather than a proved used extent (`tools/bagend/sheets.py:181-255`; CLI defaults at `tools/bagend.py:307-314`). Without explicit coverage and a live-row predicate, a missing coordinate can mean blank, truncation, or a row beyond the response. Merge anchors may also sit outside a clipped range. | Include `sheet_id`, grid dimensions, exact requested range, returned bounds, and a truncation flag/hash. Define a live row from the mapped key plus row-shape rules. Require the ingest rectangle to cover every mapped/header/merge coordinate and refuse truncated artifacts. Use merge inheritance only to construct headers; data merges require explicit anchor-only or fan-out semantics. |
| **MAJOR** | Artifact schema, P1 parity | "Formats" is underspecified for typed values. The existing grid reader requests only `userEnteredFormat.numberFormat` and retains only its type, while inherited/effective formatting and the pattern can determine whether a numeric effective value is a date (`tools/bagend/sheets.py:197-207, 235-243`). | Store both the relevant entered and effective number-format type/pattern, and specify the value-decoding algorithm. Test inherited date formats, formula-produced dates, booleans, strings, errors, and plain integers in date-like numeric ranges. P1 must prove typed-value parity, not JSON-token equality. |
| **MAJOR** | D3/E6 provenance and identity | E6 cannot perform the stated cross-check against today's provenance format. `_provenance.tsv` records local path and Drive object metadata, but not alias, tab, `sheet_id`, artifact hash, or artifact version (`tools/bagend.py:65-84`). Parsing alias/tab back out of the filename would reinstate the forbidden filename-as-identity rule. `(drive_id, title)` also treats a rename as a new tab while omitting Sheets' stable `sheetId`. | Add a provenance record keyed by artifact hash with `drive_id`, `sheet_id`, exact tab title, alias, artifact version, range, and fetch timestamp. Join primarily on `(drive_id, sheet_id)` and validate title/alias as expected metadata. Define how duplicate/stale provenance rows are resolved. |
| **MAJOR** | D6/T6, E7 | Tab-scoped staleness is not available from the proposed `drive_modified`: Drive's timestamp is file-wide, and Sheets `SheetProperties` provides no per-tab modification timestamp. E7 therefore states a policy the selected primitive cannot implement. There is also a read race if Drive metadata changes during the Sheets fetch. | Prefer a fresh artifact for each load. For cached artifacts, either conservatively invalidate all relevant tabs when file `modifiedTime` changes, or re-fetch the target tab and compare a canonical content/structure hash. Read workbook metadata before and after fetch and accept only an unchanged version window. |
| **MAJOR** | D3/E5 quarantine and overrides | Quarantine is safe only if promotion semantics say what happens to the quarantined slice. A copied shadow may carry stale rows forward; a rebuilt shadow may omit them. Either can be acceptable, but silently promoting a mixed-vintage store is not. The non-overridable set is also gameable if an entry declares its own protection, and a reason string is not authorization to bypass an owner-ratified layout. | Define required vs optional specs, carry-forward vs omission, visible stale/quarantine state, and the batch completeness threshold for promotion. Put the closed non-overridable field set in code/schema rather than in each entry. Require an explicit decision reference or operator flag for a layout override, and audit old/new values. |
| **MAJOR** | E2 classifier | Static formula classification needs a real parser and dependency graph. Regex/function-name heuristics will misclassify named ranges, sheet-qualified references, array formulas, volatile functions, and formulas that combine aggregate, external, and chained dependencies. | Specify an AST-based conservative classifier. Make `unknown` a valid derivation class and fail toward non-measured semantics. Prove the classifier against a corpus of formula shapes before making `derivation_kind` a schema commitment. |
| **MINOR** | D7/P4a | Re-deriving coordinates is useful as an audit, but an heuristic disagreement must not silently supersede the owner-ratified allow-list. "Re-derive" and "authoritative" otherwise pull in opposite directions. | Treat the audit as a shape assertion: agreement passes; disagreement quarantines and produces evidence for owner review. It never mutates or overrides the allow-list. |
| **MINOR** | Document shape | v0.2 calls itself a delta from v0.1 while also superseding it; v0.2.1 is a second delta. An implementer must reconcile three documents to construct one contract, and some amendments never update the artifact schema or phase table they alter. | Publish one consolidated v0.3 with one normative artifact schema, classifier, join contract, phase order, and test matrix. Keep earlier versions only as history. |

## 3. Answers to the five open questions

### 3.1 Total presence function

It is not total. At minimum, these states remain unresolved or contradictory:

- formula with no effective value or an empty-string result;
- explicitly entered empty string versus a genuinely absent cell;
- formula used as a row key despite `presence NOT NULL`;
- error cell with no legal fact value under the current CHECK;
- formula that cannot be parsed or falls into multiple derivation classes;
- merge shadow in a data range, where inheriting the anchor as a fact would
  duplicate data.

The copy rule is not enforceable without a persisted source edge and a
copy-aware consumer contract. `external_links` should conservatively force the
trust/presence outcome, but it should not erase the cell's observed kind or its
copy relation. Resolve merges before blank classification, but propagate merged
labels for header construction only; ingest data anchors once unless the
allow-list explicitly defines different semantics.

### 3.2 Schema extension

`zero_from_blank` must be added to `presence`. Row-level origin evidence also
belongs with the fact because formula/literal/blank/error state can vary within
one column; the per-column allow-list is an expectation and mapping contract,
not proof of each cell's observed state.

The proposed schema is nevertheless neither sufficient nor demonstrably
minimal. `derivation_kind` is premature as a single enum until its categories
are exclusive and its classifier is specified. Error storage, source A1, and
copy lineage are more immediately necessary. My preferred shape is a small,
queryable fact classification on `fact_state` plus normalized cell-lineage
evidence keyed to the fact, with composite validity constraints. Do not put
row-varying observed origin solely in layout evidence.

### 3.3 Join, overrides, refusal, quarantine

The stronger identity and pattern expansion are improvements, but use stable
`sheet_id` as well as title. Pattern expansion must refuse zero, multiple, or
colliding matches. The non-overridable field set must be fixed by the schema or
loader, not self-declared by the same entry it protects.

Quarantine is safe only with explicit promotion rules. A required spec with no
prior valid slice should block promotion. A previously valid optional slice may
be carried forward only if the store exposes that it is stale/quarantined and
the batch report cannot be mistaken for a fully current rebuild. Overrides need
an explicit operator action and decision reference; logging a reason alone is
not enough.

### 3.4 Migration safety

The migration is not safe as ordered. P0 is ambiguous about whether the live
store is rebuilt before a shadow exists; P2's copied shadow interacts badly with
the current equal-hash skip; P3 promotes before P4; and the file-swap and
rollback protocol omits SQLite connection, journal, durability, and code/schema
compatibility details.

The safe order is: define and test schema → build artifact → create shadow
safely → migrate affected slices → run provenance/shape/coordinate/semantic
reconciliation → owner accepts the report → run full consumer and integrity
tests → close all database users and atomically promote → reopen smoke test →
retain a checksummed rollback package.

### 3.5 Verification sufficiency

The proposed tests are necessary but not sufficient. Add:

- exhaustive classifier/property tests over literal, boolean, empty, formula,
  formula-empty, error, unknown-formula, key, external, copy, and merge states;
- database CHECK tests for every allowed and forbidden state pair;
- a same-value semantic-reclassification regression against the current hash
  skip path;
- query/view tests proving copies are never double-counted and errors/estimated
  components stay visible;
- range/truncation and merge-anchor-outside-range tests;
- effective/inherited format and typed-date tests;
- stable sheet identity, provenance hash mismatch, rename, and pattern-collision
  tests;
- pre/post-fetch mutation-race tests;
- quarantine tests for both a fresh rebuild and carry-forward shadow;
- SQLite crash/fault-injection tests around shadow creation and cutover;
- notes redaction and opt-in scope tests if notes are added.

## 4. Appendix comparison

### Findings reached independently and findings agreed with

I agree with the Appendix's round-one diagnosis: the blank rule requires a
schema change; flat formula-to-estimated mapping loses semantics; merges must be
resolved before blanks; override and disagreement are not synonyms; CSV cannot
be parity canon; live staleness belongs outside offline load; the CSV-backed
source still needs a CSV rule; and coordinates need an audit gate.

I also agree with the known-gap list: notes remain open; the numeric-to-date
rewrite is a separate hardening task; per-column reconciliation is a deliberate
owner gate; the born-as-CSV source cannot gain sheet structure by wishful
thinking; and charter/docs drift must be handled separately.

### Findings I contradict or regard as not yet closed

- E1 makes the artifact capable of naming an error but does not close the
  store-level error representation.
- E2 adds vocabulary without making it exclusive, total, or mechanically
  classifiable.
- E5b does not supply the copy-source relation needed by D1's anti-double-count
  rule.
- E6 promises fields the current provenance authority does not contain.
- E7 cannot derive tab-level freshness from a file-level timestamp.
- E8 corrects counts but leaves promotion before reconciliation.
- D5's "atomic promotion" and "rollback" are desired properties, not yet an
  executable protocol.

One terminology correction matters for D-3: a Sheets cell **note** is a
`CellData.note` field and can be included in `spreadsheets.get`; threaded Drive
**comments** are a separate resource, and their editor anchors are opaque to the
Drive API. The blueprint should not promise one `--with-notes` switch captures
both. See the official [Sheets CellData reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells)
and [Drive comments guide](https://developers.google.com/workspace/drive/api/guides/manage-comments).

## 5. Recommendations on the four owner decisions

### D-1 — Schema extension

**Recommendation:** Do **not** ratify the current `origin` +
`derivation_kind` shape. Ratify the need for `zero_from_blank` and row-level
origin/lineage, then require v0.3 to define error storage, source/copy lineage,
exclusive categories, allowed state pairs, and consumer behavior before fixing
the final columns. Keep row-varying evidence out of static layout-only metadata.

**Strongest argument against:** delaying the schema delays the structural path,
and a nullable `derivation_kind` column is cheap to add during an already-required
rebuild.

**Evidence that would change my mind:** an executable classifier specification
and property-test matrix showing every Sheets cell state maps to exactly one
legal stored representation, plus a query contract that uses the added fields
correctly.

### D-2 — CSV-backed source

**Recommendation:** Choose **(a)**: keep the born-as-CSV source on a CSV path and
honor `header_row` there. Re-creating it as a Sheet would not recover formulas,
merges, or types that never existed in the file and would require an owner-side
custody change. The accuracy cost is a second parser with weaker type/format
evidence and more header-drift risk; mitigate that with provenance hashes,
explicit encoding/dialect, `header_row`, expected labels, and row-shape tests.

**Strongest argument against:** one structural path is operationally simpler
than permanent dual ingestion paths and gains richer validation for future
edits.

**Evidence that would change my mind:** the owner intends to maintain this data
as a native Sheet going forward, or the CSV contains irreducible type ambiguity
that affects mapped facts.

### D-3 — Cell notes/comments

**Recommendation:** Add an opt-in `--with-notes`, scoped by allow-list to the
specific tabs/columns where notes are declared semantically relevant. Store
notes only in the private artifact/evidence layer; do not copy arbitrary note
text into fact rows. Structure-only output should emit only note presence or a
redacted formula shape. Treat threaded comments as a separate, currently
unsupported source unless a later requirement justifies the Drive Comments API.

**Strongest argument against:** opt-in scope can omit a load-bearing note and
therefore undermine the completeness goal; fetching all cell notes is simpler.

**Evidence that would change my mind:** a source census showing relevant formulas
can occur in arbitrary notes outside declared columns would favor fetching all
notes into the private artifact, with stricter redaction and retention controls.
Conversely, a census proving no mapped cell relies on notes would justify
deferral.

### D-4 — Per-column allow-list fields

**Recommendation:** Ratify per-column bindings. In a source-read-only system,
letter + expected composite header + `metric_id` is the simplest workable
binding. Strengthen the proposal: validate post-merge composite labels; include
`copy` in role semantics; add `copy_of`/external lineage where applicable;
define label normalization and collision refusal; and require exact coverage of
every spec-selected column. The allow-list declares expected semantics; the
artifact proves observed cell state.

**Strongest argument against:** column letters are positional and brittle under
insertions, while label-driven resolution can survive moves.

**Evidence that would change my mind:** frequent column reordering in the live
sources, or owner permission to add stable developer metadata to Sheets, would
justify a stable-ID or constrained label-resolution design instead.

## 6. Single highest-leverage change

Publish one consolidated **v0.3 executable contract** before ratification. It
should contain the complete artifact JSON schema, ordered total classifier and
legal state table, stable identity/provenance record, copy/error/query contract,
quarantine semantics, and one migration sequence in which reconciliation and
all verification precede a WAL-safe atomic cutover. That one rewrite would turn
the current collection of good corrections into an implementable system.
