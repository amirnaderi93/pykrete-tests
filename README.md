# pykrete-tests

[![cross-codebase](https://github.com/amirnaderi93/pykrete-tests/actions/workflows/cross-codebase.yml/badge.svg)](https://github.com/amirnaderi93/pykrete-tests/actions/workflows/cross-codebase.yml)

## Why cross-codebase testing

pykrete is a strict-superset type checker for PySpark and (as of
v1.3) pandas. To trust it, you need confidence it doesn't choke on
the patterns real Spark and pandas code actually use — not just the
ones we thought to write tests for.

So we test pykrete against real upstream code from 10 codebases that
together represent the dominant PySpark stack and (in 3 of them, as
of v1.3) typical pandas usage in the same projects. Every release
runs pykrete over the fixtures in `cross-codebase/` and the
diagnostic output is JSON-compared against a golden snapshot. A
regression in any donor blocks the release.

## The donors

Each donor lives under `cross-codebase/<donor>/` with:

- `upstream/<original-path>/<file>.pyk` — verbatim upstream Python
  source with the `.py` → `.pyk` extension rename. `.pyk` is a
  strict superset of Python, so the rename is zero-behavior-change.
  License header preserved at the top.
- `annotated/<original-path>/<file>.pyk` — same code with pykrete
  `class X(Schema)` declarations and typed-helper wrappers added.
  All bodies of upstream helpers retained for traceability.
- `annotated/<original-path>/<file>.golden.json` — JSON-formatted
  `pykrete check --format json` output, normalized for portability
  (see `scripts/golden.sh`). CI diffs the live output against this
  on every push.
- `LICENSE-UPSTREAM` — donor's license file.
- `pinned-commit` — the upstream commit each `upstream/` and
  `annotated/` file is faithful to.

| donor | repo | commit | why it's a donor |
|-------|------|--------|------------------|
| **spark** | [apache/spark](https://github.com/apache/spark) | `d004e0d8` | If pykrete works on Spark's own test suite + examples, it works on real Spark code by definition. The standard. |
| **delta** | [delta-io/delta](https://github.com/delta-io/delta) | `3f10aaec` | Delta Lake — the dominant lakehouse storage layer used in production by most teams running Spark today. DataFrameWriter chains, time-travel reads, merge expressions. |
| **kedro-plugins** | [kedro-org/kedro-plugins](https://github.com/kedro-org/kedro-plugins) | `c4c367eb` | Kedro is the most-used Python pipeline framework that wraps Spark. The `kedro-datasets` Spark adapters cover load/save plumbing and Hive upserts (Window + row_number + unionByName). |
| **iceberg-python** | [apache/iceberg-python](https://github.com/apache/iceberg-python) | `5da8186d` | The Apache lakehouse alternative to Delta. Catalog reads, DataFrameWriterV2 (writeTo), Iceberg metadata-view introspection. |
| **hudi** | [apache/hudi](https://github.com/apache/hudi) | `fc85e3ea` | Uber's lakehouse engine. The PySpark quickstart's soft-delete logic uses `reduce(lambda df, col: df.withColumn(...), ...)` — a hard "closure-over-DataFrame" case real users hit. |
| **mlflow** | [mlflow/mlflow](https://github.com/mlflow/mlflow) | `8f942548` | ML lifecycle infrastructure. `mlflow.pyfunc.spark_udf` is how thousands of teams ship models to Spark batches. Nested struct/array schemas, UDF invocation patterns. |
| **feast** | [feast-dev/feast](https://github.com/feast-dev/feast) | `4203eb74` | Feature-store reference implementation. Multi-statement `spark.sql` chains, Kafka stream parsing with `F.from_json` / `F.from_avro`, temp-view-based SparkTransformation. |
| **quinn** | [MrPowers/quinn](https://github.com/MrPowers/quinn) | `20156582` | The most popular community PySpark helper library. Pure `F.*` + Column-builder functions — heavy on `F.regexp_replace`, `F.when().otherwise()`, `F.expr` with SQL strings, `Column.eqNullSafe`. |
| **dbt-spark** | [dbt-labs/dbt-spark](https://github.com/dbt-labs/dbt-spark) | `42700b5d` | dbt's Spark adapter. The Python-model convention (`def model(dbt, spark) -> DataFrame[X]`) is how dbt users write transformations in Python. |
| **python-deequ** | [awslabs/python-deequ](https://github.com/awslabs/python-deequ) | `20693b81` | AWS-built data-quality framework. The `sc.parallelize([Row(...)]).toDF()` pattern + `spark.read.json(sc.parallelize([json_str]))` round-trip is unusual but common across DQ tools. |

38 annotated fixtures total across the 10 donors. Spark contributes
eight (basic, datasource, streaming wordcount, the four `tests/`
files, and `examples/.../arrow.py` covering `pandas_udf` /
`applyInPandas` / `mapInPandas`); mlflow contributes six (the three
`mlflow.pyfunc.spark_udf` examples,
`tests/spark/autologging/datasource/test_spark_datasource_autologging.py`,
the v1.1 `run_status_enum.pyk` covering MLflow run-status vocabulary
on a Spark DataFrame surface, and the v1.3 `pandas_eval_dataset.pyk`
exercising the `PandasFrame[X]` dispatch on the six pandas
operations); delta and hudi each contribute a v1.1 enum fixture
(`cdc_change_type_enum.pyk` and `cdc_operation_enum.pyk`); feast and
iceberg-python each contribute a v1.3 `PandasFrame[X]` fixture;
the remaining donors contribute the rest.

## What the goldens capture

The golden snapshot for each annotated fixture is the JSON-formatted
diagnostic output pykrete emits today. As of v1.3 the annotated
fixtures that use the canonical `SparkFrame[X]` / `PandasFrame[X]`
forms produce `"diagnostics": []`; fixtures that still use the v1.2
`DataFrame[X]` alias emit one `D0090 deprecatedDataFrameAlias`
warning per annotation, captured in the golden. The v1.3 mass
golden refresh absorbed 48 fixtures' worth of new D0090 warnings;
non-D0090 diagnostics on the same fixtures were preserved. The v1.0
goldens carried six fixtures with v0.1.37 false positives, all
closed by v0.1.39. The v1.1 enum fixtures
(`delta/cdc_change_type_enum.pyk`, `hudi/cdc_operation_enum.pyk`,
`mlflow/run_status_enum.pyk`) and the v1.3 pandas fixtures
(`mlflow/pandas_dataset.pyk`, `feast/pandas_entity_df.pyk`,
`iceberg-python/pandas_score_dataset.pyk`) ship against the same
contract.

The contract is "no diff against the committed golden". When pykrete
behavior changes the contributor regenerates the affected goldens in
the same PR — the diff makes the change visible, whether it's an
improvement or a regression.

## What this suite does NOT cover

Real-world donor code doesn't exercise pykrete's full surface area.
~30 individual `F.*` functions, `melt` / `cube` / `rollup`,
Schema arithmetic operators, and the v0.1.28+ atomic-type aliases
(`byte`, `short`, `decimal(p, s)`, `binary`) are not yet represented
by any donor fixture. Those features are covered by synthetic unit
tests in the main repo at
[`pykrete/crates/pykrete/tests/`](https://github.com/amirnaderi93/pykrete/tree/main/crates/pykrete/tests).

The two tiers complement each other: real-world donors prove pykrete
keeps working on production patterns; synthetic unit tests prove
each individual feature surface behaves to spec.

## Updating donors

Each donor's `pinned-commit` is part of the cross-codebase contract.
Don't bump it casually — when pykrete diagnostics change, the pinned
commit, the annotated companion, and the golden all move together.
Bumping just the upstream means the annotated file might no longer
reflect the real upstream code.

Procedure for a donor bump:

```bash
# 1. Fetch the new upstream pinned-commit and replace upstream/.
#    Re-derive the annotated companion against the new upstream code.
# 2. Regenerate the golden:
scripts/golden.sh generate /path/to/pykrete
# 3. git diff cross-codebase/<donor>/  # review every change
# 4. Update cross-codebase/<donor>/pinned-commit to the new SHA.
# 5. Commit upstream + annotated + golden + pinned-commit together.
```

See `scripts/update-pinned-commit.sh` for a starting harness.

## CI

`cross-codebase.yml` runs on every push, PR, and nightly. It builds
pykrete from `main` and diffs each fixture's live JSON diagnostic
output against its committed `.golden.json`. Any drift fails the
build — that's the release-blocking contract.

## Schema-tracking probes (v1.3)

Every pykrete release is regression-tested with **149
schema-tracking probes** from 10 upstream codebases — Apache Spark,
Delta Lake, Apache Iceberg (iceberg-python), Apache Hudi, MLflow,
Feast, Kedro (kedro-plugins), quinn, dbt-spark, and python-deequ.
The repo vendors **59 fixtures** on disk (38 annotated + 21 negative
under `probes_negative/`); the **149 probes cover 58 of those** (37
annotated + 21 negative — the feast `spark_kafka_processor` streaming
fixture is annotated but probe-free because it has no typed-DataFrame
slot for a probe to anchor to). Probes are inline `# PROBE-*` comment
markers in `.pyk` fixtures that the runner expands into synthetic
checks against `pykrete check --format json`. Positive probes assert
columns resolve cleanly after schema-changing operations (`.select`,
`.filter`, `.withColumn`, plus the v1.3 pandas analogues
`df[col_list]`, `df[mask]`, `df["new"] = expr`); negative probes
assert specific diagnostics fire on deliberately-corrupted fixtures.

- **122 positive probes** across 37 of the 38 annotated fixtures
  verify column resolution and post-narrowing flow.
- **27 negative probes** across all 21 deliberately-corrupted
  fixtures under `probes_negative/` verify diagnostic firing —
  D0030 `unknownColumn`, D0081 `nonNumericArithmetic`, D0082
  `crossTypeComparison`, D0084 `enumValueMismatch` (added v1.1),
  and **D0090 `deprecatedDataFrameAlias`** (new in v1.3 — warns
  on `DataFrame[X]`, removed in v2.0).
- **Enum value vocabulary verification** in 3 of 10 donors —
  Delta CDC `_change_type` (`{"insert", "update_preimage",
  "update_postimage", "delete"}`), Hudi `_hoodie_operation`
  (`{"I", "-U", "U", "D"}`), and MLflow run status
  (`{"RUNNING", "FINISHED", "FAILED", "KILLED", "SCHEDULED"}`).
  Positive probes assert in-vocab literals stay clean in
  `==` / `.isin` / `withColumn` / `F.expr` / `groupBy` chains;
  negative probes assert D0084 fires on off-vocab typos.
- **Spark `PROBE-TYPE-IS` type-tracking** (shipped v1.2) in 3 of
  10 donors — quinn, mlflow, and python-deequ — assert column
  types propagate through `.select` / `.withColumn` / `.filter`
  chains. Off-claim markers fire D0081 via the synth shape; a CI
  gate mutates the claimed type on every marker and verifies the
  diagnostic fires.
- **Pandas check-site coverage** (new in v1.3) in 3 of 10 donors —
  mlflow, feast, and iceberg-python — exercise the six dispatched
  pandas operations (column selection, boolean-mask filtering,
  assignment, drop, merge, rename) on `PandasFrame[X]` annotations,
  paired with `probes_negative/` counterparts asserting D0030 on
  bare `df["typo"]` and D0090 on the deprecated `DataFrame[X]`
  alias.
- The `probes` workflow runs `scripts/probes_ci.sh` on every push
  and PR; CI fails if any probe asserts the wrong outcome. The
  combined structured JSON report uploads as the `probes-report`
  artifact for postmortem inspection.

What we do **not** yet verify (deferred to v1.4):

- **Positive `PROBE-TYPE-IS` coverage on `PandasFrame[X]`.** v1.3
  ships pandas check-site coverage; positive type-tracking probes
  for pandas land in v1.4 — parallel to how v1.2 added Spark
  type-tracking after v1.1 introduced Spark column tracking.
  Tracker: [#14](https://github.com/amirnaderi93/pykrete-tests/issues/14).
- **`PROBE-TYPE-IS` synth-shape coverage beyond D0081 (Spark side).**
  D0080 (`returnTypeMismatch`) and D0082 (`crossTypeComparison`)
  need their own synth shapes; raw-mutation fixtures cover them
  in the interim.
- Numeric-subtype distinguishability (e.g. `int` vs `long` vs
  `double` arithmetic narrowing).
- withColumn output enum-constraint preservation — pykrete checks
  the literal against the sink's enum vocabulary, but the
  constraint drops on the output column. Tracker in pykrete's
  `docs/design/literal-value-vocabulary.md` polish backlog.

A weekly `catalog-drift-watch` workflow polls pykrete-core's `main`
and opens a `chore(catalog): refresh from pykrete <sha>` PR when
new D-codes appear, so `PROBE-EXPECTS` validation stays in sync
with upstream. Trigger it manually from the Actions tab to verify
end-to-end.

See [`scripts/PROBES.md`](scripts/PROBES.md) for marker syntax,
running locally, and the drift-watch contract.

## License attribution

All 10 donors are Apache 2.0. License files are reproduced verbatim
under each donor's `LICENSE-UPSTREAM`. Each fixture file preserves
the upstream license header at the top.

Annotations and tooling in this repo are MIT-licensed — see
[LICENSE](LICENSE). Vendoring is for testing purposes; canonical
sources stay upstream.
