# Schema-tracking probes

Probes are inline assertions in `.pyk` fixtures that verify pykrete is
*actually tracking schemas correctly* — not just silently emitting zero
diagnostics. They close the gap between "no false positives" (what the
v1.0 cross-codebase suite verifies) and "the checker really knows
schemas evolve through `.select()`, `.withColumn()`, joins, etc."

Status: v1.1, informational only. The runner ships now; CI wiring lands
in the next PR. Fixture seeding lands in PR #3.

## Marker syntax

There are five marker kinds. All are single-line `#`-prefixed comments
at column 0. Three are line-anchored (they target the **next logical
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
- `PROBE-TYPE-IS` — pykrete's tracked schema gives `<column>` the
  asserted type at the target line. Implemented via a synthesizer
  rewrite that targets D0081 (strict-mode operator check). One type
  expression per probe.

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

`PROBE-TYPE-IS` accepts the same atomic type names as `Schema`
annotations: `string`, `boolean`, `bool`, `date`, `timestamp`, `binary`.
Collections: `Array[T]` and `array<T>` are accepted (normalized to
`array<T>`).

**Numeric carve-out (v1.1).** Within-family numeric subtypes
(`int`, `long`, `short`, `byte`, `double`, `float`, `decimal`,
`decimal(p, s)`) are rejected at parse time with a named `ProbeError`.
The synthesizer can only fire family-level D-codes (D0080-D0082), so a
green for an int-vs-double probe would be vacuous. v1.2 will re-enable
numeric subtypes once pykrete-core ships numeric-subtype-mismatch
D-codes. For now, use a cross-family assertion (e.g., `string on
"name"`) to prove a column is non-numeric.

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

    # PROBE-TYPE-IS: string on "region" id=quinn-region-type
    df2 = df

    # PROBE-EXPECTS: D0030 id=quinn-select-drops-product on "product"
    return df2.select(col("product"))
```

Three probes cover the same chain end-to-end: the `select` keeps
`region` (`RESOLVES`), `region` stays a `string` (`TYPE-IS`), and a
follow-up reference to `product` correctly fires D0030 (`EXPECTS`).

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
