#!/usr/bin/env bash
# Hygiene gate for committed files: run before anything lands in tools/ or docs/.
#   1. long digit runs in prose/data (account numbers, IDs) — years tolerated
#   2. institution / holding names in prose/data (word-boundary, from blocklist)
#   3. .py files: account-shaped digit runs (FAIL) + blocklist names
#      (FAIL in test fixtures; WARN in operational code) — added 2026-09-12
# Exits non-zero on any FAIL. private/ and .scratch/ are excluded (gitignored).
set -uo pipefail
cd "$(dirname "$0")/.."
BLOCK=private/hygiene-blocklist.txt
status=0

echo "[1/4] digit runs in prose/data (*.md/*.json/*.tsv/*.sql; code constants exempt)…"
hits=$(grep -rnI --include="*.md" --include="*.json" --include="*.tsv" --include="*.sql" -E "[0-9]{5,}" tools docs AGENTS.md README.md 2>/dev/null \
   | grep -vE ":[0-9]+:(19|20)[0-9]{2}" | grep -v "check_hygiene.sh" || true)
if [ -n "$hits" ]; then echo "  ✗ digit runs found:"; echo "$hits" | sed 's/^/      /'; status=1
else echo "  ✓ clean"; fi

echo "[2/4] blocklisted names in committed prose/data (code literals exempt)…"
[ -f "$BLOCK" ] || { echo "  ! no blocklist at $BLOCK (skipping)"; exit $status; }
while IFS= read -r term; do
  [ -z "$term" ] && continue
  case "$term" in \#*) continue;; esac
  hits=$(grep -rniEw --include="*.md" --include="*.json" --include="*.tsv" --include="*.sql" --include="*.html" -- "$term" tools docs 2>/dev/null | grep -v check_hygiene.sh || true)
  if [ -n "$hits" ]; then echo "  ✗ '$term':"; echo "$hits" | sed 's/^/      /'; status=1; fi
done < "$BLOCK"
[ $status -eq 0 ] && echo "  ✓ clean"

# ---------------------------------------------------------------- .py coverage
# Why this exists: on 2026-09-12 the gate harnesses were promoted into version
# control, and screening by hand (because this gate did not look at .py at all)
# found real institution names and a real-format CUSIP sitting in a test fixture.
# A .py file was a blind spot in a gate whose whole job was to keep exactly that
# out of git.
#
# Two deliberate calibrations, so the rule is usable rather than noisy:
#   * digit runs: threshold 8, not 5. Measured on the real tree, 5+ matches 34
#     legitimate lines (serial numbers, grid sizes) and 7+ still matches 1; 8+ is
#     the first threshold that is clean while still covering account-number
#     length. Hex/hash context and 0x literals are excluded.
#   * blocklist names: FAIL inside tools/tests/ (fixtures must be synthetic — a
#     real name there has no purpose) but only WARN in operational code, where
#     institution names are functional identifiers (parser keys such as
#     `if parser == "chase"`, statement-format probes). Renaming those is a
#     behaviour change and does not belong in a hygiene fix.
echo "[3/4] .py files: account-shaped digit runs (8+) and blocklist names…"
py_digits=$(grep -rnE --include="*.py" "[0-9]{8,}" tools 2>/dev/null \
   | grep -vE "[0-9a-fA-F]{24,}|0x[0-9a-fA-F]+|check_hygiene.sh" || true)
if [ -n "$py_digits" ]; then
  echo "  ✗ account-shaped digit runs in .py:"; echo "$py_digits" | sed 's/^/      /'; status=1
else echo "  ✓ no 8+ digit runs in .py"; fi

if [ -f "$BLOCK" ]; then
  warn=0
  while IFS= read -r term; do
    [ -z "$term" ] && continue
    case "$term" in \#*) continue;; esac
    fx=$(grep -rniEw --include="*.py" -- "$term" tools/tests 2>/dev/null || true)
    if [ -n "$fx" ]; then
      echo "  ✗ '$term' in a test fixture (fixtures must be synthetic):"
      echo "$fx" | sed 's/^/      /'; status=1
    fi
    op=$(grep -rniEw --include="*.py" -- "$term" tools 2>/dev/null | grep -v "^tools/tests/" || true)
    if [ -n "$op" ]; then
      [ $warn -eq 0 ] && echo "  ! WARN — blocklisted names in operational .py (not a failure; see the calibration note above):"
      echo "$op" | sed 's/^/      /'; warn=1
    fi
  done < "$BLOCK"
  [ $warn -eq 1 ] && echo "      (operational identifiers — review, but do not rename blindly)"
  [ $status -eq 0 ] && echo "  ✓ no blocklisted names in test fixtures"
fi

# ------------------------------------------------- account-fragment patterns
# Added 2026-09-12 after the owner flagged a card "suffix 5679" sitting in a
# loader docstring. That class -- a partial account identifier in prose -- is
# below every digit threshold above (four digits), so no numeric rule could ever
# catch it. These patterns are anchored on the *phrasing* that introduces a
# fragment, which is why the rule is narrow: measured against the whole tree it
# flags exactly one line, the one that prompted it.
#   x{2,}[0-9]{4,} is deliberately lowercase-x only: '*{2,}' collides with
#   markdown bold (every '**2026-...' heading) and produced ~40 false positives.
echo "[4/4] account-fragment phrasing (suffix/ending-in/last-4/masked/acct #)…"
frag=$(grep -rniE --include="*.py" --include="*.md" --include="*.json" --include="*.tsv" --include="*.sql" --include="*.html" \
  "(suffix|ending in)[^a-z0-9]{0,3}[0-9]{2,}|last[ -]?4[^a-z0-9]{0,3}[0-9]{2,}|x{2,}[0-9]{4,}|(acct|account)[^a-z0-9]{0,3}#[^a-z0-9]{0,3}[0-9]" \
  tools docs AGENTS.md README.md 2>/dev/null | grep -v check_hygiene.sh || true)
if [ -n "$frag" ]; then
  echo "  ✗ account-fragment-looking text (personal data — remove it):"
  echo "$frag" | sed 's/^/      /'; status=1
else echo "  ✓ clean"; fi

exit $status
