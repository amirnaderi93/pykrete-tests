# Spark — pykrete results

Per-file diagnostics from running `pykrete check` over the vendored Apache
Spark sources after pykrete annotations were added. Regenerated on every CI
run (once that's wired); for now updated by hand alongside pilots.

**pykrete version:** 0.1.5
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
| `df["aeg"] > 21` (subscript form) | ❌ no diagnostic |

The subscript-form miss is a real gap (`Column` subscript on a DataFrame
isn't recognized as a column reference; only `col("X")` and `df.X` are).
Worth filling — production PySpark code uses subscript ubiquitously.

## Headline gaps surfaced by these files

1. **`Column` subscript on a DataFrame** (`df["x"]`) isn't checked.
   `basic.py` uses this exclusively in its filter/select examples.

## Files queued for next iteration

- `python/pyspark/sql/tests/test_group.py` (7.7 KB — focused groupBy/agg).
- One MLflow file — to be picked from the ~65 files importing
  `pyspark.sql`.
