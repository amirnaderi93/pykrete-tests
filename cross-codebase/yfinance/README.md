# yfinance

Yahoo Finance market-data API exposing pandas DataFrames
([ranaroussi/yfinance](https://github.com/ranaroussi/yfinance)).
Pinned at **tag 0.2.55** (commit `5cc1197`), Apache-2.0.

## Why yfinance is a donor

yfinance is the most popular open-source Yahoo Finance client
(~14k stars, active 2025 release cadence). It's the de-facto
free-tier source for OHLCV data in finance/economics analyses, and
its return shape is canonical pandas — typed `Open` / `High` /
`Low` / `Close` columns, datetime indices, the auto-adjust pattern.
v1.4 picked yfinance over the round-2 pandas-datareader choice
specifically because pandas-datareader has been dormant since its
v0.10.0 release in July 2021.

## What this donor covers

| File | Shape verified in upstream | Used here |
|------|----------------------------|-----------|
| `upstream/yfinance/utils.pyk` (verbatim from `yfinance/utils.py` @ 0.2.55) | L335 — `Annual.merge(TTM, left_index=True, right_index=True)` (method-form, matches v1.3 dispatch); L459-461 — `df["Adj Open"] = df["Open"] * ratio` ×3 (string-literal subscript-assign, matches); L467-470 — `df.rename(columns={...}, inplace=True)` (dict literal, matches) | `annotated/yfinance/utils.pyk` mirrors auto_adjust's subscript-assign + dict-literal rename verbatim, plus the method-form .merge shape converted to `on="Close"` (pykrete dispatches `on=`-keyed joins) |

Per the v1.4 spec §2 paste-from-source audit, the net verified
dispatched-op exercise in yfinance is 5 hits in `utils.py` covering
all three of `df["new"] = expr`, `df.rename(columns={...})`, and
`df.merge(...)`. The shapes pykrete does NOT dispatch (positional
+ axis=1 .drop at L463-465, list-comprehension slice at L472, the
boolean-mask form claimed in round-3 that does not exist in the
file) are documented in the v1.4 spec and not exercised here.

## Probe inventory

- **Annotated probes (positive)** — 6 total across the one fixture:
  - `utils.pyk` — 4 RESOLVES (`-auto-adjust-adjopen-after-assign`,
    `-auto-adjust-post-rename-open`, `-merge-statement-close`,
    `-ticker-close-scalar`) + 2 TYPE-IS
    (`-ticker-type`, `-currency-type`).
- **Negative probes (probes_negative/)** — 3 total:
  - `pandas_typo_in_rename.pyk` — D0030 on `"Open"` (rename source
    key typo).
  - `pandas_merge_unknown_key.pyk` — D0060 on `"Close"` (right-side
    join key missing).
  - `pandas_dataframe_alias.pyk` — D0090 on `DataFrame[OHLCRowDep]`
    (deprecated alias per pandas-support.md §6).

## Schema dtype claims (pandas defaults per pandas-support.md §4)

- OHLC price columns (`Open` / `High` / `Low` / `Close`, plus
  `AdjOpen` / `AdjHigh` / `AdjLow` / `AdjClose`) → `double`.
  yfinance constructs them via `pd.to_numeric(...)` for casts
  (utils.py L93, L99) before the adjust functions run.
- `ticker`, `currency` (string identifiers) → `string`.

## License

Apache-2.0. License file reproduced at `LICENSE-UPSTREAM`.
