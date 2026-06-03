# iceberg-python — probes_negative/

Deliberately-corrupted fixtures derived from PyIceberg's
`tests/integration/test_writes/test_writes.py` per-test pandas-frame
build path (upstream L1875-L1885 + L1894 delete-condition).
Each fixture mirrors a real upstream code shape, then injects exactly
one regression so pykrete must fire a specific diagnostic via the
v1.3 `PandasFrame[X]` check sites.

- `pandas_merge_unknown_key.pyk` — ScoreRowNeg shape; exercises the
  pandas `.merge(other, on=key)` dispatch row from
  `docs/design/pandas-support.md` §5 with `on="idd"` (typo of `id`),
  forcing D0060 (`missingJoinKey`) on both sides of the merge.
- `pandas_bool_mask_unknown_inner.pyk` — ScoreRowNeg shape; exercises
  the §5 boolean-mask Subscript row — the inner
  `df["relevancy_scor"]` Subscript fires D0030 (`unknownColumn`) via
  piece (b) descending into the mask expression.
