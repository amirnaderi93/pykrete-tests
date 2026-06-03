# mlflow — probes_negative/

Deliberately-corrupted fixtures derived from MLflow's Spark dataset
surface (`mlflow/data/spark_dataset.py`, the eval-dataset shape) plus
v1.3 pandas additions distilled from `mlflow/data/pandas_dataset.py`'s
`to_pyfunc()` shape. Each fixture mirrors a real upstream code shape,
then injects exactly one regression so pykrete must fire a specific
diagnostic.

`withColumn_arith_on_string.pyk` runs under **strict mode** (sibling
`pykrete.json` sets `typeCheckingMode: "strict"`);
`select_then_unknown.pyk` inherits the same config because they share
a directory. See the "Strict-mode caveat" subsection of
`scripts/PROBES.md` before adding new fixtures.

- `select_then_unknown.pyk` — TrainRow schema from MLflow's
  validate-columns demo. Narrows to `feature_a`, then references the
  dropped `target` column, forcing D0030 (`unknownColumn`).
- `withColumn_arith_on_string.pyk` — LabelledRow shape with a string
  `label` column. Adds `label + target` arithmetic, forcing D0081
  (`nonNumericArith`, strict mode).
- `run_status_off_vocab_fillna.pyk` — RunInfoNeg shape from the
  MLflow run-tracking pattern (sibling
  `annotated/mlflow/data/run_status_enum.pyk`). The `status` column
  is `enum["RUNNING", "FINISHED", "FAILED", "KILLED", "SCHEDULED"]`;
  this fixture writes `'UKNOWN'` via `.fillna({"status": ...})`,
  forcing D0084 (`enumValueMismatch`).
- `pandas_bare_subscript_unknown.pyk` — TrainRowNeg shape from
  `mlflow/data/pandas_dataset.py` `to_pyfunc()` (upstream L117-L126);
  uses a `PandasFrame[TrainRowNeg]` receiver and references `targt`
  (typo of `target`) via bare `df["targt"]`, forcing D0030
  (`unknownColumn`) via the v1.3 piece-(b) bare-Subscript col-ref
  entry point.
- `pandas_assign_subscript_unknown.pyk` — TrainRowAssignNeg shape;
  exercises the §5 "Column add / replace" dispatch row in its pandas
  form `df["new"] = df["typo"]`. The RHS Subscript references `targt`
  (typo of `target`), forcing D0030 (`unknownColumn`) via piece (b).
- `pandas_dataframe_alias_deprecated.pyk` — TrainRowDep shape; uses
  the deprecated `DataFrame[X]` alias on a parameter slot, forcing
  D0090 (`deprecatedDataFrameAlias`) per
  `docs/design/pandas-support.md` §6.
