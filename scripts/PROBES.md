# Schema-tracking probes

Probes are inline assertions in `.pyk` fixtures that verify pykrete is
*actually tracking schemas correctly* — not just silently emitting zero
diagnostics. They close the gap between "no false positives" (what the
v1.0 cross-codebase suite verifies) and "the checker really knows
schemas evolve through `.select()`, `.withColumn()`, joins, etc."

Status: v1.1, informational only. The runner ships now; CI wiring lands
in the next PR. Fixture seeding lands in PR #3.

## Operating model

The probes runner (`scripts/probes.py`) is wired into CI via
`scripts/probes_ci.sh` and the `probes · informational coverage` job
in `.github/workflows/probes.yml`. **Today (v1.1) it is informational
only** — a probe failure surfaces in the PR check list and the
structured JSON report uploads as the `probes-report` artifact, but
the job runs `continue-on-error: true` and does not block merge.
PR #3c of the v1.1 series flips this to release-blocking once the
fixture corpus is fully seeded; this happens atomically with the
trust-claim migration in README so the public claim never overruns
the gate.

Two fixture trees feed the runner:

- **`cross-codebase/<donor>/annotated/`** — donor-faithful PySpark
  code with positive probes (`PROBE-RESOLVES`, `PROBE-TYPE-IS`,
  `PROBE-FILE-CLEAN-OF`). Each fixture's `.golden.json` has an empty
  `diagnostics: []` array. These probes assert that pykrete correctly
  tracks schemas through real transforms.
- **`cross-codebase/<donor>/probes_negative/`** — deliberately-corrupted
  fixtures with negative probes (`PROBE-EXPECTS`, `PROBE-FILE-COUNT`).
  Each fixture's `.golden.json` has a NON-EMPTY `diagnostics[]` array
  encoding exactly the diagnostics pykrete must fire. These probes
  assert that pykrete actually catches regressions — without them, a
  silently-passing checker would satisfy every annotated/ probe
  vacuously.

The two trees together close the trust gap: annotated/ proves we
don't false-positive on real PySpark; probes_negative/ proves we
don't false-negative when the schema is violated.

**Catalog drift.** `scripts/diagnostic_catalog.json` is a vendored
snapshot of pykrete-core's `DIAGNOSTIC_CATALOG`. When pykrete-core
ships a release that adds or renames D-codes, the
`catalog-drift-watch` workflow opens a one-step refresh PR (typically
weekly cadence). Probe fixtures keep working across these refreshes
because PR #3a's `probes_negative/` exercises the catalog-resolution
path — a stale catalog or a renamed D-code surfaces here first.

**Authoring expectations for new donors.** When a future donor lands
under `cross-codebase/<donor>/`, it should ship with at least three
probes split across positive and negative — typically one
`PROBE-RESOLVES` on a representative DataFrame binding in `annotated/`
plus two `probes_negative/` fixtures covering different failure modes
the donor exercises (e.g. a dropped column the donor's code reads
from, a type mismatch in the donor's arithmetic surface). The
per-donor target (3 probes; mix of positive + negative) becomes
release-blocking in v1.2; v1.1 ships it as a checked-on-merge
expectation in code review.

## Probe placement convention

Markers are single-line `#`-prefixed comments and **must start at
column 0** — the parser only extracts COMMENT tokens whose source
column is 0. An indented `# PROBE-...` comment in a function body
is treated as a normal comment and silently skipped. This is the
v1.1 convention; PR #3b authors ~80-120 probes following it. Two
implications for authors:

- **Line-anchored markers above an indented statement.** The target
  line is resolved by AST walk — the marker still attaches to the
  next logical Python statement, even when that statement is
  indented inside a function body. A column-0 marker followed by an
  indented `return df.select(...)` correctly targets the `return`.
- **Markers at module scope.** Same convention — column 0. The
  target line is the next module-level statement (e.g. a `class`,
  `def`, or top-level assignment).

```python
# PROBE-FILE-CLEAN-OF: D0030
from pyspark.sql import DataFrame
from pyspark.sql.functions import col


class Sale(Schema):
    region: string
    amount: int


# PROBE-RESOLVES: id=spark-select-region -- region survives narrow select
def pipeline(d: DataFrame[Sale]) -> DataFrame:
# PROBE-EXPECTS: D0030 on "\"missing\"" id=spark-select-unknown
    return d.select(col("region"), col("missing"))
```

The third marker shows the common pattern: a marker at column 0
sitting between a function header and the function body, attached
to the `return` statement on the next non-blank source line. The
`on "\"missing\""` value includes the surrounding quotes because
the diagnostic's span text is `column..endColumn` over the source
text — for `col("missing")`, the span is `"missing"` (with quotes).

To preview what a marker resolves to before committing, run:

```bash
python scripts/probes.py extract path/to/fixture.pyk
```

It prints each parsed marker's `comment_line` and `target_line` so
authors can confirm placement without firing pykrete.

## Marker syntax

There are five marker kinds (one of which, `PROBE-TYPE-IS`, is deferred
to v1.2 — see below). All are single-line `#`-prefixed comments at
column 0. Three are line-anchored (they target the **next logical
Python statement**); two are file-scoped.

### Line-anchored

```python
# PROBE-EXPECTS: <D-code> [id=<handle>] [on "<span-text>"] [match /<regex>/[flags]] [-- <rationale>]
# PROBE-RESOLVES: [id=<handle>] [-- <rationale>]
# PROBE-TYPE-IS: <type-expr> on "<column>" [id=<handle>] [-- <rationale>]
```

- `PROBE-EXPECTS` — pykrete must emit the named D-code on the target
  line. Use it on lines that deliberately misuse the schema (typically
  in a `probes_negative/` fixture).
- `PROBE-RESOLVES` — pykrete must NOT emit any diagnostic on the target
  line. This proves the tracked schema accepts the reference. Use it
  to verify columns survive a narrow `.select()`, an alias chain, etc.
- `PROBE-TYPE-IS` — **deferred to v1.2.** The marker still parses, but
  synthesis is inconclusive in v1.1: the synthesizer emits a standalone
  `col("x") + lit(1)` expression that does not bind to a typed
  DataFrame in scope, so no type-mismatch D-code can fire. Do not
  author TYPE-IS markers in v1.1 — they are no-ops. v1.2 will inject
  the synthesized expression inside a `df.select(...)` against the
  typed DataFrame so `col()` binds and D0081 can fire. See pykrete's
  `docs/design/schema-tracking-probes.md` v1.2 tracker.

### File-scoped

```python
# PROBE-FILE-CLEAN-OF: <D-code>[, <D-code>...] [id=<handle>] [-- <rationale>]
# PROBE-FILE-COUNT: <D-code> == <N> [id=<handle>] [-- <rationale>]
```

- `PROBE-FILE-CLEAN-OF` — no diagnostic in the file carries any of
  the listed codes.
- `PROBE-FILE-COUNT` — exactly `<N>` diagnostics with `<D-code>` fire
  in the file. Useful to document deltas ("there used to be 3, now 0").

### Optional argument slots

All optional arguments are **order-insensitive named slots**. The parser
keys on the slot keyword, not on position:

- `id=<handle>` — stable handle shown in failure output and reports.
  Synthesized if omitted. IDs must be unique within a fixture (and,
  for cross-file uniqueness, within a donor under `cross-codebase/`).
- `on "<text>"` — pins `PROBE-EXPECTS` to a diagnostic whose source
  span (sliced by `column..endColumn`, strict equal — no substring
  fallback) equals `<text>`. For `PROBE-TYPE-IS`, names the column
  under assertion.
- `match /<regex>/[flags]` — pins `PROBE-EXPECTS` by message regex
  (Python `re`; flags `i m s x`). Prefer `on` — diagnostic message
  wording is NOT stable across pykrete-core minor releases.
- `-- <rationale>` — free-form note that ends the marker. Shown in
  failure output.

### Quoting rules

The `on "..."` value is parsed verbatim with two escapes only:

- `\"` → literal `"`
- `\\` → literal `\`

No other escape is interpreted. `\n`, `\t`, etc. are preserved as the
literal two-character sequences. Unterminated quoted strings hard-fail
at parse time with a named `ProbeError`. Non-ASCII bytes (e.g. `café`)
pass through unchanged.

### Type expressions

`PROBE-TYPE-IS` is **deferred to v1.2** (see above). The marker grammar
still parses type expressions for forward compatibility, but no v1.1
TYPE-IS marker drives a meaningful assertion. Do not author TYPE-IS
markers in v1.1.

## Target-line resolution

A line-anchored marker attaches to the **first source line of the next
Python logical statement** after the comment. Blank lines and other
comments are skipped. A marker directly above a decorator attaches to
the decorated `def`, not the decorator. A marker with no following
statement is a parse error.

## Running

```bash
# Verify every .pyk under one or more paths (recursive; default = CWD):
python scripts/probes.py run cross-codebase/

# Extract probes as JSON (for tooling / inspection):
python scripts/probes.py extract path/to/fixture.pyk

python scripts/probes.py --version
python scripts/probes.py --help
```

### Running the CI driver locally

`scripts/probes_ci.sh` is the wrapper CI invokes. It walks every
donor's `annotated/` and `probes_negative/` subtree, runs `probes.py
run` against each, and emits a combined JSON report.

```bash
PYKRETE_BIN=/path/to/pykrete bash scripts/probes_ci.sh
# Prints a human-readable summary (probes-found / passed / failed,
# failedProbeIds list) and writes the combined report to
# $PROBES_REPORT (default /tmp/probes-report.json).
```

Exit codes match `probes.py run`: 0 = all green (or no probes
found), 1 = at least one probe failed, 2 = setup error.

### CI behavior (v1.1)

The `probes · informational coverage` job runs on every push and
PR. It uses `continue-on-error: true` — a probe failure surfaces in
the PR check list and the structured JSON report uploads as a
workflow artifact (`probes-report`), but the failure does NOT block
merge. PR #3 of the v1.1 series flips this to release-blocking
once probes are seeded across the 32 annotated fixtures.

If you're reading CI output and see a yellow/orange check on
`probes · informational coverage`, that's the contract: investigate
the failed probes, but it's intentional that the PR can still
merge.

### Env vars

- `PYKRETE_BIN` — path to the pykrete binary. Defaults to `pykrete` on
  PATH. The runner does not assume a build location.
- `PROBES_CATALOG` — override path to `diagnostic_catalog.json`.
  Defaults to the file next to `probes.py`.
- `PYKRETE_TIMEOUT` — seconds for the pykrete subprocess (default 30).
  Raise this if the checker is slow on a particular fixture.

### Exit codes

| code | meaning |
|------|---------|
| 0    | all probes satisfied (or no probes found) |
| 1    | one or more probes failed |
| 2    | usage error, parse error, catalog drift, or checker crash |

### Output

The runner writes structured JSON to stdout summarizing per-fixture
probe pass/fail. Per-probe failure messages go to stderr in this shape:

```
PROBE FAILURE: <fixture>
  comment line <C>  target line <T>  id=<id>
    PROBE-<KIND> <args>
    expected: <human-readable expectation>
    actual:   <what was observed>
```

The format is greppable and includes both the comment line (where the
marker lives) and the target line (where the assertion applies), so a
CI log reader can jump straight to the failing assertion. An empty
checker stdout with a non-zero exit is treated as a crash (`CHECKER
ERROR: ...` on stderr, exit 2), not a silent pass.

## Worked example

```python
from pykrete import col, lit
from quinn.schemas import Order


def pipeline(orders: DataFrame[Order]) -> DataFrame[Order]:
# PROBE-RESOLVES: id=quinn-select-region -- region survives narrow select
    df = orders.select("region", "amount")

# PROBE-EXPECTS: D0030 id=quinn-select-drops-product on "product"
    return df.select(col("product"))
```

Both markers sit at column 0 even though the statements they target
are indented inside `pipeline`. The parser only extracts COMMENT
tokens at column 0; an indented `# PROBE-...` would be silently
skipped (see "Probe placement convention" above).

The two probes cover the chain end-to-end: the `select` keeps
`region` (`RESOLVES`), and a follow-up reference to `product`
correctly fires D0030 (`EXPECTS`).

### Tricky placement cases

The "column 0, target = next logical statement" rule covers every
case, but three placements come up often enough in PR #3b authoring
that they're worth showing explicitly.

**(a) Marker describing a class-method body line.** The marker sits
at column 0 even though the method body it targets is double-indented
inside the class:

```python
class Pipeline:
    def run(self, orders: DataFrame[Order]) -> DataFrame:
# PROBE-RESOLVES: id=pipeline-method-region
        return orders.select("region")
```

The marker resolves to the `return` line — `target_line` is the
first source line of the next logical statement, regardless of
indent depth.

**(b) Marker above a multi-line chained call.** When a chain like
`.select(...).filter(...).withColumn(...)` is split across lines,
the marker attaches to the first source line of the chain (the
assignment or `return` it sits inside):

```python
def derive(df: DataFrame[Sale]) -> DataFrame:
# PROBE-EXPECTS: D0030 on "\"missing\"" id=derive-missing-in-chain
    return (df
        .select(col("region"), col("amount"))
        .filter(col("region") == "EU")
        .withColumn("doubled", col("missing") * 2))
```

The marker resolves to the `return` line. The D0030 diagnostic
fires on the `col("missing")` token deeper in the chain, but the
marker's anchor is the statement, not the offending sub-expression.

**(c) Marker right after a function `def` line.** A column-0 marker
between the `def` and the first body statement anchors to that body
statement, not to the `def`:

```python
def keep_region(orders: DataFrame[Order]) -> DataFrame:
# PROBE-RESOLVES: id=keep-region-narrow-select
    return orders.select("region")
```

The marker resolves to the `return`. To anchor to a `def` itself
(e.g. a decorator placement), put the marker above the decorator —
it then attaches to the decorated `def`.

### Strict-mode caveat

`probes.py` stages each fixture into a temp dir and runs pykrete from
there. Staging copies the **entire source directory**, so a
`pykrete.json` sitting beside a fixture applies to that fixture *and
to every sibling fixture in the same directory*. This is what makes
the D0081 / D0082 negative fixtures work — `cross-codebase/spark/
probes_negative/pykrete.json` and `cross-codebase/mlflow/
probes_negative/pykrete.json` are 31-byte files enabling strict mode
across their directories.

Two implications for PR #3b authors:

- The existing `spark/probes_negative/` and `mlflow/probes_negative/`
  directories are **strict-mode directories**. Adding a new fixture
  there that exercises arithmetic or cross-type comparisons inherits
  strict-mode checking whether you wanted it or not.
- If you need a different config for a new fixture, put it in its own
  per-fixture subdir: `probes_negative/<fixture-name>/<fixture-name>
  .pyk` + `probes_negative/<fixture-name>/pykrete.json`. The runner
  picks up the nearest sibling `pykrete.json` per the standard
  pykrete config-discovery rules.

A `pykrete.json` next to a fixture is silently scoped to its
directory; if you find yourself wanting to opt one fixture out of
strict mode, the right answer is to move it to its own subdir, not
to delete the sibling `pykrete.json` for the others.

## Diagnostic catalog

`scripts/diagnostic_catalog.json` is a vendored snapshot of
pykrete-core's `DIAGNOSTIC_CATALOG`. Every `PROBE-EXPECTS` /
`PROBE-FILE-CLEAN-OF` / `PROBE-FILE-COUNT` D-code must exist in this
catalog or the probe fails to parse. The catalog is refreshed in
lockstep with `PYKRETE_REF` bumps; a scheduled drift-watch GHA
(`catalog-drift-watch.yml`) surfaces upstream additions before the
next bump.

### catalog-drift-watch contract

The workflow runs weekly (Mondays 14:00 UTC) and can be triggered
manually from the GitHub Actions tab via `workflow_dispatch`. It:

1. Polls pykrete-core's `main` for the current HEAD commit.
2. Skips with a warning if the upstream commit's check-runs report
   any failure / timeout / action-required conclusion (we won't
   vendor a known-broken upstream state).
3. Otherwise fetches `crates/pykrete/src/diagnostics.rs` at that
   commit, regenerates `scripts/diagnostic_catalog.json` via
   `scripts/build_catalog_from_source.py`, and opens a
   `chore(catalog): refresh from pykrete <sha>` PR **only when the
   diagnostics payload changes** — a pin-only SHA bump does not open
   a PR. The PR body cites the source commit and lists the
   added / renamed / removed D-codes. Successive weekly runs
   force-update the same `catalog-drift/auto` branch, so at most one
   refresh PR is ever open.
4. Network failure fails the workflow with a clear message; the
   next weekly cron retries.

The auto-opened refresh PR is created by `GITHUB_TOKEN`, which by
GitHub policy does not trigger downstream workflow runs — so its own
`probes` check will sit pending until a maintainer pushes an empty
commit or closes/reopens the PR. This is GHA-platform behavior, not
a bug in the workflow.

Run the builder by hand to preview drift without opening a PR:

```bash
python scripts/build_catalog_from_source.py \
  --diagnostics /path/to/pykrete/crates/pykrete/src/diagnostics.rs \
  --commit "$(git -C /path/to/pykrete rev-parse HEAD)" \
  --previous scripts/diagnostic_catalog.json \
  --out /tmp/new_catalog.json \
  --summary /tmp/catalog_summary.txt
diff scripts/diagnostic_catalog.json /tmp/new_catalog.json
cat /tmp/catalog_summary.txt
```

## Authoring API

`scripts.probes.extract` and `scripts.probes.verify` are stable
within `probesSchemaVersion: "1"`. Fixture-author tooling may import
them. See the `Probe` and `ProbeFailure` dataclasses in `probes.py`.
