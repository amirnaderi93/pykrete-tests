# spark — probes_negative/

Deliberately-corrupted fixtures derived from Apache Spark's PySpark
test surface (`python/pyspark/sql/tests/`). Each fixture mirrors a
real upstream code shape, then injects exactly one regression so
pykrete must fire a specific diagnostic.

Fixtures here run under **strict mode** (sibling `pykrete.json` sets
`typeCheckingMode: "strict"`). See the "Strict-mode caveat"
subsection of `scripts/PROBES.md` before adding new fixtures.

- `cross_type_comparison.pyk` — KV schema from `test_column.py`'s
  operator surface, but compares string against int to force D0082
  (`crossTypeComparison`, strict mode).
- `drop_then_reference.pyk` — NameAgeActiveNeg schema from
  `test_dataframe.py`'s drop demo. Two functions: `drop_then_select_dropped`
  drops one column (`active`) then references it in a follow-up
  `.select()`, forcing one D0030; `select_two_unknowns` selects two
  typos (`nam`, `agee`) in a single `.select()` call, forcing two
  stacked D0030s from one statement (stacked-EXPECTS coverage).
- `cross_frame_typo.pyk` — v1.5 PR-B1 cross-frame negative-space probe.
  LeftFrameCrossNeg + RightFrameCrossNeg mirror the cross-frame
  Subscript surface from `test_dataframe.py:L54-55` where
  `joined_df.drop(left_df["join_key"])` resolves the literal against
  the OTHER frame's schema. This fixture exercises
  `left_df.select(right_df["rite_value"])` — `rite_value` is a typo
  of `right_value` so D0030 fires against `RightFrameCrossNeg` (the
  other frame's schema, NOT `left_df`'s LeftFrameCrossNeg). Confirms
  PR-B1's cross-frame col-ref routing via `collect_col_refs`.
- `groupby_non_dataframe_arg_no_fp.pyk` — v1.5 PR-B2 regression-guard.
  `df.groupBy(bag.x)` where `bag` is a non-DataFrame plain class must
  fall through the column_name_arg DataFrame gate silently — no D0030
  spuriously fires against `df`'s schema for a non-DataFrame Attribute
  arg. Asserts FILE-CLEAN-OF D0030. Without the v1.5 PR-B2 gate
  (commit 7d9c97e), the ungated col-ref arm would emit a false-positive
  D0030 against NameAgeActiveB2.
