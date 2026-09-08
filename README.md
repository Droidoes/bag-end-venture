# bag-end-venture

The owner's personal-capital repo — household accounting, retirement planning,
and the personal investment book. **Method only: no real numbers are ever
committed here.**

- **Charter:** [`AGENTS.md`](AGENTS.md) — Roth, the household steward
  (three desks: Accounting · Retirement · Portfolio).
- **North Star:** [`docs/CODEBASE_OVERVIEW.md`](docs/CODEBASE_OVERVIEW.md) ·
  **Ledger:** [`docs/TASKS.md`](docs/TASKS.md).
- **Data lives in Google Drive** (canonical custody) and computes in
  `private/books.db` (SQLite, rebuildable, gitignored). The repo holds the
  schemas, tooling, and docs that move data safely.
- **Toolkit:** [`tools/README.md`](tools/README.md) — one entrypoint
  (`tools/bagend.py`) for Drive extraction, structure inspection, ingestion,
  and querying.
- **Team:** [`tools/PANEL.md`](tools/PANEL.md) + `tools/panel_routes.json` —
  flash-model fan-out for surveys and schema review; pro review is
  owner-initiated and post-hoc.
- **Financial page:** [`apps/finpage/BagEnd.html`](apps/finpage/BagEnd.html) —
  static retirement dashboard; one capability = one page, data connected
  locally via `tools/bagend.py export finpage` (Homepage-DB pattern — hosted
  page, local JSON, never committed).
- **Sibling repo:** `~/Droidoes/10x-learning-machine` (equity research; the
  Portfolio desk consumes its deliverables).

**Privacy:** personal financial figures, account numbers, and institution
identifiers never enter committed files, delegate prompts, or web tools.
`private/` and `.scratch/` are gitignored. `tools/check_hygiene.sh` gates every
commit.
