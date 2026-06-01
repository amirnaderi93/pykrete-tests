# spark — probes_negative/

Deliberately-corrupted fixtures derived from Apache Spark's PySpark
test surface (`python/pyspark/sql/tests/`). Each fixture mirrors a
real upstream code shape, then injects exactly one regression so
pykrete must fire a specific diagnostic.

Fixtures here run under **strict mode** (sibling `pykrete.json` sets
`typeCheckingMode: "strict"`). See the "Strict-mode caveat"
subsection of `scripts/PROBES.md` before adding new fixtures.

- `cross_type_comparison.pyk` — KV schema from `test_column.py`'s
  operator surface, but compares string against int to force D0082
  (`crossTypeComparison`, strict mode).
- `drop_then_reference.pyk` — NameAgeActiveNeg schema from
  `test_dataframe.py`'s drop demo. Two functions: `drop_then_select_dropped`
  drops one column (`active`) then references it in a follow-up
  `.select()`, forcing one D0030; `select_two_unknowns` selects two
  typos (`nam`, `agee`) in a single `.select()` call, forcing two
  stacked D0030s from one statement (stacked-EXPECTS coverage).
