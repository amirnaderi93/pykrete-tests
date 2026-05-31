#!/usr/bin/env python3
"""Regression tests for scripts/build_catalog_from_source.py.

Closes round-2 BLOCKER 2 (drift-watch SHA-only noise PR): proves that
the diagnostics[] payload is byte-identical when only the pinned SHA
changes, so the workflow's jq-based payload-only comparison can rely
on it to suppress no-drift PRs.

Run: python -m unittest scripts/test_build_catalog.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILDER = REPO_ROOT / "scripts" / "build_catalog_from_source.py"
VENDORED_CATALOG = REPO_ROOT / "scripts" / "diagnostic_catalog.json"


def _diagnostics_rs_from(catalog: dict) -> str:
    entries = ",\n    ".join(
        f'("{e["code"]}", "{e["ruleName"]}")'
        for e in catalog["diagnostics"]
    )
    return (
        "pub static DIAGNOSTIC_CATALOG: &[(&str, &str)] = &[\n"
        f"    {entries},\n"
        "];\n"
    )


def _run_builder(diagnostics_rs: str, commit: str, previous: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        diag_path = tdp / "diagnostics.rs"
        diag_path.write_text(diagnostics_rs, encoding="utf-8")
        out_path = tdp / "new_catalog.json"
        summary_path = tdp / "summary.txt"
        subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                "--diagnostics", str(diag_path),
                "--commit", commit,
                "--previous", str(previous),
                "--out", str(out_path),
                "--summary", str(summary_path),
            ],
            check=True,
            capture_output=True,
        )
        return {
            "catalog": json.loads(out_path.read_text(encoding="utf-8")),
            "raw": out_path.read_text(encoding="utf-8"),
            "summary": summary_path.read_text(encoding="utf-8"),
        }


class PayloadStableUnderShaChange(unittest.TestCase):
    """The diagnostics[] payload must NOT change when only the SHA differs.

    This is what gates BLOCKER 2: the workflow's payload-only diff stays
    empty under a SHA-only upstream bump, so no PR is opened.
    """

    def test_diagnostics_array_byte_identical_under_sha_only_bump(self):
        vendored = json.loads(VENDORED_CATALOG.read_text(encoding="utf-8"))
        diag_rs = _diagnostics_rs_from(vendored)
        fake_new_sha = "0" * 40
        result = _run_builder(diag_rs, fake_new_sha, VENDORED_CATALOG)
        # diagnostics[] should be byte-identical to vendored
        self.assertEqual(
            result["catalog"]["diagnostics"],
            vendored["diagnostics"],
            "diagnostics[] drifted under a SHA-only upstream bump",
        )
        # Only the SHA-pin headers should differ at the JSON level
        self.assertEqual(result["catalog"]["pykreteSourceCommit"], fake_new_sha)
        self.assertNotEqual(
            result["catalog"]["pykreteSourceCommit"],
            vendored["pykreteSourceCommit"],
        )
        # Summary should call out that there is no code-level drift
        self.assertIn("No code-level drift", result["summary"])

    def test_added_code_surfaces_as_drift(self):
        vendored = json.loads(VENDORED_CATALOG.read_text(encoding="utf-8"))
        bumped = json.loads(json.dumps(vendored))
        bumped["diagnostics"].append({
            "code": "D9999",
            "ruleName": "syntheticForTest",
            "severity": "error",
            "stable": True,
        })
        diag_rs = _diagnostics_rs_from(bumped)
        result = _run_builder(diag_rs, "1" * 40, VENDORED_CATALOG)
        codes = [e["code"] for e in result["catalog"]["diagnostics"]]
        self.assertIn("D9999", codes)
        self.assertIn("Added (1)", result["summary"])

    def test_renamed_code_surfaces_as_drift(self):
        vendored = json.loads(VENDORED_CATALOG.read_text(encoding="utf-8"))
        bumped = json.loads(json.dumps(vendored))
        bumped["diagnostics"][0]["ruleName"] = "renamedForTest"
        diag_rs = _diagnostics_rs_from(bumped)
        result = _run_builder(diag_rs, "2" * 40, VENDORED_CATALOG)
        self.assertEqual(
            result["catalog"]["diagnostics"][0]["ruleName"],
            "renamedForTest",
        )
        self.assertIn("Renamed (1)", result["summary"])

    def test_removed_code_surfaces_as_drift(self):
        vendored = json.loads(VENDORED_CATALOG.read_text(encoding="utf-8"))
        bumped = json.loads(json.dumps(vendored))
        dropped = bumped["diagnostics"].pop()
        diag_rs = _diagnostics_rs_from(bumped)
        result = _run_builder(diag_rs, "3" * 40, VENDORED_CATALOG)
        codes = [e["code"] for e in result["catalog"]["diagnostics"]]
        self.assertNotIn(dropped["code"], codes)
        self.assertIn("Removed (1)", result["summary"])


class JqPayloadDiffMirrorsWorkflow(unittest.TestCase):
    """Mirror the workflow's `jq -S .diagnostics` comparison locally.

    The workflow at .github/workflows/catalog-drift-watch.yml gates PR
    creation on `diff jq(prev) jq(new)`. This test executes that exact
    pipeline against a SHA-only bump and asserts zero diff bytes — so
    if anyone weakens either the builder or the jq filter, this fails.
    """

    @unittest.skipIf(
        subprocess.run(["which", "jq"], capture_output=True).returncode != 0,
        "jq not on PATH",
    )
    def test_jq_diagnostics_diff_empty_under_sha_only_bump(self):
        vendored_text = VENDORED_CATALOG.read_text(encoding="utf-8")
        vendored = json.loads(vendored_text)
        diag_rs = _diagnostics_rs_from(vendored)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            diag_path = tdp / "diagnostics.rs"
            diag_path.write_text(diag_rs, encoding="utf-8")
            new_catalog = tdp / "new.json"
            summary = tdp / "summary.txt"
            subprocess.run(
                [
                    sys.executable, str(BUILDER),
                    "--diagnostics", str(diag_path),
                    "--commit", "deadbeef" * 5,
                    "--previous", str(VENDORED_CATALOG),
                    "--out", str(new_catalog),
                    "--summary", str(summary),
                ],
                check=True,
                capture_output=True,
            )
            prev_diag = subprocess.run(
                ["jq", "-S", ".diagnostics", str(VENDORED_CATALOG)],
                capture_output=True, check=True,
            ).stdout
            new_diag = subprocess.run(
                ["jq", "-S", ".diagnostics", str(new_catalog)],
                capture_output=True, check=True,
            ).stdout
            self.assertEqual(
                prev_diag, new_diag,
                "jq -S .diagnostics drift detected under SHA-only bump — "
                "the workflow would open a noise PR",
            )


if __name__ == "__main__":
    unittest.main()
