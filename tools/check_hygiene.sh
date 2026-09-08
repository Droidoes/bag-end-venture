#!/usr/bin/env bash
# Hygiene gate for committed files: run before anything lands in tools/ or docs/.
#   1. long digit runs (account numbers, IDs) — years are tolerated
#   2. institution / holding names from private/hygiene-blocklist.txt (word-boundary)
# Exits non-zero on any hit. private/ and .scratch/ are excluded (gitignored).
set -uo pipefail
cd "$(dirname "$0")/.."
BLOCK=private/hygiene-blocklist.txt
status=0

echo "[1/2] digit runs in prose/data (*.md/*.json/*.tsv/*.sql; code constants exempt)…"
hits=$(grep -rnI --include="*.md" --include="*.json" --include="*.tsv" --include="*.sql" -E "[0-9]{5,}" tools docs AGENTS.md README.md 2>/dev/null \
   | grep -vE ":[0-9]+:(19|20)[0-9]{2}" | grep -v "check_hygiene.sh" || true)
if [ -n "$hits" ]; then echo "  ✗ digit runs found:"; echo "$hits" | sed 's/^/      /'; status=1
else echo "  ✓ clean"; fi

echo "[2/2] blocklisted names in committed files (prose/data; code literals exempt)…"
[ -f "$BLOCK" ] || { echo "  ! no blocklist at $BLOCK (skipping)"; exit $status; }
while IFS= read -r term; do
  [ -z "$term" ] && continue
  case "$term" in \#*) continue;; esac
  hits=$(grep -rniEw --include="*.md" --include="*.json" --include="*.tsv" --include="*.sql" --include="*.html" -- "$term" tools docs 2>/dev/null | grep -v check_hygiene.sh || true)
  if [ -n "$hits" ]; then echo "  ✗ '$term':"; echo "$hits" | sed 's/^/      /'; status=1; fi
done < "$BLOCK"
[ $status -eq 0 ] && echo "  ✓ clean"
exit $status
