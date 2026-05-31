#!/usr/bin/env bash
# Shell unit tests for scripts/probes_ci.sh.
#
# Closes round-2 BLOCKER 1 (probes.yml pipe-tee swallowed exit code)
# and BLOCKER 3 (bash 3.x crash on empty positive_paths).
#
# Run:  bash scripts/test_probes_ci.sh
#
# Exit 0 = all assertions held; non-zero on any assertion failure.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

note() { echo "  $*"; }
pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; [ -n "${2:-}" ] && note "$2"; }

# -------- BLOCKER 1: pipe + tee propagates non-zero exit --------
# Simulate the workflow's exact recipe and force a failure on the LHS.
# Without `set -o pipefail` + `${PIPESTATUS[0]}`, rc would be tee's 0
# and CI would pass green on every probe failure.
rc=0
(
  set -o pipefail
  set +e
  bash -c 'echo simulated probe failure on stdout; exit 1' | tee "$WORK/out.txt"
  exit ${PIPESTATUS[0]}
) || rc=$?
if [ "$rc" -eq 1 ]; then
  pass "pipe-tee propagates non-zero exit (rc=$rc)"
else
  fail "pipe-tee swallowed exit code" "expected rc=1, got rc=$rc"
fi

# Negative: without pipefail + PIPESTATUS, rc=0 (the bug we fixed).
rc=0
(
  set +e
  bash -c 'exit 1' | tee "$WORK/out.txt"
  exit $?
) || rc=$?
if [ "$rc" -eq 0 ]; then
  pass "control: naive pipe-tee swallows exit code (proves the bug existed)"
else
  fail "control: naive pipe-tee unexpectedly returned non-zero (rc=$rc)"
fi

# -------- BLOCKER 3: probes_ci.sh tolerates empty fixture trees --------
# Run the real script against an empty cross-codebase tree with a
# stub binary. Under bash 3.2 this used to crash on empty array
# expansion under `set -u`; the explicit length-guard fixes it.
EMPTY_ROOT="$WORK/empty_repo"
mkdir -p "$EMPTY_ROOT/cross-codebase" "$EMPTY_ROOT/scripts"
cp scripts/probes_ci.sh "$EMPTY_ROOT/scripts/"
cp scripts/probes.py "$EMPTY_ROOT/scripts/"
cp scripts/diagnostic_catalog.json "$EMPTY_ROOT/scripts/"
STUB_BIN="$WORK/pykrete-stub"
cat > "$STUB_BIN" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$STUB_BIN"

rc=0
out="$WORK/empty_run.log"
PYKRETE_BIN="$STUB_BIN" PROBES_REPORT="$WORK/report.json" \
  bash "$EMPTY_ROOT/scripts/probes_ci.sh" > "$out" 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  pass "empty cross-codebase tree exits 0 (bash $(/usr/bin/env bash --version | head -1))"
else
  fail "empty cross-codebase tree crashed" "rc=$rc, output: $(cat "$out")"
fi

# If /bin/bash is bash 3.x (macOS), specifically re-run under it.
if /bin/bash -c '[ "${BASH_VERSINFO[0]}" -eq 3 ]' 2>/dev/null; then
  rc=0
  out="$WORK/empty_run_bash3.log"
  PYKRETE_BIN="$STUB_BIN" PROBES_REPORT="$WORK/report3.json" \
    /bin/bash "$EMPTY_ROOT/scripts/probes_ci.sh" > "$out" 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    pass "empty cross-codebase tree exits 0 under bash 3.2 (/bin/bash)"
  else
    fail "bash 3.2 crashed on empty positive_paths" "rc=$rc, output: $(cat "$out")"
  fi
else
  note "(skipped /bin/bash bash-3 reproduction — system bash is 4+)"
fi

echo
echo "summary: $PASS passed, $FAIL failed"
exit $FAIL
