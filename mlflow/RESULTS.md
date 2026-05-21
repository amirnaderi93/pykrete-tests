# MLflow — pykrete results

Per-file diagnostics from running `pykrete check` over the vendored
MLflow sources after pykrete annotations were added. Regenerated on
every CI run (once that's wired); for now updated by hand alongside
pilots.

**pykrete version:** main @ `d68d1e2` (post-pilot-3 fix landed)
**upstream commit:** [`b5dd920`](https://github.com/mlflow/mlflow/tree/b5dd920)
**run date:** 2026-05-21

## Files exercised

### `tests/spark/autologging/datasource/test_spark_datasource_autologging.py` — pilot 3

MLflow's Spark datasource autologging integration tests. 286 lines of
end-to-end test scenarios that read CSVs through PySpark, apply
filter/select/limit chains, and verify that MLflow logs the right
datasource tags. Representative of the "MLflow library used against a
real Spark dataframe" surface.

**Annotations added** (kept minimal):

- `class Numbers(Schema)` with `number1: int, number2: int` — matches
  the columns in the CSVs being read (visible in upstream line 39:
  `SELECT number1, number2 from temptable LIMIT 5`).
- Two pykrete-typed module-level helpers carrying the dataframe-typed
  cores of the test bodies:
  - `chained_filter_select_limit_demo(df: DataFrame[Numbers])` —
    mirrors the dfs-list construction in
    `test_autologging_of_datasources_with_different_formats`.
  - `sql_query_result_demo(df: DataFrame[Numbers])` — mirrors the
    `spark.sql(...)` result, with the user re-anchoring to
    `DataFrame[Numbers]` via cast.
- The original test functions stay verbatim below — they take
  `spark_session, format_to_file_path` fixtures with no `DataFrame[X]`
  parameter, so pykrete doesn't enter their bodies. The helpers above
  are the observable surface.

**Result on the unmodified annotated file:**

```
1 schema(s), 2 typed function(s), 0 issue(s)
```

Clean — no false positives.

**Probes** (planted bugs):

| Typo planted | pykrete output |
|---|---|
| `df.filter(col("number1") > 0).select("nubmer1").limit(2)` | ✅ `D0030 unknownColumn: Column 'nubmer1' does not exist on schema 'Numbers'. Did you mean 'number1'?` |
| `df.filter("nubmer1 > 0")` (bare-string SQL filter) | ✅ `D0030 unknownColumn: Column 'nubmer1' does not exist on schema 'Numbers'. Did you mean 'number1'?` |
| `df.where("CAST(nofield AS STRING) = '5'")` (column ref inside CAST) | ✅ `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |
| `df.intersect(df).select(col("nofield"))` | ✅ (after fix) `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |
| `df.subtract(df).select(col("nofield"))` | ✅ (after fix) `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |
| `df.exceptAll(df).select(col("nofield"))` | ✅ (after fix) `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |
| `df.withColumn("flag", F.when(col("nofield") > 0, 1).otherwise(0))` | ✅ `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |
| `df.select(F.struct(col("nofield"), col("number2")).alias("s"))` | ✅ `D0030 unknownColumn: Column 'nofield' does not exist on schema 'Numbers'` |

Pleasant surprise: SQL-string filters (`df.filter("col > 0")`) and
their `where`/`selectExpr` siblings already extract column references
from inside CAST, comparison, and boolean expressions — no gap there.
`when/otherwise` and `F.struct` likewise already work.

## Gaps surfaced and fixed in this iteration

1. **`intersect` / `intersectAll` / `subtract` / `exceptAll` weren't
   modeled.** Their sibling `union` was; the four set ops fell through
   to the default (untyped result) branch, so a downstream
   `select(col("typo"))` slipped past silently. **Fixed** in pykrete
   commit
   [`d68d1e2`](https://github.com/amirnaderi93/pykrete/commit/d68d1e2)
   — a new `TwoDfMethod::SetOp` variant folds all four into the same
   handler as `Union/UnionByName` and threads the method name through
   so the schema-mismatch diagnostic reads
   `intersect between schema A and schema B: …` instead of the
   previous hardcoded `unionByName between …`. Six regression tests
   added to
   [`tests/inference_and_returns.rs`](https://github.com/amirnaderi93/pykrete/blob/main/crates/pykrete/tests/inference_and_returns.rs).

   *(Spark also documents `df.except`, but Python's `except` keyword
   makes that name unavailable as an attribute access — real PySpark
   code uses `exceptAll`/`subtract`, so it's not registered.)*

## Files queued for next iteration

- TBD — pilot 4 selection pending. Candidate areas: MLflow's
  `mlflow/spark/__init__.py` (model save/load), MLflow's evaluation
  pipelines (`mlflow/evaluation/`), or back to Spark for a
  representative `pyspark/ml/` file.
