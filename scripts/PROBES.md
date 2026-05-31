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
  rewrite that targets D0081/D0082 (strict-mode operator checks). One
  type expression per probe.

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
  Synthesized if omitted. IDs must be unique within a fixture.
- `on "<text>"` — pins `PROBE-EXPECTS` to a diagnostic whose source
  span (sliced by `column..endColumn`) equals `<text>`. For
  `PROBE-TYPE-IS`, names the column under assertion. Double-quoted;
  `\"` escapes.
- `match /<regex>/[flags]` — pins `PROBE-EXPECTS` by message regex
  (Python `re`; flags `i m s x`). Prefer `on` — diagnostic message
  wording is NOT stable across pykrete-core minor releases.
- `-- <rationale>` — free-form note that ends the marker. Shown in
  failure output.

### Type expressions

`PROBE-TYPE-IS` accepts the same atomic type names as `Schema`
annotations: `int`, `long`, `double`, `float`, `string`, `boolean`,
`bool`, `date`, `timestamp`, `binary`, `byte`, `short`, `decimal`,
`decimal(p, s)`. Collections: `Array[T]` and `array<T>` are accepted
(normalized to `array<T>`). `decimal` unparameterized matches Spark's
default `decimal(10, 0)`.

## Target-line resolution

A line-anchored marker attaches to the **first source line of the next
Python logical statement** after the comment. Blank lines and other
comments are skipped. A marker directly above a decorator attaches to
the decorated `def`, not the decorator. A marker with no following
statement is a parse error.

## Running

```bash
# Verify probes in a single file:
python scripts/probes.py verify path/to/fixture.pyk

# Verify everything under a directory (recursive):
python scripts/probes.py run cross-codebase/

# Extract probes as JSON (for tooling / inspection):
python scripts/probes.py extract path/to/fixture.pyk
```

### Env vars

- `PYKRETE_BIN` — path to the pykrete binary. Defaults to `pykrete` on
  PATH. The runner does not assume a build location.
- `PROBES_CATALOG` — override path to `diagnostic_catalog.json`.
  Defaults to the file next to `probes.py`.

### Exit codes

| code | meaning |
|------|---------|
| 0    | all probes satisfied (or no probes found) |
| 1    | one or more probes failed |
| 2    | usage error, parse error, or catalog drift |

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
CI log reader can jump straight to the failing assertion.

## Worked example

```python
from pykrete import col, lit
from quinn.schemas import Order


def pipeline(orders: DataFrame[Order]) -> DataFrame[Order]:
    # PROBE-RESOLVES: id=quinn-select-region -- region survives narrow select
    df = orders.select("region", "amount")

    # PROBE-TYPE-IS: double on "amount" id=quinn-amount-type
    df2 = df

    # PROBE-EXPECTS: D0030 id=quinn-select-drops-product on "product"
    return df2.select(col("product"))
```

Three probes cover the same chain end-to-end: the `select` keeps
`region` (`RESOLVES`), `amount` stays a `double` (`TYPE-IS`), and a
follow-up reference to `product` correctly fires D0030 (`EXPECTS`).

## Diagnostic catalog

`scripts/diagnostic_catalog.json` is a vendored snapshot of
pykrete-core's `DIAGNOSTIC_CATALOG`. Every `PROBE-EXPECTS` /
`PROBE-FILE-CLEAN-OF` / `PROBE-FILE-COUNT` D-code must exist in this
catalog or the probe fails to parse. The catalog is refreshed in
lockstep with `PYKRETE_REF` bumps; a scheduled drift-watch GHA (PR #2
of v1.1) surfaces upstream additions before the next bump.

## Authoring API

`scripts.probes.extract` and `scripts.probes.verify` are stable
within `probesSchemaVersion: "1"`. Fixture-author tooling may import
them. See the `Probe` and `ProbeFailure` dataclasses in `probes.py`.
