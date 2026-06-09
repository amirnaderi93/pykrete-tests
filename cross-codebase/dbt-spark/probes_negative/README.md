# dbt-spark — probes_negative/

Deliberately-corrupted fixtures derived from dbt-spark's
`dbt/adapters/spark/session.py` (Cursor.execute / QueryResult) and
`tests/functional/adapter/test_python_model.py` (TwoIntCols Python
model) at pinned-commit 42700b5d. Each fixture mirrors a real
upstream code shape, then injects exactly one regression so pykrete
must fire a specific diagnostic.

This directory is strict-mode (`pykrete.json` enables
`typeCheckingMode: strict`); every fixture below inherits it.

- `sql_then_unknown.pyk` — Cursor.execute's
  `spark.sql(sql).cast(DataFrame[QueryResultNeg])` re-anchor, then a
  follow-up `.select("row_count")` against a column not in the
  schema. Forces D0030 on the most-frequent dbt-spark adapter
  pattern.
- `create_dataframe_then_unknown.pyk` — Python-model's
  `spark.createDataFrame(data, schema=['test1','test3']).cast(
  DataFrame[TwoIntColsNeg])` re-anchor, then a `.select("test2")` —
  test2 was renamed to test3 in the v2 model. Forces D0030 on dbt's
  python-model convention surface.
- `narrowed_select_then_drop.pyk` — narrowed `.select("test1")` on
  the TwoIntCols schema, then a follow-up `.select(col("test3"))`
  references the column the narrow dropped. Forces D0030 on the
  DataFrame-output transformation chain.
- `to_pandas_then_unknown.pyk` — cross-dialect probe. dbt-spark's
  python-model convention accepts Spark / pandas / pyspark.pandas
  returns (BasePySparkTests.test_different_dataframes). Exercises
  the v1.5 PR-A1 `.toPandas()` Spark→pandas handoff on the
  TwoIntCols shape, then references a column not in the schema on
  the pandas side. Forces D0030 — verifies the dialect handoff
  carries negative coverage, not just the positive path.
- `withColumn_arith_on_string.pyk` — strict-mode probe. Cursor
  result's QueryResult shape (id:int + msg:string); mixes the
  string `msg` into arithmetic with `id`. Forces D0081
  (nonNumericArithmetic) on dbt-spark's strictest typing surface
  (Cursor result columns flowing into downstream model arithmetic).
