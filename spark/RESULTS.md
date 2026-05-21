# Spark — pykrete results

Per-file diagnostics from running `pykrete check` over the vendored Apache
Spark sources after pykrete annotations were added. Regenerated on every CI
run (once that's wired); for now updated by hand alongside pilots.

**pykrete version:** main @ `483cc09` (post-v0.1.5 fix landed)
**upstream commit:** [`c3096ee`](https://github.com/apache/spark/tree/c3096ee570572f385a409d07988e7a75c524ecd1)
**run date:** 2026-05-21

## Files exercised

### `examples/src/main/python/sql/basic.py` — pilot

Canonical "first PySpark example" file from the Spark docs. 214 lines, two
example pipelines plus an RDD/SQL example.

**Annotations added** (kept minimal):

- `class People(Schema)` declaring the columns of `people.json`
  (`age: long`, `name: string`).
- The DataFrame-using core of `basic_df_example` extracted into a helper
  `people_demo(spark: SparkSession, df: DataFrame[People])`. pykrete only
  enters body analysis for functions whose signature has a `DataFrame[X]`
  slot, so the helper-extraction is required to get the body checked.
- `df = spark.read.json(...).cast(DataFrame[People])` to re-anchor the
  opaque `spark.read` chain.

**Result on the unmodified annotated file:**

```
1 schema(s), 1 typed function(s), 0 issue(s)
```

Clean — no false positives.

**Probes** (planted bugs, to verify the analyzer actually fires):

| Typo planted | pykrete output |
|---|---|
| `df.select("nmae")` (bare-string) | ✅ `D0030 unknownColumn: Column 'nmae' does not exist on schema 'People'` |
| `df["aeg"] > 21` (subscript form) | ✅ `D0030 unknownColumn: Column 'aeg' does not exist on schema 'People'` |

Both forms now caught.

## Gaps surfaced and fixed in this iteration

1. **`df["X"]` subscript wasn't recognized as a column reference.**
   `basic.py` uses subscript form exclusively in its filter/select
   examples; a typo on `df["aeg"]` slipped past silently. **Fixed** in
   pykrete commit
   [`483cc09`](https://github.com/amirnaderi93/pykrete/commit/483cc09) —
   subscript form is now recognized alongside `col("X")` and `df.X`, in
   both the general column-ref walker and the arg-position extractor
   used by `groupBy`/`drop`. 11 regression tests in
   [`tests/subscript_columns.rs`](https://github.com/amirnaderi93/pykrete/blob/main/crates/pykrete/tests/subscript_columns.rs).

## Files queued for next iteration

- `python/pyspark/sql/tests/test_group.py` (7.7 KB — focused groupBy/agg).
- One MLflow file — to be picked from the ~65 files importing
  `pyspark.sql`.
