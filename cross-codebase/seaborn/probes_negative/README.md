# seaborn — probes_negative/

Deliberately-corrupted fixtures derived from the seaborn relational
+ categorical surfaces (`seaborn/relational.py` axis-rename idiom,
`seaborn/categorical.py:L79` dict-literal rename). Each fixture
mirrors a real upstream code shape, then injects exactly one
regression so pykrete must fire a specific diagnostic.

- `pandas_typo_in_rename.pyk` — TidyDataNeg shape from the sibling
  `annotated/seaborn/relational.pyk axis_rename_then_select`. The
  rename source key `x_rwa` (transposition of `x_raw`) doesn't
  match the receiver schema, so `x` is never bound on the renamed
  view; the post-rename `plot_data["x"]` Subscript fires D0030
  (`unknownColumn`) via piece (b)'s col-ref check on the rebound
  schema.
- `pandas_merge_unknown_key.pyk` — TidyDataMergeNeg +
  MetaFrameMergeNeg shapes mirroring `merge_metadata_then_select`.
  The `on="unit_id"` join key exists on the left frame but is
  absent from MetaFrameMergeNeg, so the v1.3 join-key check fires
  D0060 (`missingJoinKey`) on the right side via the .merge(...)
  dispatch.
- `pandas_dataframe_alias.pyk` — TidyDataDep shape from the
  sibling annotated/seaborn/relational.pyk; uses the deprecated
  `DataFrame[X]` alias on a parameter slot, firing D0090
  (`deprecatedDataFrameAlias`) per pandas-support.md §6.
- `pandas_pivot_table_unknown_values.pyk` — v1.6 PR-D1 negative-space
  probe. TidyDataPivotNeg mirrors the relational TidyData schema;
  `df.pivot_table(index="hue_raw", columns="unit_id", values="x_rwa")`
  where `x_rwa` is a transposition of `x_raw`. The v1.6 PR-D1
  pandas `pivot_table` literal-form arm validates each literal name
  on the receiver schema and fires D0030 against TidyDataPivotNeg.
  Shape divergence: seaborn's library source does not literally call
  `DataFrame.pivot_table` (grep returns 0 hits); the fixture captures
  the seaborn-USER reshape idiom (tidy → wide before sns.heatmap)
  exercising the v1.6 PR-D1 arm specifically.
- `arg_schema_mismatch.pyk` — v1.7 PR-P1 shape-rule probe. Mirrors
  the seaborn-USER plot-input helper pattern where a function
  expects a tidy axis frame `PandasFrame[TidyData]` but a caller
  passes the `PandasFrame[MetaFrame]` metadata frame instead.
  `check_one_call_arg` at `operations/expr.rs:2367` fires D0051
  (argumentColumnsMismatch) on the argument range when parameter /
  argument field-name sets disagree.
