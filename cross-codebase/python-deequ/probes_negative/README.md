# python-deequ — probes_negative/

Deliberately-corrupted fixtures derived from python-deequ's
`tests/test_analyzers.py` (AnalysisRunner / AnalyzerContext flow),
`tests/test_checks.py` (VerificationSuite / VerificationResult
flow), and `pydeequ/pandas_utils.py` (PandasConverter dialect
handoff) at pinned-commit 20693b81. Each fixture mirrors a real
upstream code shape, then injects exactly one regression so pykrete
must fire a specific diagnostic.

This directory is strict-mode (`pykrete.json` enables
`typeCheckingMode: strict`); every fixture below inherits it.

- `analyzer_metric_then_unknown.pyk` — deequ's most-frequent API
  surface. `AnalysisRunner.onData(df).addAnalyzer(...).run()` →
  `AnalyzerContext.successMetricsAsDataFrame(spark, result)` returns
  a MetricRow-shaped DataFrame; upstream tests call
  `.select("value").collect()`. This fixture references `variance`,
  which is not in MetricRowNeg. Forces D0030.
- `parallelize_then_unknown.pyk` — deequ's schema-introspection-
  style fixture-build pattern. `sc.parallelize([Row(...)]).toDF()`
  produces an opaque DataFrame; the annotated/ companion .casts onto
  InputRow. This fixture mirrors the same re-anchor then references
  `e`, which is not in InputRowNeg (real Row had `a, b, c, d`
  only). Forces D0030.
- `verification_narrow_then_drop.pyk` — DataFrame-output
  transformation. `VerificationSuite.run()` →
  `VerificationResult.checkResultsAsDataFrame` returns a 6-column
  schema (check, check_level, check_status, constraint,
  constraint_status, constraint_message); upstream
  `run_check` narrows via `.select(*columns)`. This fixture narrows
  to `constraint_status` only and then references
  `constraint_message`, which the narrow dropped. Forces D0030.
- `to_pandas_then_unknown.pyk` — cross-dialect probe. pydeequ's
  `PandasConverter.pysparkDF_to_pandasDF` returns
  `spark_df.toPandas()`; `ensure_pyspark_df` accepts both pandas
  and pyspark inputs, making this the donor's canonical
  cross-dialect surface. Exercises the v1.5 PR-A1 `.toPandas()`
  Spark→pandas handoff on CustomerRow, then references a column not
  in the schema on the pandas side. Forces D0030 — verifies
  negative coverage carries across the handoff.
- `withColumn_arith_on_string.pyk` — strict-mode probe. MetricRow
  shape (entity:string, instance:string, name:string, value:double);
  mixes the string `name` into arithmetic with `value`. Forces
  D0081 (nonNumericArithmetic) on deequ's strictest typing surface
  (the post-analyzer metric DataFrame is where downstream user code
  does numeric aggregations on `value`).
