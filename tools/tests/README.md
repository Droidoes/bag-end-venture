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
| `blank_semantics_tests.py` | DM-2026-01 blank semantics: per-column `blank_means` (`zero` default / `not_applicable` writes no row), the per-column zero report, per-column `series_start`, `series_anchor_month` arming (declaration-driven — the `Deposit` shape arms with no grain on the mapping), the **anchored-blank guard staying non-vacuous at/after the start** (negative test), the report-only `SERIES SHAPE` detector, the `expected=0` escape hatch | 57 |
| `view_contract_tests.py` | Slice B read surface: `v_state_current` exposes `presence`/`origin`/`error_type`/`derivation_kind`; the five-class composition partition (`copy` > `error` > `presence`) sums to the row count; **additive totals exclude `copy` and `error`**; a `copy` is never summed with its source; `n_error` means `presence='error'`, not a null value | 122 |
| `column_shape_tests.py` | E5b column declarations: the allow-list's per-column `expected_label` + `role` are **asserted against the artifact header before any load** — a renamed header or a shifted frame is quarantined (`column-undeclared`, 0 rows, `partial`) instead of silently loading the wrong figures into the wrong metrics. Proves the gate can fail (fail-before: 6 passed / 38 failed on the pre-change loader) | 58 |
| `declared_role_tests.py` | COS ruling 2026-09-12: `role` is DECLARATIVE — `src_column.role` is written from the allow-list declaration, never computed from origin precedence, so the two can never silently diverge again; `origin`/`derivation_kind` keep the observed per-cell facts | 16 |
| `finpage_null_tests.py` | the exporter must survive a `NULL` additive total — `v_net_worth.total` is NULL for an all-copy/all-error group (Slice B excludes both), which previously raised `TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'`; also proves an all-NULL store exits with a clear message instead of crashing | 17 |
| `schema_read_mode_tests.py` | the store gate split by intent: a **write** requires an exact `SCHEMA_VERSION` (byte-identical refusal message), a **read** also accepts the pre-migration whitelist with a loud warning, and an unknown version is refused by **both** — the read set is a whitelist, not "anything". Also covers the `--db` URI construction (a naive `file:{path}` makes SQLite read `#` as a fragment and silently open an empty DB) | 90 |
| `shadow_diff.py` | P2 shadow-vs-live diff: every difference must be labelled *intended fix* / *bug* / *unknown*, with `zero_from_blank` **derived per column** from the declarations (never pre-declared — pre-declaring is what once let 298 fabricated zeros pass as "intended"). Exits non-zero on any unreviewed *unknown*. Needs `private/books-shadow.db`; SKIPs if absent | 3 |

```bash
for t in v02_tests v02_1_tests v021_loader_tests schema_parity loader_smoke snapshot_tests structural_loader_tests blank_semantics_tests view_contract_tests column_shape_tests declared_role_tests finpage_null_tests schema_read_mode_tests; do
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
