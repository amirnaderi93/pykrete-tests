# Spark — pykrete results

Per-file diagnostics from running `pykrete check` over the vendored Apache
Spark sources after pykrete annotations were added. Regenerated on every CI
run (once that's wired); for now updated by hand alongside pilots.

**pykrete version:** main @ `9a49bf6` (post-pilot-5 fix landed)
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

### `python/pyspark/sql/tests/test_column.py` — pilot 4

PySpark's test suite for `Column` object methods. 616 lines, ~34 test
methods covering arithmetic, comparison, predicate, and string
operators on Column refs; nested-struct field access via three syntactic
forms; `Column.withField` / `Column.dropFields`; alias / cast /
metadata; bitwise ops; self-joins.

**Annotations added** (kept minimal):

- Six schemas matching the test data shapes:
  - `KV(key: int, value: string)` — the standard `self.df` of
    ReusedSQLTestCase.
  - `R(a: int, b: string)` + `LRD(l: int, r: R, d: int)` — the
    nested-struct shape from `test_field_accessor` / `test_with_field`
    / `test_drop_fields`. (Array and map element types are abstracted
    as `int` since pykrete v0.1 doesn't yet model the inner element
    types of `array<…>` / `map<…>`.)
  - `AB(a: int, b: int)` — self-join shape.
  - `ABC(colA, colB, colC: string)` + `CDE(colC, colD, colE: string)` —
    the join-with-Column-equality shape from `test_drop_notexistent_col`.
- Eight module-level helpers carrying the dataframe-typed cores: column
  arithmetic+predicate ops, basic select, integer subscript demo,
  nested-field access (all three forms), Column.withField,
  Column.dropFields, self-join, and join+when+drop.

**Result on the unmodified annotated file:**

```
6 schema(s), 8 typed function(s), 0 issue(s)
```

Clean — no false positives.

**Probes** (planted bugs):

| Typo planted | pykrete output |
|---|---|
| `df.r.typo` (chained attribute on nested struct) | ✅ (after fix) `D0030 unknownColumn: Column 'typo' does not exist on schema 'R'` |
| `df.r["typo"]` (attr then subscript) | ✅ (after fix) same |
| `df["r"].typo` (subscript then attr) | ✅ (after fix) same |
| `df["r"]["typo"]` (double subscript) | ✅ (after fix) same |
| `df["r.typo"]` (top-level dotted string — already worked pre-fix) | ✅ same |
| `df[2]` (integer subscript out of range, df has 2 cols) | ❌ not yet flagged — queued (see below) |
| `df["a"].dropFields("typo")` (typo on nested-struct field via Column.dropFields) | ❌ not yet flagged — queued (see below) |

### `examples/src/main/python/sql/arrow.py` — pilot 5

PySpark's Arrow + pandas_udf usage example, the canonical doc-tutorial
for vectorized UDFs. 345 lines, ten example functions covering
PyArrow-table interop, four pandas_udf signatures (series→frame,
series→series, iter[series]→iter[series], iter[tuple[series]]→
iter[series], series→scalar with Window), `applyInPandas`,
`mapInPandas`, cogrouped `applyInPandas`, and two `@udf` shapes.

**Annotations added** (kept minimal):

- Eight schemas matching the data shapes used by the examples:
  - `Inner(col1: string)` + `LongStringStruct(long_col, string_col,
    struct_col: Inner)` — the struct-column shape from
    `ser_to_frame_pandas_udf_example`.
  - `X(x: long)` — single-column long for iter_ser/iter_sers/ser_to_ser.
  - `IdV(id: int, v: double)` — for ser_to_scalar (groupby + Window)
    and grouped_apply_in_pandas.
  - `IdAge(id, age: int)` — for mapInPandas.
  - `TimeIdV1` + `TimeIdV2` — cogrouped applyInPandas's two inputs.
  - `IdNameAge(id, name, age)` — arrow_python_udf.
- Nine module-level helpers extracting the dataframe-typed cores of
  the most representative example bodies.

**Result on the unmodified annotated file:**

```
8 schema(s), 9 typed function(s), 0 issue(s)
```

Clean — no false positives.

**Probes** (planted bugs):

| Typo planted | pykrete output |
|---|---|
| `df.select(mean_udf(df["typoval"]))` (pandas_udf inner arg) | ✅ `D0030 unknownColumn: Column 'typoval' does not exist on schema 'IdV'` |
| `df.groupby("ido").agg(mean_udf(df["v"]))` (lowercase groupby key) | ✅ (after fix) `D0030 ... Did you mean 'id'?` |
| `df.groupby("ido").applyInPandas(...)` (lowercase groupby key) | ✅ (after fix) same |
| `df1.groupby("typo").cogroup(df2.groupby("id")).applyInPandas(...)` (cogroup left key) | ✅ (after fix) `D0030 ... 'typo' does not exist on schema 'TimeIdV1'` |
| `w = Window.partitionBy("ido")` (Window key typo) | ❌ not yet flagged — queued |

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

3. **Chained Column-on-Column nested-field access wasn't checked.**
   Spark resolves `df.r.X` / `df["r"].X` / `df.r["X"]` / `df["r"]["X"]`
   by lifting `r` to a Column (the nested struct) and accessing `X`
   on it. Pykrete recorded only the first step (`r`) and dropped the
   second — a typo on the nested field slipped past silently. (The
   dotted-string form `df["r.X"]` already worked via `resolve_path`.)
   **Fixed** in pykrete commit
   [`0b70d9c`](https://github.com/amirnaderi93/pykrete/commit/0b70d9c) —
   a new `check_chained_field_access` walker extracts the chain
   bottoming out at a DataFrame-bound Name and walks each segment
   segment-by-segment, descending into nested `Declared` schemas as
   it goes. Diagnostic names the nested schema (`Column 'typo' does
   not exist on schema 'R'`), not the outer one. Method calls
   (`df["r"].withField(...)`) correctly skipped so 'withField' isn't
   flagged as a missing field. 8 regression tests added to
   [`tests/dotted_columns.rs`](https://github.com/amirnaderi93/pykrete/blob/main/crates/pykrete/tests/dotted_columns.rs).

4. **Lowercase `groupby` alias wasn't wired in.**
   PySpark accepts both `df.groupBy(...)` (the camelCase form) and
   `df.groupby(...)` (lowercase) with identical semantics. Real
   doc-tutorial code uses the lowercase form exclusively (the
   arrow.py example here does). pykrete only had `groupBy` in
   `column_method_shape` and `apply_method` — a typo on the groupby
   key with lowercase slipped past silently, and downstream pivot /
   shortcut-aggregate checks were also skipped. **Fixed** in pykrete
   commit
   [`9a49bf6`](https://github.com/amirnaderi93/pykrete/commit/9a49bf6) —
   `groupby` is now treated identically to `groupBy` in both arms.
   4 regression tests added to
   [`tests/groupby_agg.rs`](https://github.com/amirnaderi93/pykrete/blob/main/crates/pykrete/tests/groupby_agg.rs).

## Gaps surfaced but queued for a later iteration

These are real but lower-priority — mostly require type-tracking
beyond what pykrete v0.1 currently models (Column-expression types,
Window objects as locals).

- **`Window.partitionBy("typo")` / `.orderBy("typo")`** — Window keys
  aren't checked against any DataFrame schema. Common pattern:
  `w = Window.partitionBy("city").orderBy("ts"); df.withColumn(...).over(w)`.
  Needs local-binding tracking for Window objects, then resolution
  of the keys against the schema at the `.over(w)` site.
- **`df[N]` integer subscript out-of-bounds.** `df[0]` returns the
  first column; `df[N]` for `N >= len(df.columns)` raises `IndexError`
  at runtime. Static-bounds check is doable but rare in real code.
- **`Column.withField("typo", …)` adding to a struct.** Adding a new
  field is intentional in Spark, so this isn't always a typo — but a
  warn-mode hint when "typo" looks suspiciously close to an existing
  field name would be useful.
- **`Column.dropFields("typo")`** dropping a nonexistent nested
  field. Spark errors at runtime; needs Column-expression type
  tracking to verify the nested-struct shape of the receiver.

## Files queued for next iteration

- Another representative file — to be picked. The chained-access fix
  expands pykrete's coverage of the Column-method surface; pilots 5+
  should push toward joins, window functions, or
  `pandas_udf` / `mapInPandas` patterns where the audit still flags
  open gaps.
