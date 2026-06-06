# pykrete-tests

[![cross-codebase](https://github.com/amirnaderi93/pykrete-tests/actions/workflows/cross-codebase.yml/badge.svg)](https://github.com/amirnaderi93/pykrete-tests/actions/workflows/cross-codebase.yml)

## Why cross-codebase testing

pykrete is a strict-superset type checker for PySpark and (as of
v1.3) pandas. To trust it, you need confidence it doesn't choke on
the patterns real Spark and pandas code actually use — not just the
ones we thought to write tests for.

So we test pykrete against real upstream code from **17 codebases**
that together represent the dominant PySpark stack and (as of v1.4)
the dominant pandas stack — ML preprocessing, stats/econometrics,
schema validation, data quality, forecasting, visualization, and
financial market data. Every release runs pykrete over the fixtures
in `cross-codebase/` and the diagnostic output is JSON-compared
against a golden snapshot. A regression in any donor blocks the
release.

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

### PySpark donors (10 — established v1.0 coverage)

| donor | repo | commit | why it's a donor |
|-------|------|--------|------------------|
| **spark** | [apache/spark](https://github.com/apache/spark) | `d004e0d8` | If pykrete works on Spark's own test suite + examples, it works on real Spark code by definition. The standard. |
| **delta** | [delta-io/delta](https://github.com/delta-io/delta) | `3f10aaec` | Delta Lake — the dominant lakehouse storage layer used in production by most teams running Spark today. DataFrameWriter chains, time-travel reads, merge expressions. |
| **kedro-plugins** | [kedro-org/kedro-plugins](https://github.com/kedro-org/kedro-plugins) | `c4c367eb` | Kedro is the most-used Python pipeline framework that wraps Spark. The `kedro-datasets` Spark adapters cover load/save plumbing and Hive upserts (Window + row_number + unionByName). |
| **iceberg-python** | [apache/iceberg-python](https://github.com/apache/iceberg-python) | `5da8186d` | The Apache lakehouse alternative to Delta. Catalog reads, DataFrameWriterV2 (writeTo), Iceberg metadata-view introspection. Hybrid: also carries v1.3 pandas fixtures. |
| **hudi** | [apache/hudi](https://github.com/apache/hudi) | `fc85e3ea` | Uber's lakehouse engine. The PySpark quickstart's soft-delete logic uses `reduce(lambda df, col: df.withColumn(...), ...)` — a hard "closure-over-DataFrame" case real users hit. |
| **mlflow** | [mlflow/mlflow](https://github.com/mlflow/mlflow) | `8f942548` | ML lifecycle infrastructure. `mlflow.pyfunc.spark_udf` is how thousands of teams ship models to Spark batches. Nested struct/array schemas, UDF invocation patterns. Hybrid: also carries v1.3 pandas fixtures. |
| **feast** | [feast-dev/feast](https://github.com/feast-dev/feast) | `4203eb74` | Feature-store reference implementation. Multi-statement `spark.sql` chains, Kafka stream parsing with `F.from_json` / `F.from_avro`, temp-view-based SparkTransformation. Hybrid: also carries v1.3 pandas fixtures. |
| **quinn** | [MrPowers/quinn](https://github.com/MrPowers/quinn) | `20156582` | The most popular community PySpark helper library. Pure `F.*` + Column-builder functions — heavy on `F.regexp_replace`, `F.when().otherwise()`, `F.expr` with SQL strings, `Column.eqNullSafe`. |
| **dbt-spark** | [dbt-labs/dbt-spark](https://github.com/dbt-labs/dbt-spark) | `42700b5d` | dbt's Spark adapter. The Python-model convention (`def model(dbt, spark) -> DataFrame[X]`) is how dbt users write transformations in Python. |
| **python-deequ** | [awslabs/python-deequ](https://github.com/awslabs/python-deequ) | `20693b81` | AWS-built data-quality framework. The `sc.parallelize([Row(...)]).toDF()` pattern + `spark.read.json(sc.parallelize([json_str]))` round-trip is unusual but common across DQ tools. |

### Pandas donors (10 — 3 hybrid carry-over from v1.3 + 7 new in v1.4)

v1.4 splits pandas donors into two scoping classes, called out
explicitly so the coverage claim stays honest:

- **Direct-dispatch (3)** — `annotated/<libname>/...` fixtures track
  the actual upstream library code, with `PandasFrame[X]` annotations
  added and the upstream call sites matched against pykrete's v1.3
  dispatched-shape recognizers (string-literal subscripts, dict-literal
  `rename(columns=…)`, etc.). These donors are the cleanest signal:
  pykrete is checking shapes the library itself uses.
- **Canonical-fixture-only (4)** — `annotated/canonical/...` fixtures
  model how a user idiomatically wields the library at the pandas
  boundary, inspired by the library's API. The upstream code itself
  rarely uses pykrete-dispatched shapes (sklearn / statsmodels operate
  on numpy arrays internally; pandera / GE operate at metric / domain
  layers above raw pandas). The fixtures stand in for what a real user
  writes when consuming each library.
- **Hybrid (3)** — `annotated/<libname>/...` fixtures from the v1.3
  PySpark-primary donors, extended with separate `PandasFrame[X]`
  fixtures (`mlflow/pandas_dataset.pyk`, `feast/pandas_entity_df.pyk`,
  `iceberg-python/pandas_score_dataset.pyk`).

| donor | scoping | repo | commit | why it's a donor |
|-------|---------|------|--------|------------------|
| **mlflow** | hybrid | [mlflow/mlflow](https://github.com/mlflow/mlflow) | `8f942548` | (See PySpark table above.) Pandas surface: `pandas_dataset.pyk` exercises the six dispatched pandas operations on an MLflow-shaped dataset. |
| **feast** | hybrid | [feast-dev/feast](https://github.com/feast-dev/feast) | `4203eb74` | (See PySpark table above.) Pandas surface: `pandas_entity_df.pyk` exercises the dispatched pandas operations on a Feast entity-frame shape. |
| **iceberg-python** | hybrid | [apache/iceberg-python](https://github.com/apache/iceberg-python) | `5da8186d` | (See PySpark table above.) Pandas surface: `pandas_score_dataset.pyk` exercises the dispatched pandas operations on an Iceberg score-dataset shape. |
| **scikit-learn** | canonical-fixture-only | [scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn) | `1.7.x` | The dominant ML stack; `annotated/canonical/preprocessing_pattern.pyk` models how users wield `StandardScaler` / `OneHotEncoder`-style pipelines on a `PandasFrame[X]` boundary. |
| **statsmodels** | canonical-fixture-only | [statsmodels/statsmodels](https://github.com/statsmodels/statsmodels) | `0.14.x` | Canonical stats / econometrics; `annotated/canonical/regression_pattern.pyk` models a typical OLS-style pipeline against a `PandasFrame[X]` regressor frame. |
| **pandera** | canonical-fixture-only | [unionai-oss/pandera](https://github.com/unionai-oss/pandera) | `0.23.x` | Sibling runtime-validation project; pykrete is the static peer. `annotated/canonical/user_validation.pyk` models a pandera-validated pipeline at the static boundary. |
| **great-expectations** | canonical-fixture-only | [great-expectations/great_expectations](https://github.com/great-expectations/great_expectations) | `1.3.x` | Data-quality framework, pandas-first by lineage; `annotated/canonical/expectation_pattern.pyk` models an expectation-suite pipeline at the static boundary. |
| **prophet** | direct-dispatch | [facebook/prophet](https://github.com/facebook/prophet) | `v1.1.6` | Time-series forecasting; canonical `ds` (timestamp) + `y` (float64) schema. Direct-dispatch on `df["new"] = expr` subscript-assigns in `forecaster.py`. |
| **seaborn** | direct-dispatch | [mwaskom/seaborn](https://github.com/mwaskom/seaborn) | `v0.13.2` | Statistical visualization, pandas-first API. Direct-dispatch on `df.rename(columns={…})` dict-literal kwarg in `categorical.py`. |
| **yfinance** | direct-dispatch | [ranaroussi/yfinance](https://github.com/ranaroussi/yfinance) | `0.2.55` | Financial market-data API → pandas DataFrames. Direct-dispatch on `df["new"] = expr`, `df.rename(columns={…})`, and `df.merge(...)` in `utils.py`. |

83 fixtures total across the 17 donors (46 annotated + 37 negative
under `probes_negative/`). Spark contributes eight annotated fixtures
(basic, datasource, streaming wordcount, the four `tests/` files, and
`examples/.../arrow.py` covering `pandas_udf` / `applyInPandas` /
`mapInPandas`); mlflow contributes six (the three
`mlflow.pyfunc.spark_udf` examples,
`tests/spark/autologging/datasource/test_spark_datasource_autologging.py`,
the v1.1 `run_status_enum.pyk` covering MLflow run-status vocabulary
on a Spark DataFrame surface, and the v1.3 `pandas_dataset.pyk`
exercising the `PandasFrame[X]` dispatch on the six pandas operations);
delta and hudi each contribute a v1.1 enum fixture
(`cdc_change_type_enum.pyk` and `cdc_operation_enum.pyk`); feast and
iceberg-python each add a v1.3 `PandasFrame[X]` fixture
(`feast/pandas_entity_df.pyk`, `iceberg-python/pandas_score_dataset.pyk`)
on top of their prior Spark coverage; the seven new v1.4 pandas donors
contribute the remainder.

## What the goldens capture

The golden snapshot for each annotated fixture is the JSON-formatted
diagnostic output pykrete emits today. As of v1.3 the annotated
fixtures that use the canonical `SparkFrame[X]` / `PandasFrame[X]`
forms produce `"diagnostics": []`; fixtures that still use the v1.2
`DataFrame[X]` alias emit one `D0090 deprecatedDataFrameAlias`
warning per annotation, captured in the golden. The v1.3 mass golden
refresh absorbed 48 fixtures' worth of new D0090 warnings; non-D0090
diagnostics on the same fixtures were preserved. The v1.4 mass golden
refresh absorbed two negative-fixture deltas where v1.4's tightened
diagnostic coverage (D0081 `nonNumericArithmetic` and D0082
`crossTypeComparison`) added newly-firing warnings on already-corrupted
inputs (`mlflow/probes_negative/withColumn_arith_on_string.pyk`,
`spark/probes_negative/cross_type_comparison.pyk`) — the additions are
the intended tightening, not regressions, and the positives across the
83-fixture set were unchanged.

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
pykrete from `scripts/diagnostic_catalog.json`'s
`pykreteSourceCommit` pin (mirroring `probes.yml`) and diffs each
fixture's live JSON diagnostic output against its committed
`.golden.json`. Any drift fails the build — that's the
release-blocking contract.

## Schema-tracking probes (v1.4)

Every pykrete release is regression-tested with **223
schema-tracking probes** from the 17 upstream codebases listed above.
The repo vendors **83 fixtures** on disk (46 annotated + 37 negative
under `probes_negative/`); the **223 probes cover 82 of those** (45
annotated + 37 negative — the feast `spark_kafka_processor` streaming
fixture is annotated but probe-free because it has no typed-DataFrame
slot for a probe to anchor to). Probes are inline `# PROBE-*` comment
markers in `.pyk` fixtures that the runner expands into synthetic
checks against `pykrete check --format json`. Positive probes assert
columns resolve cleanly after schema-changing operations (`.select`,
`.filter`, `.withColumn`, plus the pandas analogues
`df[col_list]`, `df[mask]`, `df["new"] = expr`); negative probes
assert specific diagnostics fire on deliberately-corrupted fixtures.

- **180 positive probes** across 45 annotated fixtures verify column
  resolution, post-narrowing flow, and dtype propagation (`PROBE-RESOLVES`
  + `PROBE-TYPE-IS`).
- **43 negative probes** across 37 deliberately-corrupted fixtures
  under `probes_negative/` verify diagnostic firing —
  D0030 `unknownColumn`, D0060 `missingJoinKey` (v1.3), D0081
  `nonNumericArithmetic` (v1.4-widened to subscript-on-name receivers),
  D0082 `crossTypeComparison` (v1.4-widened correspondingly), D0084
  `enumValueMismatch` (v1.1), and D0090 `deprecatedDataFrameAlias`
  (v1.3 — warns on `DataFrame[X]`, removed in v2.0).
- **Enum value vocabulary verification** in 3 of 17 donors —
  Delta CDC `_change_type` (`{"insert", "update_preimage",
  "update_postimage", "delete"}`), Hudi `_hoodie_operation`
  (`{"I", "-U", "U", "D"}`), and MLflow run status
  (`{"RUNNING", "FINISHED", "FAILED", "KILLED", "SCHEDULED"}`).
  Positive probes assert in-vocab literals stay clean in
  `==` / `.isin` / `withColumn` / `F.expr` / `groupBy` chains;
  negative probes assert D0084 fires on off-vocab typos.
- **Spark type-tracking** (v1.2) via the `PROBE-TYPE-IS` synth in
  3 of 17 donors — quinn, MLflow, and python-deequ. The synth wraps
  `{df}.select(col("x") + 1)` around the typed marker so off-claim
  numeric types fall through to D0081 `nonNumericArithmetic`.
- **Pandas type-tracking** (v1.4 — closes #14) via the `PROBE-TYPE-IS`
  synth on `PandasFrame[X]` across 7 of 17 donors — scikit-learn,
  statsmodels, pandera, Great Expectations, prophet, seaborn, and
  yfinance. The synth wraps `{df}.assign(__probe={df}["x"] + 1)` around
  the typed marker (a dispatched pandas op) so off-claim numeric types
  fall through to D0081 `nonNumericArithmetic`. **21 pandas TYPE-IS
  markers** ship across the seven new donors (3 per donor, exactly
  meeting the v1.4 spec §1 floor of ≥3 per donor / ≥21 total). The
  three v1.3 hybrid pandas
  donors (mlflow, feast, iceberg-python) carry zero pandas TYPE-IS
  markers in v1.4 — retrofitting them was deliberately out of scope
  per v1.4 spec §1.
- **v1.4 pandas dialect** — 10 of 17 donors carry pandas fixtures (the
  3 v1.3 hybrid carry-overs plus the 7 v1.4 additions); see the donors
  table above for the per-donor scoping (direct-dispatch /
  canonical-fixture-only / hybrid) so the coverage claim is honest.
- The `probes` workflow runs `scripts/probes_ci.sh` on every push
  and PR; CI fails if any probe asserts the wrong outcome. The
  combined structured JSON report uploads as the `probes-report`
  artifact for postmortem inspection.

What we do **not** yet verify (deferred to v1.5+):

- **Cross-dialect handoff annotations** (`.toPandas()`, `.toSpark()`,
  `pd.DataFrame.from_records(...)`). v1.4 covers depth on annotated
  frames, not boundary recognition.
- **`df.query("…")` / `df.eval("…")` mini-DSLs** — own design surface;
  parse string-fragment column refs separately.
- **Broader pandas method modeling** (`pivot_table`, `groupby.agg`,
  `melt`, `stack` / `unstack`, `reset_index`, `set_index`).
- **`pd.read_csv(...)` + other I/O entry points** — schema inference
  from file headers / SQL / type-stubs is a separate design.
- **`PROBE-TYPE-IS` synth-shape coverage beyond D0081 (Spark side).**
  D0080 (`returnTypeMismatch`) and D0082 (`crossTypeComparison`)
  need their own synth shapes; raw-mutation fixtures cover them
  in the interim.
- **Numeric-subtype distinguishability** (e.g. `int` vs `long` vs
  `double` arithmetic narrowing).
- **withColumn output enum-constraint preservation** — pykrete checks
  the literal against the sink's enum vocabulary, but the constraint
  drops on the output column. Tracker in pykrete's
  `docs/design/literal-value-vocabulary.md` polish backlog.

A weekly `catalog-drift-watch` workflow polls pykrete-core's `main`
and opens a `chore(catalog): refresh from pykrete <sha>` PR when
new D-codes appear, so `PROBE-EXPECTS` validation stays in sync
with upstream. Trigger it manually from the Actions tab to verify
end-to-end.

See [`scripts/PROBES.md`](scripts/PROBES.md) for marker syntax,
running locally, and the drift-watch contract.

## License attribution

All 17 donors are open-source under permissive licenses (Apache 2.0,
BSD-3-Clause, or MIT). License files are reproduced verbatim under
each donor's `LICENSE-UPSTREAM`. Each fixture file preserves the
upstream license header at the top.

Annotations and tooling in this repo are MIT-licensed — see
[LICENSE](LICENSE). Vendoring is for testing purposes; canonical
sources stay upstream.
