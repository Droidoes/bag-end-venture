# Bag End Data Toolkit

One consistent entrypoint for everything data: Drive extraction, structure
inspection, SQLite ingestion, and querying. **No more one-off scripts** —
if a command is missing, extend this toolkit rather than improvising.

```
tools/
  bagend.py            CLI entrypoint (all commands)
  bagend/
    config.py          paths, Drive folder/sheet IDs, aliases — EDIT HERE to add sources
    gws_client.py      gws CLI wrapper (auth wrinkle handled centrally)
    catalog.py         census + registry merge + search (the map of what exists)
    inspect.py         structure survey (tabs, headers, date ranges — no values)
    ingest.py          source files -> private/books.db with provenance
```

## The mental model

```
Google Drive (My Drive/My Info/Investment)   CANONICAL data, living sheets
        │  fetch / export (tools)
        ▼
private/raw/                                 exact source bytes, never edited
        │  ingest (provenance enforced)
        ▼
private/books.db (SQLite)                    queryable store, rebuildable
        │  query (SQL)
        ▼
analysis / memos / reports                   numbers with lineage or they don't count
```

- **Drive is custody.** The local DB is a cache — it can be dropped and
  rebuilt at any time from Drive.
- **private/ is gitignored.** Raw files and the DB may contain numbers;
  nothing under private/ is ever committed.
- **Every row is traceable.** Ingested tables carry `_source_path`,
  `_drive_id`, `_ingested_at` (and `_sheet`); `_ingest_log` records every
  load. A number without lineage fails the charter's honesty rule.

## Commands

All commands run from the repo root:

```bash
# 1. Census a Drive tree -> private/catalog.tsv  (~4 min; metadata only)
python3 tools/bagend.py catalog drive --root investment

# 2. Merge the owner's Homepage-DB registry (sheet name -> Drive ID)
cp "/mnt/c/Users/fangq/Documents/My Info/Misc/Homepage-DB/Tools/my-data-records.json" \
   private/my-data-records.json
python3 tools/bagend.py catalog merge-registry

# 3. Search the census
python3 tools/bagend.py catalog find "Social-Security"

# 4. Read a source (alias from config.py or raw Drive ID)
#    native Google Sheet  -> typed CSV dump (the sanctioned path for VALUES)
python3 tools/bagend.py sheets dump trading-2019 --tab Performance
#    ...and for LAYOUT work, read the same tab's STRUCTURE natively:
#    merges + formulas + formats, no export (structure only unless --with-values)
python3 tools/bagend.py sheets grid stats --tab "Inv Income" --max-rows 45
#    uploaded file (xlsx/pdf/csv) -> the original bytes, unchanged
python3 tools/bagend.py fetch <drive-file-id>
#    (`fetch` REFUSES native Sheets: use `sheets dump`; escape hatch exists
#     only for workbook-format preservation, never for analysis)

# 5. Inspect structure BEFORE designing a schema (never prints values)
python3 tools/bagend.py inspect private/raw/2019-Trading-Performance.xlsx --md

# 6. Ingest one tab into the store (append-only; provenance attached)
python3 tools/bagend.py ingest xlsx private/raw/2019-Trading-Performance.xlsx \
        Performance pnl_2019 --skiprows 0 --note "initial backfill"

# 7. Query (read gate: see "Store schema gate" below)
python3 tools/bagend.py query "SELECT * FROM _ingest_log"

# 8. Export the dashboard payload (defaults to the live store)
python3 tools/bagend.py export finpage
python3 tools/bagend.py export finpage --db private/books-shadow.db   # smoke a shadow
```

## Store schema gate — split by intent, not weakened

`loader21.assert_schema(conn, mode=...)` has two modes:

- **`mode="write"`** (load/ingest) — requires an **exact** `SCHEMA_VERSION` match. A
  loader writing into an older store is the dangerous case, and it stays refused.
- **`mode="read"`** (query/export) — also accepts the pre-migration whitelist in
  `loader21.READ_COMPATIBLE_SCHEMA_VERSIONS`, and prints a loud stderr warning
  naming the version. An unknown version is refused by both modes: the read set is
  a whitelist, never "anything".

Why the split exists: the live store is legitimately `v0.2.4` while the toolkit was
`v0.2.6`, and the live store **cannot** be rebuilt mid-migration — the shadow holds
only the first wave, so promoting it would drop cost basis, SSA, checking/card and
events. Without the split, the dashboard exporter simply broke. With it, reads keep
working and say plainly that they are reading pre-migration figures.

**The read entries are TEMPORARY.** Drop `"v0.2.5"` and `"v0.2.4"` at the P3 cutover
so reads become exact too — otherwise "compatible" quietly degrades into "any old
store may be read", which is not a gate at all.

A pre-migration read publishes a **pre-migration figure**: on `v0.2.4` the
`v_net_worth` view is the older definition, so its `total` still sums `copy` and
`error` rows and its `n_error` means `value_num IS NULL`. The exporter stamps the
schema it read, so a stale figure is traceable rather than silent.

## Conventions

1. **Aliases over IDs.** New well-known sources get an entry in
   `bagend/config.py` (`DRIVE_SHEETS` / `DRIVE_FOLDERS`) — never inline IDs.
2. **Inspect, then ingest.** Run `inspect` first; if the tab needs a
   `skiprows` or header gymnastics, that's a per-call flag or a small
   parsing function — it does not go into the generic ingester.
3. **Append-only.** Re-ingesting the same source adds rows with a fresh
   `_ingested_at`. Corrections happen as new rows (or an explicit, logged
   table rebuild), never as silent edits.
4. **Table naming.** Lowercase snake, source-family prefix:
   `pnl_2019`, `pnl_records`, `fi_401k_history`, `ss_earnings`,
   `spend_checking`, `nw_snapshot` …
5. **Raw files are sacred.** Never edit anything in `private/raw/`;
   re-fetch instead. The DB must always be reproducible from Drive + code.

## Known gws API traps (learned 2026-09-06)

1. **`files.download` returns metadata, not bytes.** Binary fetches must use
   `files.get` with `alt=media`; the plain download method answers with a JSON
   envelope (`partialDownloadAllowed`, …) and writes no file.
2. **`gws` refuses `-o` paths outside the current directory.** Fetch into the
   repo tree (`private/raw/`), never `/tmp`.
3. **A 0 exit code is not proof of success.** `_run_gws` now raises unless the
   output file exists and is non-empty — that check once let 19 failed fetches
   pass as successes.
4. **`/tmp` is not durable between harness tool calls.** Keep working files in
   `private/` or `.scratch/`.
5. **Never send batch stderr to `/dev/null`.** It converts a loud failure into
   a silent one; capture and print it.
6. **Never export a native Sheet to xlsx to analyze it.** Enforced in code:
   `fetch` refuses (use `sheets dump`), and `ingest xlsx` refuses any local file
   whose provenance row says `source_kind=native-google-sheet` +
   `obtained_via=files.export`. The `--allow-xlsx-export` escape hatch exists only
   for genuine workbook-preservation needs, never for parsing. This rule exists
   because exports manufactured three false "source defects" and made correct
   owner data look corrupt.
7. **Filename ≠ source identity.** `private/raw/_provenance.tsv` is the only
   authority on what a local file actually is.

## Sandbox note (agent sessions)

`gws` writes its OAuth token cache at `~/.config/gws`. In the DeepSeek
Harness sandbox that directory is read-only, so behaviour depends on the
token state: **reads succeed while the cached token is valid and covers the
needed scope** (`sheets tabs/dump`, `values get` work unaided); anything
that forces a token **fetch or refresh** (a missing-scope call, an expired
token) fails with "Failed to set permissions on token directory" — run such
calls with bash `sandbox_permissions="danger-full-access"`, or have the
owner re-auth from their terminal. Pure-local steps (inspect, ingest, query
after fetch) need no elevation.

## Three read paths — and which to use (charter v1.0.2)

| Source kind | Command | Result |
|---|---|---|
| **native Google Sheet — INGEST** | `sheets snapshot <alias> --tab NAME [--with-notes]` | the **structural artifact** (JSON): values **plus** formulas, merges, number formats, errors, spills and explicit blanks, with requested/returned bounds, tab extent, a truncation flag and a content hash |
| **native Google Sheet — layout** | `sheets grid <alias> --tab NAME` | **merges + formulas + formats** (JSON); no values unless `--with-values` |
| **native Google Sheet — ad-hoc/legacy** | `sheets dump <alias> [--tab NAME]` | per-tab **CSV**, typed values, used-range only — **not an ingest path** |
| **uploaded file** (xlsx/csv/pdf) | `fetch <alias>` | the original bytes, unchanged |

**Values are not structure.** `sheets dump` calls `values.get`, which returns
values only: a merged group band arrives as a label in its anchor cell, and a
derived column arrives as an ordinary number. Two independent survey legs on
2026-09-10 had to *infer* subtotal semantics and could not see that the columns
were formulas — the direct cause of the unresolved-header backlog (Task #3).
Use `sheets grid` whenever the question is "what IS this tab" rather than
"what does it say"; it reads the same sheet natively through
`spreadsheets.get(includeGridData)`, so the no-export rule is untouched.

**Ingest uses `sheets snapshot`, never `sheets dump`.** A values-only read cannot
tell a formula-derived cell from a measured one, so computed values would enter
the store indistinguishable from observations. The 2026-09-12 audit found 8 of 11
ingest specs reading tabs where derivation was pervasive for exactly that reason.
`snapshot` also asserts its own coverage: it records the requested range, the
returned bounds and the tab extent, and flags truncation — the loader refuses a
truncated artifact. A 2026-09-12 sweep that read an 80-row window while reporting
its counts as measurements understated the largest tab by nearly six times.

## Gate harnesses

`tools/tests/` holds the suite that must be green before anything lands (schema,
loader contract, snapshot writer). See `tools/tests/README.md`. They read the
authoritative `tools/schema/books.sql` rather than copied snapshots, and never
pin a version literal — both mistakes previously let a suite go stale and
silently stop gating.

Native Sheets are **read directly through the Sheets API**, not exported to xlsx.
The export path cost this project real diagnosis time — it injected ~1,000 blank
padding rows per tab, crashed on chartsheet/pivot-cache tabs, and re-inferred the
year on year-less text dates (correct data arrived looking corrupt). A live
example: `Summary!2015` dumps to **91 typed rows** (`2015-01-02` …), where the
xlsx export of the same tab reported ~1,000 rows and dates that looked like 2019.

`sheets tabs <alias>` lists grid tabs with row/column counts and **excludes**
charts/BI tabs, so the tab inventory is trustworthy before anything is read.

`fetch` on a native Sheet still works (`--as-xlsx`) when formulas/formatting must be
preserved exactly, but CSV dumps are the default for ingestion, and
they make provenance unambiguous — a native Sheet never appears on disk as a
`.xlsx` that could be mistaken for a deleted mirror.

## Layout config (personal data — lives outside this dir)

`tools/manifests/layouts.schema.md` is the committed **spec**; the populated
allow-list is `private/layouts/layouts.json` (gitignored), because tab names,
column labels and plan identifiers are personal data. `tools/` stays tooling.

## Extending

- New Drive command? Add it to `gws_client.py` (method-aware `_run_gws`
  already supports any `files.*` / `folders.*` method).
- New file format? Parser goes in `inspect.py` (survey) and/or
  `ingest.py` (load) with tests against a real file in `private/raw/`.
- Anything that can't be a general rule stays a documented per-source
  note in `docs/` — consistency beats cleverness.
