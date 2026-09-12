# Session handoff — 2026-09-11 (Roth, COS)

**Session:** `session-65f91fa9…` (started "Agent Team on 3081", resumed after the
WSL restart) · **Workspace:** `bag-end-venture` · **Status:** CLOSED — owner
returning to the stable :3080 instance · **Figures scrubbed** per house rule.

> The 2026-09-10 handoff (`docs/session-handoff-2026-09-10.md`) covers the
> pre-restart half: the Agent Team panel error root-cause, the producer/verifier
> pilot, and the Task #3 proposal. This file covers the second half and the close.

## What landed today

1. **`bagend.py sheets grid`** — native STRUCTURAL read (merges, formulas,
   formats; numeric literals inside formulas redacted by default). A values-only
   read cannot show a merged group band or a derived column; this is what made
   Task #3 settleable. `sheets errors [--all]` followed for migration defects,
   with 429 quota backoff.
2. **Task #3 CLOSED** — all 11 unresolved allow-list entries settled with the
   owner; `private/layouts/layouts.json` has **0 unresolved**. Entries written for
   `Inv Income`, `401k Contributions`, `Taxes`, `NEAR`, `Tax Rates`; exclusions
   ruled for `Buybacks` (worksheet), `Sheet1`/`Sheet2` (tabs deleted by owner),
   `2026 Data` (scratch), `Social Security Earnings` (derived — calculated table
   for Chart2), `VCA_PLAN` (duplicate of `Row Data`: 674 + 440 + 9 = 1,123).
   History: `private/layouts/task3-proposal-2026-09-10.md`.
3. **Blank semantics completed** (owner rulings): blank cell inside a live row =
   **0**; absent row/period = **not recorded**; pre-series label rows (Tax Rates
   2010–2014 before the 2015 series) = **not records**. Recorded in
   `layouts.json._cross_cutting.blank_cell_is_zero` and North Star invariant 4.
4. **xlsx→Sheets migration defects swept and CERTIFIED CLEAN** across all 13
   sheets (`sheets errors --all` → 0 error cells in every tab) after the owner's
   repairs. Defects D15–D18 filed in `private/defects/inventory.md`.
5. **Agent Teams trial verdict** — sandbox for independent verification, not the
   daily driver; re-trial at the first genuinely parallel job (Task #7) or the
   next dsh upgrade that aligns plugin and core. Full write-up:
   `~/Obsidian/AIML/dsh/dsh-agent-teams-experiment-2026-09-11.md`.
6. **Committed and pushed:** `b75ac23` on `main` (toolkit, schema spec, docs,
   ledger). Pre-commit gates: hygiene 2/2 clean, schema/loader harnesses ALL
   GREEN, `py_compile` OK.

## Open work (filed in `docs/TASKS.md`)

- **#19(a) first** — make `cmd_query` read-only (`file:…?mode=ro`). It is the only
  open item that protects `books.db`: today DDL persists (`DROP` destroys data)
  while DML rolls back on `close()`. Then (b) inspector blind spots — CSV header
  scorer counts numeric strings as labels, the `header unresolved` CLI warning is
  xlsx-only, xlsx `--header-row` applies workbook-globally; (c) `sheets._typed`
  rewriting integers in the 20,000–80,000 range into dates; (d) doc drift.
- **#18** — loader follow-through: consume `group_row`, `sub_header_row`,
  `first_data_row`, `skip_rows`, `derived_columns`, `external_links`, and emit
  `presence='zero_from_blank'`. Also settle the CSV header mechanism: today
  `header_row` is **inert** on CSV paths (`loader21` CSV branch uses `csv_skip` +
  line 1; only the xlsx branch reads `header_row`).
- **#7** — complete the trading-* allow-list for unlisted tabs (the natural
  Task #7-scale fan-out; re-trial checkpoint for Agent Teams).

## Environment notes

- Two `dsh web` instances shared `~/.dsh/sessions`: stable **:3080** (`web`
  profile) and the trial **:3081** (`teamlab`). **Never keep one session open on
  both** — the session lease is single-writer across processes, which is what
  produced `SessionAlreadyOwnedError` in the Agent Team panel. Use the panel only
  in a session the server you are on owns.
- Boot the trial from a plain terminal: `dsh --profile teamlab --port 3081 --no-open`
  (`dsh web --profile teamlab …` is invalid). Pre-trial config backup +
  `restore.sh` at `~/.dsh/backups/pre-teamlab-<timestamp>/`.
- Agent-team bundles are mounted **only** in the `teamlab` profile; on :3080 the
  teammate/task-board tools do not exist.
- **Harness limits — SUPERSEDED 2026-09-12; read this line, not the struck one
  below.** Workflow `agent()` children **can** use tools on the current build, and
  `subagent` accepts `provider`/`model`/`reasoning_effort` for all four flash
  routes (verified end to end). Both fan-out templates had their `DO NOT RUN YET`
  headers retired. See `tools/PANEL.md` §3 ("Delegation doors"), ledger #21, and
  `~/Obsidian/AIML/dsh/dsh-subagent-architecture-2026-09-12.md`.
- ~~Harness limit to remember: workflow `agent()` children cannot use tools on dsh
  0.1.5-rc.1 (tool-using child → null); teammates/subagents have no model
  override. Both fan-out templates carry the warning in their headers.~~
  Retired 2026-09-12. The **teammate** half still holds; the workflow half and the
  subagent half no longer do.

**Boundary note (logged, not silent):** `AGENTS.md` §5.4 keeps the Obsidian vault
read-only from this repo. The Agent Teams write-up was written to
`~/Obsidian/AIML/dsh/` on the owner's direct instruction (2026-09-11) — a
one-off, owner-directed exception, logged here per §5.6. No other vault path was
touched, and nothing financial was written.

## What survives / what dies

| Survives (disk) | Dies with the instance |
|---|---|
| This session's transcript + task board (`~/.dsh/sessions/…`) | the :3081 server and its URL token |
| All repo artifacts, including the Task #3 result in `private/` | live teammates (all idle) |
| The vault write-up and the ledger | write leases (released by the kernel on process death) |
