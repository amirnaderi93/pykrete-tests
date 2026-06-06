# Great Expectations

Data-quality framework, pandas-first by historical lineage
([great-expectations/great_expectations](https://github.com/great-expectations/great_expectations)).
Pinned at **tag 1.3.13** (commit `6aab3bbb`), Apache 2.0.

## Classification: canonical-fixture-only

Round-4 paste-from-source audit of
`great_expectations/execution_engine/pandas_execution_engine.py`
at tag `1.3.13` found ZERO dispatched-shape sites (the file
operates at the metric-domain abstraction layer, not raw pandas
ops). Re-greps under the `1.3.13` pin across `metrics/` and
`expectations/` did not surface verifiable in-library
dispatched-shape sites either — GE's execution engine pushes
row-level checks through a metric abstraction rather than raw
`.assign / .merge / .rename / .drop / df["x"] =` calls.

Per the v1.4 spec §2 Great Expectations entry: "floor-not-met →
scoped 'canonical-fixture-only' per scikit-learn precedent". This
is that scoping — the annotated companion at
`annotated/canonical/expectation_pattern.pyk` is a **canonical
example inspired by the Great Expectations data-quality API**,
**NOT extracted verbatim from Great Expectations internal code**.
The fixture models the SAME shape of work GE USERS write AROUND
the GE API — build a validated dataset, filter to rows that
satisfy / violate an expectation via boolean mask, mark rows
with a validation-result flag via `df.assign`, then reference
the validation-result columns — rather than mirroring GE's own
internal source.

## What this donor covers

| File | Origin | Used here |
|------|--------|-----------|
| `upstream/great_expectations/__init__.pyk` (verbatim from `great_expectations/__init__.py` @ 1.3.13) | Vendored solely for license attribution — GE's package root with no v1.3-dispatched op surface | not annotated; the file is reproduced verbatim only as license-attribution evidence per the canonical-fixture-only classification |
| `annotated/canonical/expectation_pattern.pyk` | Canonical example inspired by Great Expectations data-quality API; not extracted verbatim from Great Expectations internal code | Models the GE-USER mask-filter / assign pipeline |

Two dispatched ops are modeled in the canonical fixture, both
mapping to v1.3 dispatch rows that v1.4 maintains under the
`PandasFrame[X]` tag:

- `df[df["passes_check"]]` — boolean-mask Subscript shape per
  `pandas-support.md` §5 row 2; piece (b) descends the inner
  `df["passes_check"]` and resolves it under the typed receiver.
- `df.assign(is_valid=df["passes_check"])` — dispatched at
  `column_methods.rs:445-458` (`apply_pandas_assign` →
  `apply_add_columns_iter`).

## Probe inventory

- **Annotated probes (positive)** — 8 total in `expectation_pattern.pyk`:
  - 5 RESOLVES (`-mask-passing-row-count`,
    `-mask-passing-category-survives`, `-mask-inner-passes-check`,
    `-assign-is-valid-binds`,
    `-assign-expectation-name-survives`).
  - 3 TYPE-IS (`-category-type` [string],
    `-expectation-name-type` [string],
    `-evidence-blob-type` [binary]).
- **Negative probes (probes_negative/)** — 2 total:
  - `pandas_mask_typo.pyk` — D0030 on `"passes_chcek"` (a
    transposition of `passes_check`; piece (b) descends the inner
    Subscript inside the mask slice and fires D0030 on the
    unbound literal).
  - `pandas_dataframe_alias.pyk` — D0090 on
    `DataFrame[ValidatedDatasetDep]` (deprecated alias per
    `pandas-support.md` §6).

## TYPE-IS atomic-family discipline

Per v1.4 spec §1 line 64 floor, each new pandas donor ships ≥3
`PROBE-TYPE-IS` markers, with atomic-family diversity (not all
string). The schema mixes:

- `category: string` — pandas object/str categorical label
  standard to per-category expectation reporting (Textual family
  → D0081 fires under the synth wrap).
- `expectation_name: string` — second string slot covering the
  name of the expectation that produced each per-row outcome
  (Textual family → D0081 fires). Two distinct string slots let
  the TYPE-IS markers exercise two schema slots so a regression
  that confused one for another can't pass both.
- `evidence_blob: binary` — bytes column carrying per-row
  evidence payloads for audit-trail rows (Collection family per
  `strict_operators.rs:57` → D0081 fires).

Numeric columns (`row_count`, `value`) and the bool `passes_check`
column are intentionally NOT covered by TYPE-IS — the
strict-operator checker fires D0081 only on Textual / Collection
families, so a TYPE-IS on a numeric or bool column would silently
pass and be vacuous.

## Schema dtype claims (pandas defaults per `pandas-support.md` §4)

- `row_count: long` — int64 expectation aggregation counter.
- `value: double` — float64 measurement under test
  (`ExpectColumnValuesToBeBetween` canonical input).
- `passes_check: bool` — bool flag carrying the per-row
  expectation outcome bit; used as the slice expression in the
  boolean-mask Subscript filter.
- `category: string`, `expectation_name: string` — object/str
  label columns (categorical reporting + per-expectation name).
- `evidence_blob: binary` — object/bytes column carrying audit
  payloads (v1.3 §4 "Other / structured").

## License

Apache 2.0. License file reproduced at `LICENSE-UPSTREAM`. The
Great Expectations copyright is © 2024 Great Expectations Labs,
Inc. (and prior).
