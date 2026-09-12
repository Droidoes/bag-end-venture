# Panel review prompt — structural pre-fetch artifact blueprint

**Convened by:** Joe (owner), in separate pro-model sessions — one session per reviewer.
**Artifact under review:** `docs/superpowers/plans/2026-09-12-structural-prefetch-v0.2.1.md`
— read **together with** `...-v0.2.md`, which v0.2.1 amends. v0.2 is the design;
v0.2.1 folds in the third review leg (E1–E8). **The pair is the current design.**
**Context only:** `...-v0.1.md` (the superseded design, kept for the record) and
`...-panel-review-prompt.md` (this file)
**Written:** 2026-09-12 · **Prepared by:** Roth (COS)

> **Version rule:** if a higher-numbered blueprint exists in this directory when
> you run, review **that** one and say which version you reviewed. This prompt was
> corrected once already: it originally pointed at v0.1, which two independent
> flash reviews had judged "fails as written" — re-reviewing a superseded version
> wastes the panel.

**Independence:** the COS chair (`deepseek-flash`) authored these blueprints and
the audit behind them, so it is **excluded** from this review (`tools/PANEL.md` §2).
Reviewers must not be the chair model.

---

## 1. What you are asked to do

Independently review a design blueprint before it is implemented. You are not
asked to approve it. You are asked to find where it fails — and, because the
design has already been through one review round, **the interesting question is
whether its fixes are right**, not whether the earlier holes exist.

## 2. Problem statement

The loader ingests **values-only CSV** produced by `bagend.py sheets dump`
(Sheets API → typed CSV). A structure-only audit of all **11** CSV-backed loader
specs found:

- **9 of 11** read tabs where formula-derived cells are pervasive — one tab is
  **97.8% formulas** (539 of 551 cells); another has 194 of 295; five tabs carry
  47–77 each, including live external quote formulas.
- A values-only CSV **cannot distinguish a derived cell from a measured one**, so
  computed values enter the store indistinguishable from observations.
- It also **cannot express merges**: a two-tier header appears as a label in the
  anchor cell with **empty siblings** — which already caused independent survey
  legs to agree on wrong layout readings (correlated error).

**Owner's standing ruling (2026-09-10, verbatim):** *"I think I have made clear
not to convert google sheet into cvs... it losses info in the process.. .trying
to parse the source directly if possible"*

**Owner's decision (2026-09-12):** make the **pre-fetch artifact structural** —
values **plus** formulas, merges and formats in one file — and have the loader
consume that instead of a values-only CSV.

## 3. Settled vs open

**Settled by the owner — do not re-litigate:** the structural-artifact direction;
and that `layouts.json` (the allow-list) is authoritative for layout semantics,
with a per-load override escape hatch.

**Open — judge v0.2's answer to each, and say whether it holds:**

> **v0.2.1 additionally adds E1–E8** — error cells represented in the artifact,
> `derivation_kind`, merge-resolution ordered *before* blank logic, load-time shape
> assertions, per-column allow-list fields, a provenance cross-check in the target
> flow, staleness scoped to read tabs, and corrected spec arithmetic. **Judge those
> too**; they are where the third leg's findings landed.

1. **The total presence function (v0.2 §D1).** v0.2 replaces the flat
   `formula → estimated` rule with two orthogonal facts — `origin`
   (`entered` / `copy` / `constant_formula` / `derived` / `external` / `key`) and
   `presence` (`measured` / `estimated` / `zero_from_blank` / `error`) — claimed to
   be **total** over cell states. Is it actually total? Which cell state is still
   unmapped? Is the `copy` rule (stored, declared duplicate, never summed with its
   source) enforceable? Is `external_links` overriding `kind` the right precedence?
2. **The schema extension (v0.2 §D2).** One CHECK value (`zero_from_blank`) plus
   one new column (`origin`), requiring a table rebuild in SQLite. Is that the
   minimum? Is `origin` the right *dimension*, and is its vocabulary right, or does
   this belong somewhere else entirely (layout evidence rather than fact rows)?
3. **The repaired join and refusal rules (v0.2 §D3).** Overrides are now legal
   (recorded, not refused); refusal is narrowed to three cases; `role:
   derived/scratch` entries must be explicitly acknowledged; tab patterns are
   expanded; failures are **quarantined** rather than blocking a batch. Does this
   close the holes without opening new ones — in particular, can a
   non-overridable field list be gamed, and is quarantine safe?
4. **Migration safety (v0.2 §D5).** P0 schema → P1 artifact (parity against the
   **source**, not the CSV; divergences classified *intended fix / bug / unknown*)
   → P2 loader behind a flag writing to a **shadow store** → P3 **atomic
   promotion** with the pre-promotion file kept as **rollback** → P4 per-column
   reconciliation → P5 CSV retirement. Is the promotion genuinely atomic, is the
   rollback real, and is the phase order safe?
5. **Verification sufficiency (v0.2 §D6/D7).** A total-function assertion, a
   merge-shadow test, an external-link precedence test, error-cell mapping, a
   `copy`-never-summed test, and a **coordinate-system audit** that re-derives
   `header_row`/`first_data_row`/`skip_rows` from the structural artifact and
   flags disagreements with the ratified numbers. What is still not covered?

## 4. Method

- **Form your own findings from v0.2 first.** Only then read the Appendix (§8),
  and report: findings you reached independently; findings you agree with;
  findings you **contradict**.
- Grade each finding `BLOCKER | MAJOR | MINOR | NIT` and name the section.
- Mark anything uncertain `[unsure]`. "I could not determine this" beats a
  confident guess.
- Convergence is graded `n/n` (load-bearing, must resolve) · `(n−1)/n` (strong
  consensus) · `1/n` (unique catch, still surfaced).

## 5. Boundaries — non-negotiable

- **Do NOT read anything under `private/`** — that is the owner's live financial data.
- **No financial values anywhere in your output.**
- **Read-only.** Write exactly one file: your feedback (§6). Do not modify the
  blueprint, the repo, the store, or any Drive file.

## 6. Where to leave feedback

Write your review to **the same directory as this prompt**:

```
docs/superpowers/plans/2026-09-12-structural-prefetch-review-<model>.md
```

Suffix the filename with your model name — e.g. `...-review-qwen3.8-max.md`,
`...-review-glm-5.3.md`, `...-review-gpt-5.6-sol.md`. If you reviewed a later
version, put that version in the filename too.

Suggested structure: **1.** verdict in one paragraph, naming the version reviewed
· **2.** findings table (`severity | §section | finding | what you would change`)
· **3.** your answer to each of the five open questions · **4.** disagreements with
the Appendix · **5.** the single change that would most improve the blueprint.

## 7. Decisions requested from the panel

The owner has four items to ratify but does not hold the technical context to
judge them, and **should not have to**. The panel is asked to **recommend an
answer for each**, so the owner ratifies a reasoned recommendation instead of
authoring a design. For each item give: your recommendation · the strongest
argument against it · what evidence would change your mind.

**D-1 — Schema extension** (v0.2 §D2, v0.2.1 §E2). Add the `presence` value
`zero_from_blank` plus columns `origin` and `derivation_kind`, requiring a table
rebuild. Is that the right shape and the minimum? Or do `origin` /
`derivation_kind` belong in *layout evidence* rather than on every fact row —
i.e. is this a schema question at all?

**D-2 — `fi_balances:over-time`.** It is a CSV **file** in Drive, not a Sheet, so
there are no formulas or merges to read. Either (a) keep it CSV-only and honour
`header_row` on the CSV path (needs nothing from the owner), or (b) the owner
re-creates it as a Google Sheet so it joins the structural path. **Note:** (b)
requires the owner to modify his own Drive; the COS may never write there.
Recommend (a) or (b), and say what (a) costs in accuracy.

**D-3 — Cell notes/comments.** The structural read pulls values, formulas, merges
and formats but **not** cell notes/comments. The owner has stated that in at least
one tab the formulas are stored in comments. Add `--with-notes`? Weigh completeness
against larger fetches and the fact that comments are free text that may carry
content we would then be storing.

**D-4 — Per-column fields in `layouts.schema.md`.** Letter-based addressing needs,
per column: `metric_id`, `expected_label`, `role` (value/key/derived/external).
The committed schema has none, so the proposed join has nothing to resolve
against. Is this the right mechanism, or is there a better way to bind a
spreadsheet column to a metric?

> Recommendations only. The owner ratifies; the panel does not decide for him.

## 8. Appendix — read only *after* forming your own findings

### 7a. What the first review round found, and how v0.2 answers it

| Round-1 finding | v0.2's answer |
|---|---|
| "No schema change" was false — the ratified blank rule (`zero_from_blank`) had no representation | §D2 — CHECK extension + `origin` column, carried by a new P0 |
| `formula → estimated` collapsed copy / constant-formula / deterministic / projection cases | §D1 — the total presence function |
| Merge shadows absent from `cells`; `merges` unused | §D1 — shadow inherits the anchor, never blank; vertical data merges flagged series-unsafe |
| §7's reasoned override was itself a "disagreement" rule 4 refused (self-deadlock) | §D3 — override ≠ disagreement; refusal narrowed to three cases |
| `(alias, tab)` insufficient identity; blanket refusal causes outages | §D3 — `(drive_id, sheet title)` + pattern expansion + quarantine |
| No shadow store, atomic promotion or rollback | §D5 — P2 shadow, P3 promotion + rollback |
| P1's "diff against the CSV" canonized the `_typed` serial→date bug | §D5 — parity against the source; divergences classified |
| T6's staleness check needed live Drive, contradicting offline ingest | §D6 — moved to the pre-fetch step |
| Decision 2 was not moot (`fi_balances` stays CSV) | §D4 — CSV rule (A) adopted for CSV-backed specs |
| Coordinate systems mixed with no audit gate | §D7 — new P4a coordinate audit |

### 7b. Known gaps v0.2 does **not** close — do not report these as novel

- `sheets.py` does **not** read cell **notes/comments**, and the owner has said
  some formulas live in comments. An owner decision is pending on `--with-notes`.
- **Task #19(c)** — `sheets.py:94` rewriting integers in 20,000–80,000 into dates —
  is a separate open task; v0.2 only refuses to inherit it.
- The per-column derived-vs-measured reconciliation for the 9 inadequate specs
  (P4) is deliberately deferred and owner-reviewed before promotion.
- `fi_balances:over-time` remains on CSV because it is a Drive CSV file with no
  sheet behind it; converting it is an owner decision.
- **`AGENTS.md` and the `bag-end-data` / `bag-end-team` skills still describe the
  values-only path as the native read.** A charter amendment (v1.0.2) is pending
  owner ratification; it is out of scope for this blueprint.
