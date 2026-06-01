# quinn — probes_negative/

Deliberately-corrupted fixtures derived from quinn's
`dataframe_helpers.py` PersonRow shape. Each fixture mirrors a real
upstream helper, then injects exactly one regression so pykrete must
fire a specific diagnostic.

- `select_drops_then_ref.pyk` — extends quinn's `.select(name)`
  helper with a follow-up `.select(age)` that drops `name`, then
  references `name` with two typos in one statement. Forces two
  D0030s from one `.select()` call (stacked-EXPECTS coverage,
  exercises the bipartite pairing logic).
- `unknown_column_in_filter.pyk` — two helpers each reference a
  column not in PersonRow (one via `.filter`, one via `.select`).
  Forces exactly two D0030s file-wide, which is the first real
  exercise of `PROBE-FILE-COUNT`.
