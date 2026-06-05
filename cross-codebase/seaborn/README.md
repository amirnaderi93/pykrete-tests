# seaborn

Statistical visualization library, pandas-first API
([mwaskom/seaborn](https://github.com/mwaskom/seaborn)). Pinned at
**tag v0.13.2** (commit `9521ea1`), BSD-3-Clause.

## Why seaborn is a donor

seaborn is the canonical statistical-visualization layer on top of
matplotlib for pandas users. Tens of thousands of analysis notebooks
build a tidy DataFrame, hand it to `sns.relplot` / `sns.catplot` /
`sns.lmplot`, and rely on the library to rename axis columns,
combine with grid-metadata via merges, and project to plotting
slots. Trust-claim wise: if pykrete passes on idioms from the
dominant pandas-visualization stack, that's a stronger signal than
synthetic fixtures could give.

## What this donor covers

| File | Shape verified in upstream | Used here |
|------|----------------------------|-----------|
| `upstream/seaborn/categorical.pyk` (verbatim from `seaborn/categorical.py` @ v0.13.2) | L79 — `self.plot_data.rename(columns={"x": "y", "y": "x"})` — DICT LITERAL kwarg, matches v1.3 dispatch | `annotated/seaborn/categorical.pyk` mirrors the wide-orient axis swap |
| `upstream/seaborn/relational.pyk` (verbatim from `seaborn/relational.py` @ v0.13.2) | L825, L886 use `.rename(columns=<var>)` (variable kwarg, does NOT dispatch); L890-895 use `pd.merge(...)` (top-level, does NOT dispatch); L300-307 use f-string / variable Subscript-assign (does NOT dispatch) | `annotated/seaborn/relational.pyk` mirrors the SAME shape of work seaborn API USERS write — dict-literal renames, method-form merges, string-literal Subscripts — even though the library's own source uses the variable forms pykrete doesn't dispatch |

Per the v1.4 spec §2 paste-from-source audit, the one verified
in-library dispatched-shape hit in seaborn is `categorical.py:L79`.
The relational annotated companion models the idiom users WRITE
around seaborn rather than the variable-kwarg shapes seaborn's own
source uses; this scoping decision is documented in the v1.4 spec
("the fixtures can model the IDIOMS users actually write [...]
even though the library's own source uses variable forms").

## Probe inventory

- **Annotated probes (positive)** — 9 total across the two fixtures:
  - `categorical.pyk` — 2 RESOLVES (`-wide-swap-x`, `-wide-swap-y`).
  - `relational.pyk` — 5 RESOLVES (`-axis-rename-x`, `-axis-rename-y`,
    `-axis-rename-hue-survives`, `-merge-treatment`,
    `-merge-x-raw-survives`) + 2 TYPE-IS
    (`-hue-raw-type`, `-merge-hue-raw-type`).
- **Negative probes (probes_negative/)** — 3 total:
  - `pandas_typo_in_rename.pyk` — D0030 on `"x"` (the source key of
    the rename didn't match, so the target was never bound).
  - `pandas_merge_unknown_key.pyk` — D0060 on `"unit_id"`
    (right-side join key missing).
  - `pandas_dataframe_alias.pyk` — D0090 on `DataFrame[TidyDataDep]`
    (deprecated alias per pandas-support.md §6).

## Schema dtype claims (pandas defaults per pandas-support.md §4)

- `x_raw` / `y_raw` (numeric measurement) → `double`. Seaborn's
  relational plots assume numeric axis dtype for estimator + CI paths.
- `hue_raw` (categorical/string label) → `string`.
- `unit_id` (integer grouping key) → `long`.
- `treatment` (string label) → `string`.

## License

BSD-3-Clause. License file reproduced at `LICENSE-UPSTREAM`. The
seaborn copyright is © 2012-2023 Michael L. Waskom.
