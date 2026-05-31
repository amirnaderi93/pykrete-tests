# spark — probes_negative/

Deliberately-corrupted fixtures derived from Apache Spark's PySpark
test surface (`python/pyspark/sql/tests/`). Each fixture mirrors a
real upstream code shape, then injects exactly one regression so
pykrete must fire a specific diagnostic.

Fixtures here run under **strict mode** (sibling `pykrete.json`
enables `strictTypeOps`). See the "Strict-mode caveat" subsection
of `scripts/PROBES.md` before adding new fixtures.

- `cross_type_comparison.pyk` — KV schema from `test_column.py`'s
  operator surface, but compares string against int to force D0082
  (`crossTypeComparison`, strict mode).
- `drop_then_reference.pyk` — NameAgeActive schema from
  `test_dataframe.py`'s drop demo. Drops two columns, then references
  the dropped columns in a follow-up `.select()`, forcing two
  D0030s from one statement (stacked-EXPECTS coverage) plus a third
  earlier D0030.
