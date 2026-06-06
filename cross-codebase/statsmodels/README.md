# statsmodels

Statistics / econometrics canonical for Python; pandas is the
canonical data input to its API
([statsmodels/statsmodels](https://github.com/statsmodels/statsmodels)).
Pinned at **tag v0.14.6** (commit `40e6a84d`), BSD-3-Clause.

## Classification: canonical-fixture-only

Round-4 paste-from-source audit of
`statsmodels/regression/linear_model.py` at tag `v0.14.4` found
ZERO `.rename / .merge / .drop / .assign / df["x"]` sites in the
file (numeric-array idioms predominate inside the regression
core); two adjacent files audited (`tsa/seasonal.py`,
`iolib/foreign.py`) similarly have zero matches. Re-greps under
the `v0.14.6` pin across a wider statsmodels surface
(`iolib/sql.py`, `tools/`, `genmod/`) did not surface verifiable
in-library dispatched-shape sites either — statsmodels'
regression core targets numpy / scipy arrays for performance.

Per the v1.4 spec §2 statsmodels entry: "if the verified-cite
floor (≥1 dispatched op in upstream code) isn't met, donor
enters as 'canonical-fixture-only' scoped per scikit-learn
precedent above". This is that scoping — the annotated companion
at `annotated/canonical/regression_pattern.pyk` is a **canonical
example inspired by the statsmodels regression API**, **NOT
extracted verbatim from statsmodels internal code**. The fixture
models the SAME shape of work statsmodels USERS write AROUND the
statsmodels API — rename incoming user-side column names to the
statsmodels formula-API regressor slot names, merge in a
per-subject covariate frame, then reference post-rename /
post-merge columns — rather than mirroring statsmodels' own
internal source.

## What this donor covers

| File | Origin | Used here |
|------|--------|-----------|
| `upstream/statsmodels/__init__.pyk` (verbatim from `statsmodels/__init__.py` @ v0.14.6) | Vendored solely for license attribution — statsmodels' package root with no v1.3-dispatched op surface | not annotated; the file is reproduced verbatim only as license-attribution evidence per the canonical-fixture-only classification |
| `annotated/canonical/regression_pattern.pyk` | Canonical example inspired by statsmodels regression API; not extracted verbatim from statsmodels internal code | Models the statsmodels-USER align / merge pipeline |

Two dispatched ops are modeled in the canonical fixture, each
mapping to a v1.3 dispatch row that v1.4 maintains under the
`PandasFrame[X]` tag:

- `df.rename(columns={"raw_y": "y", "raw_x1": "x1", "raw_x2": "x2"})`
  — dispatched at `expr.rs:938` (`apply_pandas_rename` →
  `apply_rename_dict`).
- `df.merge(cov, on="subject_id")` — dispatched at
  `expr.rs:1049` (`apply_pandas_merge` with `on=` kwarg).

## Probe inventory

- **Annotated probes (positive)** — 9 total in `regression_pattern.pyk`:
  - 6 RESOLVES (`-rename-y-binds`, `-rename-x1-binds`,
    `-rename-condition-survives`, `-merge-cohort-binds`,
    `-merge-raw-y-survives`, `-merge-baseline-score-binds`).
  - 3 TYPE-IS (`-condition-type` [string],
    `-model-payload-type` [binary],
    `-cohort-type` [string]).
- **Negative probes (probes_negative/)** — 2 total:
  - `pandas_merge_unknown_key.pyk` — D0060 on `"subject_id"`
    (right-side join key absent from `CovariateFrameMergeNeg`).
  - `pandas_dataframe_alias.pyk` — D0090 on
    `DataFrame[RegressionInputDep]` (deprecated alias per
    `pandas-support.md` §6).

## TYPE-IS atomic-family discipline

Per v1.4 spec §1 line 64 floor, each new pandas donor ships ≥3
`PROBE-TYPE-IS` markers, with atomic-family diversity (not all
string). The schema mixes:

- `condition: string` — pandas object/str label standard to
  regression-input frames (Textual family → D0081 fires under the
  synth wrap on the first-param `RegressionInput` receiver).
- `cohort: string` — string slot on the `CovariateFrame` schema;
  the third TYPE-IS lives in a dedicated `cohort_typed_probe`
  function where `CovariateFrame` is the first frame-annotated
  param so the synth correctly binds to it (the synth's
  `_first_dataframe_param` rule per `scripts/probes.py:866`).
- `model_payload: binary` — bytes column carrying serialized
  fitted-model bytes alongside the design-matrix rows
  (Collection family per `strict_operators.rs:57` → D0081 fires).

Numeric columns (`raw_y`, `raw_x1`, `raw_x2`, `subject_id`,
`baseline_score`) are intentionally NOT covered by TYPE-IS —
the strict-operator checker fires D0081 only on Textual /
Collection families, so a TYPE-IS on a numeric column would
silently pass and be vacuous.

## Schema dtype claims (pandas defaults per `pandas-support.md` §4)

- `raw_y: double`, `raw_x1: double`, `raw_x2: double`,
  `baseline_score: double` — float64 measurements / regressors
  (statsmodels OLS / GLM canonical numeric inputs).
- `subject_id: long` — int64 join key.
- `condition: string`, `cohort: string` — object/str label
  columns (treatment / cohort covariates standard on regression
  frames).
- `model_payload: binary` — object/bytes column carrying
  serialized fitted-model bytes (v1.3 §4 "Other / structured").

## License

BSD-3-Clause. License file reproduced at `LICENSE-UPSTREAM`. The
statsmodels copyright is © 2006 Jonathan E. Taylor, © 2006-2008
Scipy Developers, © 2009-2018 statsmodels Developers.
