"""Feasibility spike: PROBE-TYPE-IS synth scope-binding (v1.2).

Hypothesis: v1.1's standalone `col("x") + lit(1)` synth fails to bind to the
typed DataFrame in scope, so pykrete reports inconclusive. Wrapping the synth
inside `df.select(...)` binds it to df's schema; pykrete then fires the
expected D-code on type mismatch.

This spike is exploration only. It does NOT modify scripts/probes.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PYKRETE = "/Users/amir/Documents/amir/dathon/target/release/pykrete"
STRICT_CONFIG = '{"typeCheckingMode": "strict"}\n'


@dataclass
class Case:
    name: str
    description: str
    schema_block: str
    df_param_type: str
    expect_style_b_code: Optional[str]  # None = vacuous green expected


CASES: list[Case] = [
    Case(
        name="string_on_int",
        description="PROBE-TYPE-IS: string on \"amount\" where amount is int",
        schema_block="class S(Schema):\n    amount: int\n    label: string\n",
        df_param_type="S",
        # Probe asserts amount is string; synth treats amount as non-numeric
        # by adding lit(1). If column IS numeric (int), arithmetic is fine,
        # no D0081 fires — which the probe runner interprets as "type-is
        # claim refuted, probe FAILS". But in style (a) the synth is
        # detached, so the column doesn't resolve at all => no diagnostic
        # either way => inconclusive. Style (b) should fire D0081 when the
        # probe target column is genuinely string. To exercise the cross-
        # family path we flip target: probe says int on label (string column).
        expect_style_b_code="D0081",
    ),
    Case(
        name="enum_status",
        description="PROBE-TYPE-IS: int on \"status\" where status is enum",
        schema_block=(
            "class S(Schema):\n"
            "    status: enum[\"pending\", \"shipped\"]\n"
            "    amount: int\n"
        ),
        df_param_type="S",
        # Probe asserts status is int (it's actually a string-enum). Adding
        # lit(1) to a string-enum column should fire D0081 inside select().
        expect_style_b_code="D0081",
    ),
    Case(
        name="same_family_int",
        description="PROBE-TYPE-IS: int on \"amount\" where amount IS int (vacuous green)",
        schema_block="class S(Schema):\n    amount: int\n    label: string\n",
        df_param_type="S",
        # Probe asserts amount is int, and it is. Synth adds lit(1) to an
        # int column — no D-code should fire in either style.
        expect_style_b_code=None,
    ),
]


def write_fixture(
    case_dir: Path,
    case: Case,
    target_column: str,
    style: str,
) -> Path:
    """Write a .pyk fixture exercising the synth for one (case, style).

    style = "a"  -> standalone synth (today's behavior)
    style = "b"  -> synth wrapped in df.select(...)
    """
    if style == "a":
        synth_line = f'    _probe = (col({target_column!r}) + lit(1))'
    elif style == "b":
        synth_line = f'    _probe = df.select(col({target_column!r}) + lit(1))'
    else:
        raise ValueError(style)

    body = (
        "from pyspark.sql import DataFrame\n"
        "from pyspark.sql.functions import col, lit\n"
        "\n"
        f"{case.schema_block}\n"
        f"def fn(df: DataFrame[{case.df_param_type}]) -> DataFrame:\n"
        "    out = df\n"
        f"{synth_line}\n"
        "    return out\n"
    )
    path = case_dir / f"{case.name}_style_{style}.pyk"
    path.write_text(body)
    return path


def run_pykrete(case_dir: Path, pyk_file: Path) -> dict:
    """Invoke pykrete from inside case_dir so pykrete.json discovery works."""
    rel = pyk_file.name
    proc = subprocess.run(
        [PYKRETE, "check", "--format", "json", rel],
        cwd=case_dir,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"diagnostics": [], "_raw_stdout": proc.stdout, "_stderr": proc.stderr}


def summarize(result: dict) -> str:
    diags = result.get("diagnostics", [])
    if not diags:
        return "no diagnostics (inconclusive)"
    parts = []
    for d in diags:
        parts.append(f"{d['code']} at line {d['line']}")
    return ", ".join(parts)


def target_column_for(case: Case) -> str:
    # For each case, pick the column whose REAL type contradicts the probe
    # claim, so style (b) is expected to fire. For same_family_int the
    # target is amount (int) and the probe claim "int" matches, so no
    # diagnostic should fire.
    if case.name == "string_on_int":
        return "label"  # actually string; probe claims int; lit(1) + string -> D0081
    if case.name == "enum_status":
        return "status"  # enum (string-backed); lit(1) -> D0081
    if case.name == "same_family_int":
        return "amount"
    raise KeyError(case.name)


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="pyk_spike_"))
    print(f"[spike] workdir: {workdir}")
    rows: list[tuple[str, str, str, str]] = []

    for case in CASES:
        case_dir = workdir / case.name
        case_dir.mkdir()
        (case_dir / "pykrete.json").write_text(STRICT_CONFIG)
        target = target_column_for(case)

        path_a = write_fixture(case_dir, case, target, "a")
        path_b = write_fixture(case_dir, case, target, "b")
        result_a = run_pykrete(case_dir, path_a)
        result_b = run_pykrete(case_dir, path_b)

        rows.append((case.name, target, summarize(result_a), summarize(result_b)))

    print()
    print("=" * 88)
    print(f"{'case':<22} {'col':<10} {'style A':<28} {'style B':<28}")
    print("-" * 88)
    for name, col_name, a, b in rows:
        print(f"{name:<22} {col_name:<10} {a:<28} {b:<28}")
    print("=" * 88)

    # Vacuity check: confirm style B fires the expected code for each
    # negative case, and stays silent for the same-family case.
    print()
    print("[vacuity check]")
    for case, (_, _, a, b) in zip(CASES, rows):
        expect = case.expect_style_b_code
        if expect is None:
            ok = "no diagnostics" in b
            print(f"  {case.name}: expect silent  -> {'PASS' if ok else 'FAIL'} (got {b!r})")
        else:
            ok = expect in b
            print(f"  {case.name}: expect {expect}    -> {'PASS' if ok else 'FAIL'} (got {b!r})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
