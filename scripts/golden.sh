#!/usr/bin/env bash
# Per-fixture golden snapshot harness.
#
# Usage:
#   scripts/golden.sh generate <pykrete-binary>   # regenerate all goldens
#   scripts/golden.sh check <pykrete-binary>      # diff each fixture vs its golden
#
# Each annotated cross-codebase/<donor>/.../<file>.pyk has a sibling
# <file>.golden.json. CI calls `check`; releases call `generate` deliberately.
#
# Normalization (applied to both actual and stored golden):
#   - strip top-level `version` (changes per pykrete release)
#   - rewrite each diagnostic's `file` to a repo-relative path
# `schemaVersion` is kept — a bump there IS a regression contract change.

set -euo pipefail

MODE="${1:-}"
PYKRETE="${2:-}"

if [ -z "$MODE" ] || [ -z "$PYKRETE" ]; then
  echo "usage: $0 {generate|check} <pykrete-binary>" >&2
  exit 2
fi
if [ ! -x "$PYKRETE" ]; then
  echo "error: $PYKRETE is not executable" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

normalize() {
  jq --arg root "$REPO_ROOT/" '
    del(.version)
    | .diagnostics |= map(.file |= sub("^" + $root; ""))
  '
}

fixtures=$(find cross-codebase -path "*/annotated/*" -name "*.pyk" -type f | sort)
total=0
fails=0

while IFS= read -r fixture; do
  total=$((total + 1))
  golden="${fixture%.pyk}.golden.json"
  # pykrete check exits non-zero when diagnostics are present; that's
  # expected here (we want to capture the JSON either way). Suppress so
  # `set -e` doesn't terminate the loop.
  actual=$("$PYKRETE" check --format json "$fixture" 2>&1 || true)
  actual_norm=$(printf '%s' "$actual" | normalize)
  case "$MODE" in
    generate)
      printf '%s\n' "$actual_norm" > "$golden"
      echo "  wrote $golden"
      ;;
    check)
      if [ ! -f "$golden" ]; then
        echo "MISSING GOLDEN: $golden" >&2
        fails=$((fails + 1))
        continue
      fi
      golden_norm=$(normalize < "$golden")
      if ! diff -u <(printf '%s\n' "$golden_norm") <(printf '%s\n' "$actual_norm") > /tmp/golden-diff.$$; then
        echo "REGRESSION: $fixture" >&2
        cat /tmp/golden-diff.$$ >&2
        rm -f /tmp/golden-diff.$$
        fails=$((fails + 1))
      else
        rm -f /tmp/golden-diff.$$
      fi
      ;;
    *)
      echo "unknown mode: $MODE" >&2
      exit 2
      ;;
  esac
done <<< "$fixtures"

echo
echo "$MODE: $total fixture(s) processed, $fails failure(s)."
if [ "$fails" -ne 0 ]; then exit 1; fi
