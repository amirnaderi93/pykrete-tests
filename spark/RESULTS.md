# Spark — pykrete results

Per-file diagnostics from running `pykrete check` over the vendored Apache
Spark sources after pykrete annotations were added. Regenerated on every CI
run (once that's wired); for now updated by hand alongside pilots.

**pykrete version:** main @ `c25fe5c` (post-pilot-2 fix landed)
**upstream commit:** [`c3096ee`](https://github.com/apache/spark/tree/c3096ee570572f385a409d07988e7a75c524ecd1)
**run date:** 2026-05-21

## Files exercised

### `examples/src/main/python/sql/basic.py` — pilot 1

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

### `python/pyspark/sql/tests/test_group.py` — pilot 2

The PySpark sql test for groupBy/agg semantics. 207 lines, six test
methods on `GroupTestsMixin` covering shortcut aggregates (`g.max/min/
sum/count/mean`), pivot, `groupBy` by ordinal, nested-struct
aggregation, `orderBy` by ordinal, and pivot's max-values guardrail.

**Annotations added** (kept minimal):

- Four schemas matching the test data shapes:
  - `KV(key: int, value: int)`
  - `Sales(electronic: string, year: int, sales: int)`
  - `C(c: int)` and `NestedAB(a: string, b: C)` — `b` is a struct,
    expressed in pykrete as a sibling Schema referenced as a field type.
- Four module-level helpers carrying the dataframe-typed cores of the
  most representative test methods:
  - `agg_func_demo(df: DataFrame[KV])` — `g.max/min/sum/count/mean`.
  - `pivot_demo(df: DataFrame[Sales])` — `.pivot(col, [values])` and
    `.pivot(col)` without values.
  - `aggregator_demo(df: DataFrame[KV])` — empty-key `groupBy()` plus
    `F.first/last/approx_count_distinct/countDistinct`, exercising both
    `df["x"]` subscript and `df.x` attribute-access column refs.
  - `nested_agg_demo(df: DataFrame[NestedAB])` — dotted `"b.c"` path
    into a nested struct via the GroupedData shortcut.
- The original `GroupTestsMixin` class is kept verbatim below the
  helpers for traceability. pykrete doesn't enter its method bodies
  (they take `self`, not `DataFrame[X]`); the helpers above are the
  observable surface.

**Result on the unmodified annotated file:**

```
4 schema(s), 4 typed function(s), 0 issue(s)
```

Clean — no false positives.

**Probes** (planted bugs):

| Typo planted | pykrete output |
|---|---|
| `g.max("vlaue")` (bare-string arg to GroupedData shortcut) | ✅ `D0030 unknownColumn: Column 'vlaue' does not exist on schema 'KV'` |
| `g.max("b.cc")` (dotted nested ref through shortcut) | ✅ `D0030 unknownColumn: Column 'cc' does not exist on schema 'C'. Did you mean 'c'?` |

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

2. **GroupedData shortcut aggregates didn't check their column args.**
   `g.max("col") / g.min(...) / g.sum(...) / g.mean(...) / g.avg(...)`
   are sugar for `g.agg(F.<method>(col))` but bypassed the agg-arg
   handler entirely; typos like `g.max("vlaue")` and dotted typos like
   `g.max("b.cc")` slipped past silently. **Fixed** in pykrete commit
   [`c25fe5c`](https://github.com/amirnaderi93/pykrete/commit/c25fe5c) —
   the receiver-Grouped + shortcut-method case now walks each
   string-literal arg through `resolve_path` against the underlying
   schema, the same way `pivot` does. Dotted nested refs work the same
   as `col("b.c")`. 7 regression tests added to
   [`tests/groupby_agg.rs`](https://github.com/amirnaderi93/pykrete/blob/main/crates/pykrete/tests/groupby_agg.rs).

## Files queued for next iteration

- One MLflow file — to be picked from the ~65 files importing
  `pyspark.sql`.
