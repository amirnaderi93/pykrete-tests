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
- `pandas_loc_literal_typo.pyk` — OHLCRowLocNeg shape from the sibling
  annotated `OHLCRow`. Selects via `df.loc[:, "Clse"]` (missing `o`)
  against the pandas-tagged receiver; the v1.5 PR-C literal-form
  `.loc` column-inference arm (expr.rs Subscript-on-Name) fires D0030
  with a "did you mean 'Close'?" suggestion. Shape divergence from
  upstream: yfinance/utils.py uses `df.loc[idx, "col"]` (non-slice row
  indexer) at L664-L683; the `:` slice-all-rows form is the PR-C spec
  arm yfinance does not exercise verbatim — the fixture reuses the
  OHLC schema + `.loc` idiom to keep the donor's coverage recognizable
  while exercising the literal-key shape specifically.
- `pandas_head_then_merge_unknown_key.pyk` — v1.5 PR-A3 chain-survival
  negative-space probe. AnnualRowChainNeg + TTMRowChainNeg mirror the
  `Annual.merge(TTM, ...)` shape from `yfinance/utils.py:L335`, but
  pre-chain a `.head(10)` before the `.merge(on="Close")` — the v1.5
  PR-A3 dialect-gating arm at `shapes.rs:103-105` (on pin 8b2555f)
  keeps the pandas tag through `.head()` so the follow-up `.merge`
  still routes through the pandas dispatch and the join-key check
  fires D0060 on the right side. Without PR-A3 gating, `.head()`
  would be treated as terminal and the `.merge` schema check would
  silently skip. Shape divergence: yfinance/utils.py does not literally
  chain `.head().merge()`; the chain is the user-side spot-check idiom
  exercising the chain-survival arm.
