# kedro-plugins — probes_negative/

Deliberately-corrupted fixtures derived from
`kedro-datasets/kedro_datasets/spark/spark_dataset.py`'s Weather
demo. Each fixture mirrors a real upstream code shape, then injects
exactly one regression so pykrete must fire a specific diagnostic.

- `unknown_after_cast.pyk` — Weather schema with the
  `.cast(DataFrame[Weather])` re-anchor after `spark.read.load`. Real
  upstream code reads schema-declared columns afterwards; this
  fixture references a column not in `WeatherNeg`, forcing D0030
  (`unknownColumn`).
