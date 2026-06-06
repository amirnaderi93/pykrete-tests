# scikit-learn

Machine-learning preprocessing standard for pandas users
([scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn)).
Pinned at **tag 1.7.2** (commit `25dee604`), BSD-3-Clause.

## Classification: canonical-fixture-only

Round-4 paste-from-source audit of
`sklearn/preprocessing/_data.py` + `sklearn/utils/validation.py`
at tag `1.7.0` found ZERO direct
`df.rename / .merge / .drop(columns=…) / .assign / df["x"] =`
sites — both files are numpy-typed throughout. Re-greps under the
`1.7.2` pin across the broader sklearn surface
(`sklearn/utils/_set_output.py`, `sklearn/compose/`) did not
surface verifiable in-library dispatched-shape sites either;
sklearn's core targets numpy array in/out for performance and
typing reasons.

Per the v1.4 spec §2 scikit-learn entry: "if none found, donor
enters as a 'canonical-fixture-only' donor (~2-3 annotated
fixtures modeling user-side sklearn-style pipelines, not
in-library code)". This is that scoping — the annotated
companion at `annotated/canonical/preprocessing_pattern.pyk` is a
**canonical example inspired by the scikit-learn preprocessing
API**, **NOT extracted verbatim from sklearn internal code**. The
fixture models the SAME shape of work scikit-learn USERS write
AROUND the sklearn API — engineer derived features via
`df.assign`, project to the StandardScaler /
ColumnTransformer-expected slot list via `df[[...]]`, and drop
the raw columns once engineered replacements are bound via
`df.drop(columns=[...])` — rather than mirroring sklearn's own
internal source.

## What this donor covers

| File | Origin | Used here |
|------|--------|-----------|
| `upstream/sklearn/__init__.py` (verbatim from `sklearn/__init__.py` @ 1.7.2) | Vendored solely for license attribution — sklearn's package root with no v1.3-dispatched op surface | not annotated; the file is reproduced verbatim only as license-attribution evidence per the canonical-fixture-only classification |
| `annotated/canonical/preprocessing_pattern.pyk` | Canonical example inspired by scikit-learn preprocessing API; not extracted verbatim from sklearn internal code | Models the sklearn-USER engineer / project / drop pipeline |

Three dispatched ops are modeled in the canonical fixture, each
mapping to a v1.3 dispatch row that v1.4 maintains under the
`PandasFrame[X]` tag:

- `df.assign(income_per_visit=df["income"])` — dispatched at
  `column_methods.rs:445-458` (`apply_pandas_assign` →
  `apply_add_columns_iter`).
- `df[["age", "income", "n_visits", "region_code"]]` — dispatched
  at `expr.rs:222-253` (list-slice column projection).
- `df.drop(columns=["n_visits"])` — dispatched at `expr.rs:964-966`
  (`apply_pandas_drop` with `columns=` kwarg).

## Probe inventory

- **Annotated probes (positive)** — 9 total in `preprocessing_pattern.pyk`:
  - 6 RESOLVES (`-assign-income-per-visit-binds`,
    `-assign-category-survives`, `-project-age-binds`,
    `-project-region-code-binds`, `-drop-feature-blob-survives`,
    `-drop-category-survives`).
  - 3 TYPE-IS (`-category-type` [string],
    `-projected-region-code-type` [string],
    `-trimmed-feature-blob-type` [binary]).
- **Negative probes (probes_negative/)** — 2 total:
  - `pandas_drop_typo.pyk` — D0030 on `"n_vistis"` (a transposition
    of `n_visits`; the drop list-element walker fires D0030 on the
    unresolved column literal).
  - `pandas_dataframe_alias.pyk` — D0090 on
    `DataFrame[FeatureMatrixDep]` (deprecated alias per
    `pandas-support.md` §6).

## TYPE-IS atomic-family discipline

Per v1.4 spec §1 line 64 floor, each new pandas donor ships ≥3
`PROBE-TYPE-IS` markers, with atomic-family diversity (not all
string). The schema therefore mixes:

- `category: string` — pandas object/str label column standard to
  sklearn ColumnTransformer string slots (Textual family → D0081
  fires under the synth wrap).
- `region_code: string` — second string slot covering survival
  through `df[[...]]` projection (Textual family → D0081 fires).
- `feature_blob: binary` — bytes column carrying per-row
  serialized embeddings, the canonical sklearn-USER shape for
  sidecar embedding bytes accompanying tabular features
  (Collection family per `strict_operators.rs:57` → D0081 fires).

Numeric columns (`age`, `income`, `n_visits`) are intentionally
NOT covered by TYPE-IS — the strict-operator checker fires D0081
only on Textual / Collection families, so a TYPE-IS on a numeric
column would silently pass and be vacuous.

## Schema dtype claims (pandas defaults per `pandas-support.md` §4)

- `age: double`, `income: double` — float64 measurements
  (sklearn StandardScaler / numeric transformer canonical input).
- `n_visits: long` — int64 count column.
- `category: string`, `region_code: string` — object/str label
  columns (sklearn ColumnTransformer string slots).
- `feature_blob: binary` — object/bytes column carrying serialized
  embeddings (v1.3 §4 "Other / structured").

## License

BSD-3-Clause. License file reproduced at `LICENSE-UPSTREAM`. The
scikit-learn copyright is © 2007-2024 The scikit-learn developers.
