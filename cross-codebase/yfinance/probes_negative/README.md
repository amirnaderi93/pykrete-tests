# yfinance — probes_negative/

Deliberately-corrupted fixtures derived from yfinance's
`utils.auto_adjust` surface (subscript-assign + dict-literal
rename) and the `Annual.merge(TTM, ...)` shape. Each fixture
mirrors a real upstream code shape, then injects exactly one
regression so pykrete must fire a specific diagnostic.

- `pandas_typo_in_rename.pyk` — OHLCRowNeg shape from the sibling
  `annotated/yfinance/utils.pyk auto_adjust_demo`. The rename
  source key `AdjOpn` (missing `e`) doesn't match the receiver
  schema, so `Open` is never bound on the renamed view; the
  post-rename `adjusted["Open"]` Subscript fires D0030
  (`unknownColumn`) via piece (b)'s col-ref check on the rebound
  schema.
- `pandas_merge_unknown_key.pyk` — OHLCRowMergeNeg +
  TTMRowMergeNeg shapes mirroring `merge_statements_demo`. The
  `on="Close"` join key exists on the left frame but is absent
  from TTMRowMergeNeg, so the v1.3 join-key check fires D0060
  (`missingJoinKey`) on the right side via the .merge(...)
  dispatch.
- `pandas_dataframe_alias.pyk` — OHLCRowDep shape from the sibling
  annotated/yfinance/utils.pyk; uses the deprecated `DataFrame[X]`
  alias on a parameter slot, firing D0090
  (`deprecatedDataFrameAlias`) per pandas-support.md §6.
