# Spike: PROBE-TYPE-IS scope-binding (v1.2)

Spike branch: `spike/v1.2-probe-type-is-scope-binding`
Spike file: `scripts/spikes/probe_type_is_scope_bind.py`
Run: `python3 scripts/spikes/probe_type_is_scope_bind.py`

## Hypothesis

v1.1's synth emits `_probe = (col("x") + lit(1))` as a standalone statement
inside the enclosing function. The expression has no DataFrame receiver, so
`col("x")` does not resolve against any schema and pykrete reports no
diagnostic (inconclusive). The proposed fix is to emit
`_probe = df.select(col("x") + lit(1))`, binding the synth to the typed
DataFrame in scope.

## Results

Three test cases, each materialized as two fixtures (style A = current synth,
style B = proposed synth) in isolated tmp dirs with strict-mode `pykrete.json`.
Pykrete invoked once per fixture; diagnostics captured as JSON.

| case              | column | style A (current)          | style B (proposed)       |
| ----------------- | ------ | -------------------------- | ------------------------ |
| string_on_int     | label  | no diagnostics             | **D0081 at line 10**     |
| enum_status       | status | no diagnostics             | **D0081 at line 10**     |
| same_family_int   | amount | no diagnostics             | no diagnostics (vacuous) |

Vacuity check (all pass):
- `string_on_int`: claim "int on label" is false (label is string); style B fires D0081.
- `enum_status`: claim "int on status" is false (status is string-backed enum); style B fires D0081.
- `same_family_int`: claim "int on amount" is true; style B correctly stays silent.

Falsifiability sanity check: mutating the schema so `label: int`
silences the D0081 in style B — the diagnostic tracks the real
schema, not the fixture text.

## Verdict

**The scope-binding fix works.** Wrapping the synth in `df.select(...)`
moves the column reference into a context where pykrete tracks the typed
DataFrame, and the existing D0081 (and by extension D0080/D0082) checks
fire as expected on type mismatch.

## Unexpected behaviors

- Pykrete enum syntax is `enum["a", "b"]`, not `typing.Literal[...]`. The
  synth only operates on the *column expression*, never the type
  expression, so this doesn't affect the v1.2 design — noted for the
  spec PR.
- `df.select(...)` adds no collateral diagnostics; only the targeted
  D-code surfaces.
- `pykrete check` honors `pykrete.json` only when run from inside the
  config dir or passed a dir argument. Absolute file paths bypass
  discovery — relevant if probes.py is ever called with absolute paths.

## Productionizing complexity

The synth change itself is one line at `scripts/probes.py:800`:

```python
# current
expr = f'{ident} = ({accessor} + lit(1))'
# proposed
expr = f'{ident} = {df_ident}.select({accessor} + lit(1))'
```

The real work is resolving `df_ident` from the AST. `_enclosing_function`
already returns the FunctionDef containing the probe target line; we need
to walk its `args.args` and pick the one with a `DataFrame[Schema]`
annotation. Edge cases the spec PR has to cover:

- Function has multiple `DataFrame[...]` params (pick by name match?
  always first? error if ambiguous?).
- Function has zero `DataFrame[...]` params (current behavior: mark
  unsynthesizable, same as today's `<unsynthesizable>` path).
- Probe target line is module-scope (today: append at module scope; with
  scope binding there's no df — keep unsynthesizable).
- The `df` binding is rebound between the function head and the probe
  target line (e.g. `df = df.filter(...)`). Pykrete tracks rebinding
  through method chains, so the most recent binding is what matters —
  using the original param name is still correct if no rebinding
  occurred up to target_line. (Out of scope for v1.2 spec; document the
  carve-out.)

Estimate: **1.5 to 2 days** — AST param-resolution helper + unit tests
(~0.5 day), synth rewrite + `test_probes.py` updates (~0.5 day),
cross-codebase golden refresh now that TYPE-IS probes fire real
D-codes instead of staying silent (~0.5 day), spec PR + bookkeeping
(~0.25 day).

## Recommendation

**Proceed with v1.2 spec PR for PROBE-TYPE-IS.** The technique is sound,
the diff at the synth site is one line, and the AST resolution work is
contained. The carve-out for numeric subtypes (rule `_NUMERIC_FAMILY` at
`probes.py:518`) stays in force; that's a separate pykrete-core gap, not
a synthesizer gap.

One follow-up for the spec PR to address explicitly: behavior when the
function declares multiple `DataFrame[...]` params. Default proposal:
pick the first; require fixture authors to put the relevant DF first if
they want a different choice. (TypeScript-style — first param wins, no
inference magic.)
