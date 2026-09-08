# tools/schema — books.db DDL

**Current: `books.sql` = v0.2.1 — RATIFIED by the three-leg panel (2026-09-07).**

- Round 1 (v0.2): semantics RATIFY-WITH-CHANGES · adversarial REJECT · purpose
  RATIFY-WITH-CHANGES — findings reconciled by the COS (convergence note:
  `.scratch/schema-review/v02/CONVERGENCE.md`), fixes implemented as v0.2.1.
- Round 2 (v0.2.1 re-verification, each leg re-executed its own probes):
  **CLEAN · CLEAN · CLEAN-WITH-NITS** — zero unresolved BLOCKER/MAJOR/MINOR
  findings; only nit-grade hardening noted. Leg reports and probe suites:
  `.scratch/schema-review/v02/`.

**Status of the store:** the DDL is ratified but **not yet applied**.
`private/books.db` still holds only quarantined pilot tables; wave-1 ingest
(Task #4) applies v0.2.1 to a fresh store after the loader gains the
batch/natural-key/supersede contract (blueprint §3).

- Blueprint: `docs/superpowers/plans/2026-09-07-schema-v0.2.md`
- Harnesses (synthetic fixtures, in-memory only): `.scratch/schema/v02_tests.py`
  (49 assertions) + `.scratch/schema/v02_1_tests.py` (panel-fix battery)
- Draft history: `.scratch/schema/books_schema_v0.1*.sql` (rejected v0.1)
