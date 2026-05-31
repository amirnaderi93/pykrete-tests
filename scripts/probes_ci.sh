#!/usr/bin/env bash
# CI driver for schema-tracking probes (v1.1, informational).
#
# Walks the cross-codebase tree, runs scripts/probes.py against each
# donor's annotated/ and probes_negative/ subtrees (if present), and
# emits a human-readable summary plus a combined structured JSON report
# at $PROBES_REPORT (default /tmp/probes-report.json) for CI artifact
# upload.
#
# Usage:
#   PYKRETE_BIN=/path/to/pykrete bash scripts/probes_ci.sh
#
# Env:
#   PYKRETE_BIN     path to the pykrete binary; required.
#   PROBES_REPORT   where to write the combined JSON report
#                   (default: /tmp/probes-report.json).
#
# Exit codes:
#   0  every probe passed (or zero probes found).
#   1  one or more probes failed.
#   2  setup error (missing binary, malformed probe marker, checker crash).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYKRETE_BIN="${PYKRETE_BIN:-}"
if [ -z "$PYKRETE_BIN" ]; then
  echo "error: PYKRETE_BIN is not set" >&2
  echo "       set it to a pykrete binary path, e.g.:" >&2
  echo "       PYKRETE_BIN=/path/to/pykrete bash scripts/probes_ci.sh" >&2
  exit 2
fi
if [ ! -x "$PYKRETE_BIN" ]; then
  echo "error: PYKRETE_BIN=$PYKRETE_BIN is not executable" >&2
  exit 2
fi
export PYKRETE_BIN

REPORT_PATH="${PROBES_REPORT:-/tmp/probes-report.json}"

positive_paths=()
negative_paths=()
while IFS= read -r d; do positive_paths+=("$d"); done < <(
  find cross-codebase -mindepth 2 -maxdepth 2 -type d -name annotated | sort
)
while IFS= read -r d; do negative_paths+=("$d"); done < <(
  find cross-codebase -mindepth 2 -maxdepth 2 -type d -name probes_negative | sort
)

run_tree() {
  local label="$1"; shift
  local out_path="$1"; shift
  if [ "$#" -eq 0 ]; then
    echo "{\"probesSchemaVersion\":\"1\",\"fixturesWithProbes\":0,\"probesTotal\":0,\"failuresTotal\":0,\"failedProbeIds\":[],\"perFixture\":[]}" > "$out_path"
    echo "$label: no fixture tree present (skipped)."
    return 0
  fi
  local rc=0
  python3 scripts/probes.py run "$@" > "$out_path" 2>/tmp/probes-stderr.$$ || rc=$?
  if [ -s /tmp/probes-stderr.$$ ]; then
    cat /tmp/probes-stderr.$$ >&2
  fi
  rm -f /tmp/probes-stderr.$$
  if [ "$rc" -eq 2 ]; then
    echo "error: probes.py setup error on $label tree (exit 2)" >&2
    exit 2
  fi
  return 0
}

pos_report="/tmp/probes-positive.$$.json"
neg_report="/tmp/probes-negative.$$.json"
trap 'rm -f "$pos_report" "$neg_report"' EXIT

run_tree "positive (annotated/)" "$pos_report" "${positive_paths[@]}"
if [ "${#negative_paths[@]}" -gt 0 ]; then
  run_tree "negative (probes_negative/)" "$neg_report" "${negative_paths[@]}"
else
  echo "{\"probesSchemaVersion\":\"1\",\"fixturesWithProbes\":0,\"probesTotal\":0,\"failuresTotal\":0,\"failedProbeIds\":[],\"perFixture\":[]}" > "$neg_report"
  echo "negative (probes_negative/): no fixture tree present (skipped)."
fi

python3 - "$pos_report" "$neg_report" "$REPORT_PATH" <<'PY'
import json, sys
pos_path, neg_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(pos_path) as f: pos = json.load(f)
with open(neg_path) as f: neg = json.load(f)
combined = {
    "probesSchemaVersion": pos.get("probesSchemaVersion") or neg.get("probesSchemaVersion") or "1",
    "catalogSourceCommit": pos.get("catalogSourceCommit") or neg.get("catalogSourceCommit"),
    "positive": pos,
    "negative": neg,
    "totals": {
        "probesTotal": pos.get("probesTotal", 0) + neg.get("probesTotal", 0),
        "failuresTotal": pos.get("failuresTotal", 0) + neg.get("failuresTotal", 0),
        "fixturesWithProbes": pos.get("fixturesWithProbes", 0) + neg.get("fixturesWithProbes", 0),
    },
}
with open(out_path, "w") as f:
    json.dump(combined, f, indent=2)
    f.write("\n")
totals = combined["totals"]
print()
print("Schema-tracking probes summary")
print("------------------------------")
print(f"  probesSchemaVersion: {combined['probesSchemaVersion']}")
print(f"  catalogSourceCommit: {combined['catalogSourceCommit']}")
print(f"  fixtures-with-probes: {totals['fixturesWithProbes']}")
print(f"  probes-found:         {totals['probesTotal']}")
probes_passed = totals['probesTotal'] - totals['failuresTotal']
print(f"  probes-passed:        {probes_passed}")
print(f"  probes-failed:        {totals['failuresTotal']}")
failed = list(pos.get("failedProbeIds", [])) + list(neg.get("failedProbeIds", []))
if failed:
    print("  failedProbeIds:")
    for fid in failed:
        print(f"    - {fid}")
print(f"  report:               {out_path}")
sys.exit(1 if totals['failuresTotal'] else 0)
PY
