# delta — probes_negative/

Deliberately-corrupted fixtures derived from Delta Lake's PySpark
quickstart (`examples/python/quickstart.py`). Each fixture mirrors a
real upstream code shape, then injects exactly one regression so
pykrete must fire a specific diagnostic.

- `unknown_column_after_load.pyk` — IdRow schema with the
  `.cast(DataFrame[IdRow])` re-anchor after the opaque Delta load.
  Real upstream code reads `id` after the cast; this fixture
  references a column not present in `IdRowNeg`, forcing D0030
  (`unknownColumn`).
- `cdc_change_type_off_vocab_eq.pyk` — StudentCDC shape from the
  Delta Change Data Feed pattern (sibling
  `annotated/examples/python/cdc_change_type_enum.pyk`). The
  `_change_type` column is `enum["insert", "update_preimage",
  "update_postimage", "delete"]`; this fixture typos `'isnert'`
  in an `== lit(...)` filter, forcing D0084 (`enumValueMismatch`).
