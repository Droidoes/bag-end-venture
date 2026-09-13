# Gate harnesses

The verification suite that must be green before anything lands in `tools/` or
`docs/`. Run every one from the **repo root**.

| Suite | Covers | Assertions |
|---|---|---|
| `v02_tests.py` | schema: identity model, precedence, guards, assumption register | 49 |
| `v02_1_tests.py` | schema: post-reconciliation fixes | 22 |
| `v021_loader_tests.py` | loader contract: spine, SSA, checking/card, holdings | 30 |
| `schema_parity.py` | v0.2.5 DDL: new columns + CHECKs, presence vocabulary, the **two zeros hashing differently**, error rows via `value_text`, the 24-combination SQL-vs-loader legal-pair equality, rebuilt-vs-fresh parity | 8 |
| `loader_smoke.py` | loader: origin/presence resolution, hash contents, illegal-pair refusal, column-grain precedence | prints `LOADER SMOKE OK` |
| `snapshot_tests.py` | P1 structural snapshot: bounds/truncation, kinds, formats, spill, notes, date-typing hazard | 95 |
| `structural_loader_tests.py` | P2 structural reader: §4 classifier totality, merge/spill rules, allow-list join, coverage, E4 shape quarantine, src_column, legal pairs | 42 |
| `blank_semantics_tests.py` | DM-2026-01 blank semantics: per-column `blank_means` (`zero` default / `not_applicable` writes no row), the per-column zero report, per-column `series_start` (a blank before the declared start contributes nothing; the **anchored-blank guard stays non-vacuous at/after it** — negative test), the report-only `SERIES SHAPE` detector, and the `expected=0` escape hatch | 42 |

```bash
for t in v02_tests v02_1_tests v021_loader_tests schema_parity loader_smoke snapshot_tests structural_loader_tests blank_semantics_tests; do
  python3 tools/tests/$t.py || echo "FAILED: $t"
done
python3 tools/tests/shadow_diff.py   # P2 shadow-vs-live (needs private/books-shadow.db; SKIPs if absent)
bash tools/check_hygiene.sh
```

## Rules these harnesses follow

1. **One source of truth for the schema.** They read `tools/schema/books.sql`
   directly. They previously read copied snapshots under `.scratch/`, which went
   stale — one carried a v0.2.1 copy and a hardcoded `"expected v0.2.4"` string,
   so it silently stopped gating anything. `old_books_v0.2.4.sql` is the sole
   deliberate exception: `schema_parity.py` needs the *previous* schema to compare
   a rebuilt table against a freshly created one.
2. **Never pin a version literal.** Read it (`loader21.SCHEMA_VERSION`) so a
   schema bump cannot silently disable a suite.
3. **Synthetic fixtures only.** No real account numbers, institution names, or
   holdings. These files are committed, and the hygiene gate does **not** scan
   `.py` — so personal data in a harness would pass the gate and land in git.
   Sanitised 2026-09-12 before this directory was tracked.
4. **Offline.** No network, no Drive. `snapshot_tests.py` is socket-guarded; a
   passing offline battery is *not* proof that an API call works — reader changes
   need a live smoke call too.
