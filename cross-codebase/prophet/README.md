# prophet

Time-series forecasting library, pandas-first API
([facebook/prophet](https://github.com/facebook/prophet)). Pinned at
**tag v1.1.6** (commit `82180bb`), MIT.

## Why prophet is a donor

prophet is the canonical "give me a forecast" library on top of
pandas. The canonical input frame is a two-column DataFrame —
`ds: datetime64[ns]` + `y: float64` — and every Prophet model
construction, fit, and predict path operates on string-literal
bracket-assigns against that frame in `python/prophet/forecaster.py`.
Trust-claim wise: if pykrete catches the dispatched-shape work the
prophet library itself performs on user-shaped frames, that's a
direct signal on the forecasting / ML-modeling pandas idiom.

## What this donor covers

Classification: **direct-dispatch** — `forecaster.py` exercises
`df["new"] = expr` subscript-assign with string-literal slices at
five verified sites (L282, L287, L346, L348, L350), which is the
v1.3 dispatched shape pykrete recognizes at `driver.rs:187-215`.

| File | Shape verified in upstream | Used here |
|------|----------------------------|-----------|
| `upstream/prophet/forecaster.pyk` (verbatim from `python/prophet/forecaster.py` @ v1.1.6) | L282 — `df['y'] = pd.to_numeric(df['y'])` — STRING LITERAL slice, matches v1.3 dispatch | `annotated/prophet/forecaster.pyk::normalize_targets` mirrors the y/ds coercion block |
| ditto | L287 — `df['ds'] = pd.to_datetime(df['ds'])` — STRING LITERAL slice, matches dispatch | covered in same block |
| ditto | L346 — `df['cap_scaled'] = (df['cap'] - df['floor']) / self.y_scale` — STRING LITERAL slice, matches | `annotated/prophet/forecaster.pyk::scale_time_series` mirrors the piecewise scaling |
| ditto | L348 — `df['t'] = (df['ds'] - self.start) / self.t_scale` — STRING LITERAL slice, matches | covered in scaling block |
| ditto | L350 — `df['y_scaled'] = (df['y'] - df['floor']) / self.y_scale` — STRING LITERAL slice, matches | covered in scaling block |
| ditto | L353 — `df[name] = ((df[name] - props['mu']) / props['std'])` — NAME slice, does NOT match dispatch | not modeled here (v1.3 dispatches only string-literal slices) |
| ditto | L544, L906 — `.drop(...)` with `axis=1` / `index=` shapes | not modeled (v1.3 dispatches `columns=` kwarg only) |

In addition, `annotated/prophet/forecaster.pyk::fluent_assign_chain`
adds one `df.assign(model_signature=df["model_name"])` call to keep
the dispatched `df.assign` row (column_methods.rs:445-458) reachable
from the prophet schema; this is the user-side idiom of fluently
constructing the training frame around prophet rather than an
in-library prophet shape (prophet itself doesn't call `df.assign` in
forecaster.py at v1.1.6).

## Probe inventory

- **Annotated probes (positive)** — 8 total in `forecaster.pyk`:
  - 5 RESOLVES (`-cap-scaled-binds`, `-y-scaled-binds`,
    `-floor-survives`, `-y-resolves`, `-assign-signature-binds`).
  - 3 TYPE-IS (`-model-name-type` [string],
    `-assign-model-name-type` [string],
    `-serialized-model-type` [binary]).
- **Negative probes (probes_negative/)** — 2 total:
  - `pandas_typo_in_assign.pyk` — D0030 on `"model_nmae"` (a
    transposition of `model_name` that doesn't resolve on the
    schema; the `df.assign` kwarg-value walker at
    `column_methods.rs:353` fires D0030).
  - `pandas_dataframe_alias.pyk` — D0090 on
    `DataFrame[ProphetFrameDep]` (deprecated alias per
    `pandas-support.md` §6).

## TYPE-IS atomic-family discipline

Per v1.4 spec §1 line 64 floor, each new pandas donor ships ≥3
`PROBE-TYPE-IS` markers. prophet's canonical
`ds: datetime64[ns]` column is **Temporal-family**
(`strict_operators.rs:59`), which is outside the
Textual/Collection fire set the TYPE-IS synth wrap relies on; the
synth `df.select(col("ds") + lit(1))` would not fire D0081 and the
probe would silently pass — vacuous. To respect both donor-faithful
canonical typing AND the TYPE-IS fire constraint, the schema adds
two adjunct columns idiomatic for prophet workflows:

- `model_name: string` — the human identifier commonly attached to
  the canonical ds/y frame in multi-model fan-out (Textual family
  → D0081 fires under the synth wrap).
- `serialized_model: binary` — pickled Prophet model bytes commonly
  persisted alongside training frames per the prophet docs
  "Serialization" section (Collection family → D0081 fires).

The two adjunct columns are added on the schema only, not on the
verbatim upstream forecaster.pyk — the upstream file is preserved
verbatim from `python/prophet/forecaster.py` @ v1.1.6 for
license-attribution and paste-from-source traceability.

## Schema dtype claims (pandas defaults per `pandas-support.md` §4)

- `ds: timestamp` — prophet's canonical date column
  (`datetime64[ns]`).
- `y: double`, `cap: double`, `floor: double` — prophet's
  canonical numeric columns (`float64`).
- `model_name: string` — adjunct identifier column (pandas
  `object[str]`).
- `serialized_model: binary` — adjunct pickle-bytes column
  (pandas `object[bytes]`; v1.3 §4 "Other / structured").

## License

MIT. License file reproduced at `LICENSE-UPSTREAM`. The prophet
copyright is © Facebook, Inc. and its affiliates.
