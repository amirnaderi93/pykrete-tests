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
