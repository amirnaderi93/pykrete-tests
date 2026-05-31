# feast — probes_negative/

Deliberately-corrupted fixtures derived from Feast's Spark
transformation surface (`feast/transformation/spark_transformation
.py`). Each fixture mirrors a real upstream code shape, then injects
exactly one regression so pykrete must fire a specific diagnostic.

- `unknown_feature_ref.pyk` — FeatureRow schema (entity_id, value).
  Real upstream code treats the dataframe as an opaque container for
  `createOrReplaceTempView`; this fixture references a feature column
  not in the schema, forcing D0030 (`unknownColumn`).
