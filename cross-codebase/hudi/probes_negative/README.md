# hudi — probes_negative/

Deliberately-corrupted fixtures derived from Hudi's PySpark quickstart
and CDC-emitter surface. Each fixture mirrors a real upstream schema
shape, then injects exactly one regression so pykrete must fire a
specific diagnostic.

- `cdc_operation_off_vocab_isin.pyk` — HudiCDCTripNeg shape from the
  Hudi CDC pattern (sibling
  `annotated/hudi-examples/.../cdc_operation_enum.pyk`). The
  `_hoodie_operation` column is `enum["I", "-U", "U", "D"]` — the
  authentic per-row vocabulary per apache/hudi `HoodieOperation.java`
  (Insert / Update-pre / Update-post / Delete). This fixture typos the
  lowercased `'-u'` inside an `.isin(...)` call, forcing D0084
  (`enumValueMismatch`) with Levenshtein-closest suggestion `'-U'`.
