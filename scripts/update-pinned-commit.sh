#!/usr/bin/env bash
# Bump a donor's pinned upstream commit.
#
# Usage:
#   scripts/update-pinned-commit.sh <donor> <new-sha>
#
# This is a thin harness — the actual code re-derivation (annotated
# companion alignment with the new upstream) is a human task. The
# script handles the mechanical parts:
#   1. Records the new SHA in cross-codebase/<donor>/pinned-commit
#   2. Prints a checklist of what the human still needs to do
#
# Run scripts/golden.sh generate after re-deriving the .pyk files.

set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <donor-dir-name> <new-upstream-sha>" >&2
  echo "example: $0 spark abc1234567890abcdef" >&2
  exit 2
fi

DONOR="$1"
NEW_SHA="$2"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DONOR_DIR="$REPO_ROOT/cross-codebase/$DONOR"

if [ ! -d "$DONOR_DIR" ]; then
  echo "error: $DONOR_DIR does not exist" >&2
  exit 1
fi

OLD_SHA="$(cat "$DONOR_DIR/pinned-commit" 2>/dev/null || echo "<none>")"
echo "$NEW_SHA" > "$DONOR_DIR/pinned-commit"

echo "Updated cross-codebase/$DONOR/pinned-commit:"
echo "  old: $OLD_SHA"
echo "  new: $NEW_SHA"
echo
echo "Next steps (manual):"
echo "  1. Replace upstream/ files with verbatim copies from the new SHA"
echo "     (rename .py -> .pyk on copy)."
echo "  2. Re-derive annotated/ companions against the new upstream."
echo "  3. Regenerate goldens:"
echo "       cargo build --release -p pykrete    # in the pykrete repo"
echo "       scripts/golden.sh generate /path/to/pykrete"
echo "  4. git diff cross-codebase/$DONOR/"
echo "  5. Commit upstream + annotated + golden + pinned-commit together."
