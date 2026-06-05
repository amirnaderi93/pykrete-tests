# pandera

Schema-validation framework for pandas
([unionai-oss/pandera](https://github.com/unionai-oss/pandera)).
Pinned at **tag v0.23.1** (commit `88ee1bb`), MIT. pykrete is the
static peer of pandera's runtime checks; this donor is the sibling-
project signal.

## Classification: canonical-fixture-only

Round-4 paste-from-source audit of pandera's internal
`pandera/backends/pandas/container.py:544-546` (the file that
actually exercises pandas `.drop` on validated frames at v0.23.1)
shows the calls use `labels=...` + `axis=1` shapes:

```python
# pandera/backends/pandas/container.py @ v0.23.1, L544-546
check_obj = check_obj.drop(labels=filter_out_columns, axis=1)
# ...
check_obj.drop(labels=filter_out_columns, inplace=True, axis=1)
```

These are NOT in the v1.3 dispatched-shape set (pykrete dispatches
the `columns=` kwarg form at `expr.rs:964-966`, NOT positional /
`labels=` + `axis=1`). No verifiable in-library
`df.rename(columns={...})` / `df.drop(columns=[...])` /
`df["new"] = expr` sites matching v1.3 dispatch were found in the
audited pandera surface.

Per the v1.4 spec §2 pandera entry: "donor enters as
'canonical-fixture-only' if floor not met". This is that scoping —
the annotated companion at `annotated/canonical/user_validation.pyk`
is a **canonical example inspired by pandera's schema-validation
API**, **NOT extracted verbatim from pandera internal code**. The
fixture models the SAME shape of work pandera USERS write around
the pandera API — align upstream frames to schema-canonical names,
attach validation-result columns, project to the validated slot
list — rather than mirroring pandera's own internal source.

## What this donor covers

| File | Origin | Used here |
|------|--------|-----------|
| `upstream/pandera/__init__.pyk` (verbatim from `pandera/__init__.py` @ v0.23.1) | Vendored solely for license attribution — pandera's package root with no v1.3-dispatched op surface | not annotated; the file is reproduced verbatim only as license-attribution evidence per the canonical-fixture-only classification |
| `annotated/canonical/user_validation.pyk` | Canonical example inspired by pandera schema-validation API; not extracted verbatim from pandera internal code | Models the pandera-USER align / assign / project pipeline |

Three dispatched ops are modeled in the canonical fixture, each
mapping to a v1.3 dispatch row that v1.4 maintains under the
`PandasFrame[X]` tag:

- `df.rename(columns={"raw_amount": "amount"})` — dispatched at
  `expr.rs:938` (`apply_pandas_rename` → `apply_rename_dict`).
- `df.assign(is_valid=df["row_count"])` — dispatched at
  `column_methods.rs:445-458` (`apply_pandas_assign` →
  `apply_add_columns_iter`).
- `df[["raw_amount", "row_count", "category", "checksum"]]` —
  dispatched at `expr.rs:222-253` (list-slice column projection).

## Probe inventory

- **Annotated probes (positive)** — 7 total in `user_validation.pyk`:
  - 4 RESOLVES (`-rename-amount-binds`,
    `-rename-category-survives`, `-assign-is-valid-binds`,
    `-project-checksum-binds`).
  - 3 TYPE-IS (`-category-type` [string],
    `-checksum-type` [binary],
    `-projected-category-type` [string]).
- **Negative probes (probes_negative/)** — 2 total:
  - `pandas_typo_in_assign.pyk` — D0030 on `"row_cuont"` (a
    transposition of `row_count`; the assign kwarg-value walker
    fires D0030 on the unresolved column literal).
  - `pandas_dataframe_alias.pyk` — D0090 on
    `DataFrame[ValidatedFrameDep]` (deprecated alias per
    `pandas-support.md` §6).

## TYPE-IS atomic-family discipline

Per v1.4 spec §1 line 64 floor, each new pandas donor ships ≥3
`PROBE-TYPE-IS` markers. pandera's canonical
`validated_at: datetime64[ns]` column is **Temporal-family**
(`strict_operators.rs:59`), which is outside the
Textual/Collection fire set the TYPE-IS synth wrap relies on; the
synth `df.select(col("validated_at") + lit(1))` would not fire
D0081 and the probe would silently pass — vacuous. To respect both
canonical pandera-USER schema typing AND the TYPE-IS fire
constraint, the schema mixes:

- `category: string` — string label column standard to pandera
  validation schemas (Textual family → D0081 fires under the
  synth wrap).
- `checksum: binary` — bytes column carrying per-row content
  fingerprints, the canonical pandera-USER shape for tracking
  validated-row provenance (paralleling the
  `Series[pa.dtypes.Binary]` field shape pandera exposes via
  `pandera/dtypes/__init__.py`) (Collection family → D0081
  fires).

## Schema dtype claims (pandas defaults per `pandas-support.md` §4)

- `raw_amount: double` — float64 measurement column.
- `row_count: long` — int64 aggregation counter.
- `category: string` — pandas object/str label column.
- `checksum: binary` — pandas object/bytes column
  (v1.3 §4 "Other / structured").
- `validated_at: timestamp` — pandera's canonical validation-time
  stamp (`datetime64[ns]`).

## License

MIT. License file reproduced at `LICENSE-UPSTREAM`. The pandera
copyright is © 2018 Niels Bantilan.
