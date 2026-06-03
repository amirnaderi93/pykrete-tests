# feast — probes_negative/

Deliberately-corrupted fixtures derived from Feast's Spark
transformation surface (`feast/transformation/spark_transformation
.py`). Each fixture mirrors a real upstream code shape, then injects
exactly one regression so pykrete must fire a specific diagnostic.

- `unknown_feature_ref.pyk` — FeatureRow schema (entity_id, value).
  Real upstream code treats the dataframe as an opaque container for
  `createOrReplaceTempView`; this fixture references a feature column
  not in the schema, forcing D0030 (`unknownColumn`).
- `pandas_list_projection_unknown.pyk` — EntityRowNeg shape distilled
  from Feast's `feature_store.py` L1949-L1959
  (`all_sources_combined_df[entity_df_cols]`); uses
  `PandasFrame[EntityRowNeg]` and references `driverr_id` (typo of
  `driver_id`) inside a list-of-literal Subscript, forcing D0030 via
  the v1.3 piece-(b) List-element entry point.
- `pandas_boolean_mask_unknown.pyk` — same EntityRowNeg shape; the
  boolean-mask filter `df[df["costomer_id"] == "abc"]` exercises the
  §5 boolean-mask Subscript row — the inner `df["costomer_id"]`
  Subscript fires D0030 via piece (b) descending into the mask
  expression.
- `pandas_dataframe_alias_deprecated.pyk` — EntityRowDep shape; uses
  the deprecated `DataFrame[X]` alias on a parameter slot, forcing
  D0090 (`deprecatedDataFrameAlias`) per
  `docs/design/pandas-support.md` §6.
