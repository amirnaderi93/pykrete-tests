# pykrete-tests

Real-world PySpark codebases used as [pykrete](https://github.com/amirnaderi93/pykrete)'s
integration test suite. pykrete-tests vendors snapshots of well-known PySpark
projects, adds pykrete annotations (Schema classes, typed signatures), and runs
pykrete on every push and nightly. Its purpose is twofold:

- **Regression coverage** — catch behavior changes in pykrete's checker as new
  operations are modeled and existing ones evolve.
- **Trust signal** — demonstrate that pykrete keeps real PySpark code
  diagnostic-free under realistic annotation, not just toy examples.

## Status

Initial scaffold. Targets:

- **Apache Spark** — `python/pyspark/sql/tests/` and `python/pyspark/tests/`
  (149 + 33 PySpark files at the time of selection).
- **MLflow** — files importing `pyspark.sql` (65 across the repo at the time
  of selection).

See [pykrete's roadmap](https://github.com/amirnaderi93/pykrete/blob/main/docs/roadmap.md)
for context.

## Layout (planned)

Each tested codebase gets a top-level directory:

```
spark/
├── upstream/        # vendored .pyk files (renamed verbatim from upstream .py)
├── annotations/     # pykrete Schema classes + typed signatures added alongside
├── pinned-commit    # the exact upstream SHA we vendored from
└── LICENSE-UPSTREAM # the upstream's license, preserved verbatim

mlflow/
├── ...
```

`.py` files become `.pyk` by simple rename — `.pyk` is a strict superset of
Python, so the upstream code is unchanged. Annotations live in companion files
that pykrete reads cross-file (`Schema` declarations) or as small patches that
add typed signatures to representative functions.

## Methodology

For each codebase:

1. Vendor the upstream Python source at a pinned commit, preserving the upstream
   license verbatim.
2. Rename `.py` → `.pyk` (zero behavior change).
3. Add Schema declarations and typed signatures alongside, the way a real user
   adopting pykrete in their codebase would.
4. Run `pykrete check` on every push and nightly. Results published in
   `RESULTS.md`, regenerated on each run.

## License

Annotations and tooling in this repo are MIT-licensed — see [LICENSE](LICENSE).

Each vendored codebase retains its upstream license verbatim in
`<project>/LICENSE-UPSTREAM`. Vendoring is for testing purposes; canonical
sources stay upstream. Each `<project>/pinned-commit` file records the exact
commit hash.
