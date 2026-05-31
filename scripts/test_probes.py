#!/usr/bin/env python3
"""Unit tests for scripts/probes.py.

Run: python -m unittest scripts/test_probes.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import probes  # noqa: E402


CATALOG = probes.load_catalog()


def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


class MarkerParserTests(unittest.TestCase):
    def test_expects_minimal(self):
        s = _src(
            "# PROBE-EXPECTS: D0030",
            "x = 1",
        )
        out = probes.extract_from_source(s, "f.pyk", CATALOG)
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p.kind, "EXPECTS")
        self.assertEqual(p.expected_code, "D0030")
        self.assertEqual(p.comment_line, 1)
        self.assertEqual(p.target_line, 2)

    def test_expects_with_id_and_on_and_rationale(self):
        s = _src(
            '# PROBE-EXPECTS: D0030 id=q-1 on "product" -- product was dropped',
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.id, "q-1")
        self.assertEqual(p.span_text, "product")
        self.assertEqual(p.rationale, "product was dropped")

    def test_optional_arg_order_insensitive(self):
        # id=, on, match, -- in any order all parse identically.
        bodies = [
            '# PROBE-EXPECTS: D0030 id=a on "p" match /foo/i -- r',
            '# PROBE-EXPECTS: D0030 on "p" id=a match /foo/i -- r',
            '# PROBE-EXPECTS: D0030 match /foo/i on "p" id=a -- r',
        ]
        for body in bodies:
            s = _src(body, "x = 1")
            p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
            self.assertEqual(p.id, "a")
            self.assertEqual(p.span_text, "p")
            self.assertEqual(p.match_regex, "foo")
            self.assertEqual(p.match_flags, "i")
            self.assertEqual(p.rationale, "r")

    def test_resolves(self):
        s = _src("# PROBE-RESOLVES: id=q-1 -- region survives", "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.kind, "RESOLVES")
        self.assertEqual(p.id, "q-1")
        self.assertEqual(p.rationale, "region survives")

    def test_type_is_atomic(self):
        s = _src('# PROBE-TYPE-IS: double on "amount"', "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.kind, "TYPE-IS")
        self.assertEqual(p.type_expr, "double")
        self.assertEqual(p.span_text, "amount")

    def test_type_is_array_aliases(self):
        for spelling, canon in [
            ("Array[int]", "array<int>"),
            ("array<int>", "array<int>"),
        ]:
            s = _src(f'# PROBE-TYPE-IS: {spelling} on "items"', "x = 1")
            p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
            self.assertEqual(p.type_expr, canon)

    def test_type_is_decimal_parametric(self):
        s = _src('# PROBE-TYPE-IS: decimal(10,2) on "p"', "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.type_expr, "decimal(10, 2)")

    def test_type_is_unsupported_type(self):
        s = _src('# PROBE-TYPE-IS: weirdtype on "p"', "x = 1")
        with self.assertRaisesRegex(probes.ProbeError, "unsupported type expression"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_file_clean_of_single(self):
        s = _src("# PROBE-FILE-CLEAN-OF: D0030", "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.kind, "FILE-CLEAN-OF")
        self.assertEqual(p.expected_code, "D0030")
        self.assertIsNone(p.target_line)

    def test_file_clean_of_multi(self):
        s = _src("# PROBE-FILE-CLEAN-OF: D0030, D0050", "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.expected_codes, ("D0030", "D0050"))

    def test_file_count(self):
        s = _src("# PROBE-FILE-COUNT: D0030 == 3", "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.kind, "FILE-COUNT")
        self.assertEqual(p.expected_code, "D0030")
        self.assertEqual(p.expected_count, 3)

    def test_unknown_d_code_in_expects(self):
        s = _src("# PROBE-EXPECTS: D9999", "x = 1")
        with self.assertRaisesRegex(probes.ProbeError, "unknown D-code"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_typo_kind_levenshtein_hint(self):
        s = _src("# PROBE-EXPECTSS: D0030", "x = 1")
        with self.assertRaisesRegex(probes.ProbeError, "did you mean 'PROBE-EXPECTS'"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_far_drift_silently_ignored(self):
        # No close match — should be silently skipped, not a hard error.
        s = _src("# PROBE-COMPLETELYUNRELATED: foo", "x = 1")
        out = probes.extract_from_source(s, "f.pyk", CATALOG)
        self.assertEqual(out, [])

    def test_non_marker_comment_ignored(self):
        s = _src("# just a regular comment", "x = 1")
        self.assertEqual(probes.extract_from_source(s, "f.pyk", CATALOG), [])

    def test_in_string_marker_ignored(self):
        # Triple-quoted string contains marker text but tokenize sees STRING,
        # not COMMENT, so no marker should parse.
        s = '"""\n# PROBE-EXPECTS: D0030\n"""\nx = 1\n'
        self.assertEqual(probes.extract_from_source(s, "f.pyk", CATALOG), [])

    def test_duplicate_id_fails(self):
        s = _src(
            "# PROBE-RESOLVES: id=dup",
            "x = 1",
            "# PROBE-RESOLVES: id=dup",
            "y = 2",
        )
        with self.assertRaisesRegex(probes.ProbeError, "duplicate probe id"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_synthesized_id_when_omitted(self):
        s = _src("# PROBE-RESOLVES:", "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertTrue(p.id.startswith("f-L1-"))

    def test_resolves_rejects_on(self):
        s = _src('# PROBE-RESOLVES: on "x"', "x = 1")
        with self.assertRaisesRegex(probes.ProbeError, "does not support"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_target_line_skips_blank_and_comment(self):
        s = _src(
            "# PROBE-RESOLVES:",
            "",
            "# unrelated comment",
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.target_line, 4)

    def test_target_line_decorator(self):
        s = _src(
            "# PROBE-RESOLVES:",
            "@decorator",
            "def f():",
            "    pass",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        # The def is the statement; ast lineno for FunctionDef points at the
        # def keyword line (Python 3.8+).
        self.assertEqual(p.target_line, 3)

    def test_no_following_statement_errors(self):
        s = "# PROBE-RESOLVES:\n"
        with self.assertRaisesRegex(probes.ProbeError, "nonexistent statement"):
            probes.extract_from_source(s, "f.pyk", CATALOG)


class VerifierTests(unittest.TestCase):
    """Stateless tests against canned JSON — no checker invocation."""

    def _probe(self, **kw) -> probes.Probe:
        defaults = dict(
            kind="EXPECTS",
            fixture_path="f.pyk",
            comment_line=1,
            target_line=2,
            id="p",
            rationale=None,
            expected_code=None,
            expected_codes=None,
            expected_count=None,
            span_text=None,
            match_regex=None,
            match_flags=None,
            type_expr=None,
        )
        defaults.update(kw)
        return probes.Probe(**defaults)

    def test_expects_matches(self):
        diag = {
            "file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
            "code": "D0030", "ruleName": "unknownColumn",
            "severity": "error", "source": "pykrete",
            "message": "Column 'foo' does not exist",
            "suggestion": None, "relatedInformation": [],
        }
        actual = {"diagnostics": [diag]}
        p = self._probe(expected_code="D0030")
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_expects_misses(self):
        actual = {"diagnostics": []}
        p = self._probe(expected_code="D0030")
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(len(failures), 1)
        self.assertIn("no diagnostic", failures[0].actual)

    def test_resolves_pass(self):
        actual = {"diagnostics": []}
        p = self._probe(kind="RESOLVES", expected_code=None)
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_resolves_fails_when_diag_present(self):
        diag = {
            "file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
            "code": "D0030", "ruleName": "unknownColumn",
            "severity": "error", "message": "x",
        }
        actual = {"diagnostics": [diag]}
        p = self._probe(kind="RESOLVES", expected_code=None)
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(len(failures), 1)

    def test_stacked_expects_pairing_distinct(self):
        # Two D0030 on the same line, two PROBE-EXPECTS — each consumes one.
        diag1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
                 "code": "D0030", "ruleName": "unknownColumn", "message": "a"}
        diag2 = {"file": "f.pyk", "line": 2, "column": 8, "endLine": 2, "endColumn": 12,
                 "code": "D0030", "ruleName": "unknownColumn", "message": "b"}
        actual = {"diagnostics": [diag1, diag2]}
        p1 = self._probe(expected_code="D0030", id="a")
        p2 = self._probe(expected_code="D0030", id="b")
        failures = probes.verify_against_json([p1, p2], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_stacked_expects_only_one_diag_one_fails(self):
        diag1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
                 "code": "D0030", "ruleName": "unknownColumn", "message": "a"}
        actual = {"diagnostics": [diag1]}
        p1 = self._probe(expected_code="D0030", id="a")
        p2 = self._probe(expected_code="D0030", id="b")
        failures = probes.verify_against_json([p1, p2], actual, "f.pyk")
        self.assertEqual(len(failures), 1)

    def test_file_clean_of_pass(self):
        actual = {"diagnostics": []}
        p = self._probe(kind="FILE-CLEAN-OF", target_line=None, expected_code="D0030")
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_file_clean_of_fail(self):
        diag = {"file": "f.pyk", "line": 5, "column": 1, "endLine": 5, "endColumn": 5,
                "code": "D0030", "ruleName": "unknownColumn", "message": "x"}
        actual = {"diagnostics": [diag]}
        p = self._probe(kind="FILE-CLEAN-OF", target_line=None, expected_code="D0030")
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(len(failures), 1)

    def test_file_count_match(self):
        diag = {"file": "f.pyk", "line": 5, "column": 1, "endLine": 5, "endColumn": 5,
                "code": "D0030", "ruleName": "unknownColumn", "message": "x"}
        actual = {"diagnostics": [diag, dict(diag, line=6)]}
        p = self._probe(kind="FILE-COUNT", target_line=None,
                        expected_code="D0030", expected_count=2)
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_file_count_mismatch(self):
        actual = {"diagnostics": []}
        p = self._probe(kind="FILE-COUNT", target_line=None,
                        expected_code="D0030", expected_count=2)
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(len(failures), 1)
        self.assertIn("0 (lines [])", failures[0].actual)

    def test_on_slot_slices_span(self):
        src = "def f():\n    return col(\"product\")\n"
        # Diagnostic spans cols 16..23 of line 2 (1-indexed): "product"
        diag = {
            "file": "f.pyk", "line": 2, "column": 16, "endLine": 2, "endColumn": 25,
            "code": "D0030", "ruleName": "unknownColumn", "message": "x",
        }
        actual = {"diagnostics": [diag]}
        p = self._probe(expected_code="D0030", span_text="\"product\"")
        failures = probes.verify_against_json(
            [p], actual, "f.pyk", fixture_source=src,
        )
        self.assertEqual(failures, [])

    def test_on_slot_mismatch_fails(self):
        src = "def f():\n    return col(\"product\")\n"
        diag = {
            "file": "f.pyk", "line": 2, "column": 16, "endLine": 2, "endColumn": 25,
            "code": "D0030", "ruleName": "unknownColumn", "message": "x",
        }
        actual = {"diagnostics": [diag]}
        p = self._probe(expected_code="D0030", span_text="region")
        failures = probes.verify_against_json(
            [p], actual, "f.pyk", fixture_source=src,
        )
        self.assertEqual(len(failures), 1)

    def test_match_regex(self):
        diag = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
                "code": "D0030", "ruleName": "unknownColumn",
                "message": "Column 'foo' does not exist on schema 'X'."}
        actual = {"diagnostics": [diag]}
        p = self._probe(expected_code="D0030", match_regex="does not exist", match_flags=None)
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(failures, [])


class CatalogTests(unittest.TestCase):
    def test_loads(self):
        self.assertIn("D0030", CATALOG.codes)
        self.assertIn("D0080", CATALOG.codes)
        self.assertEqual(CATALOG.schema_version, "1")
        self.assertEqual(len(CATALOG.source_commit), 40)

    def test_unknown_schema_version_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write('{"catalogSchemaVersion": "2", "diagnostics": []}')
            path = Path(f.name)
        try:
            with self.assertRaisesRegex(probes.ProbeError, "catalogSchemaVersion"):
                probes.load_catalog(path)
        finally:
            path.unlink()


class TypeNormalizationTests(unittest.TestCase):
    def test_atomic(self):
        self.assertEqual(probes._normalize_type_expr("int"), "int")
        self.assertEqual(probes._normalize_type_expr("string"), "string")

    def test_array_alias(self):
        self.assertEqual(probes._normalize_type_expr("Array[int]"), "array<int>")
        self.assertEqual(probes._normalize_type_expr("array<string>"), "array<string>")

    def test_decimal_param(self):
        self.assertEqual(probes._normalize_type_expr("decimal(10, 2)"), "decimal(10, 2)")
        self.assertEqual(probes._normalize_type_expr("decimal(10,2)"), "decimal(10, 2)")

    def test_unsupported(self):
        with self.assertRaises(probes.ProbeError):
            probes._normalize_type_expr("weirdtype")


def _pykrete_available() -> bool:
    bin_ = os.environ.get("PYKRETE_BIN")
    if bin_:
        if Path(bin_).is_file() and os.access(bin_, os.X_OK):
            return True
        if shutil.which(bin_):
            return True
        return False
    return shutil.which("pykrete") is not None


@unittest.skipUnless(
    _pykrete_available(),
    "PYKRETE_BIN not set / pykrete not on PATH; skipping end-to-end smoke",
)
class EndToEndSmokeTests(unittest.TestCase):
    def test_resolves_passes_expects_fires(self):
        fixture = _src(
            "from pykrete import col",
            "",
            "class Order(Schema):",
            "    region: string",
            "    amount: double",
            "",
            "def f(orders: DataFrame[Order]) -> DataFrame[Order]:",
            "    # PROBE-RESOLVES: id=keeps-region",
            "    df = orders.select(\"region\", \"amount\")",
            "    # PROBE-EXPECTS: D0030 id=drops-product",
            "    return df.select(col(\"product\"))",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smoke.pyk"
            path.write_text(fixture, encoding="utf-8")
            _, failures = probes.verify(path)
        self.assertEqual(failures, [], msg="\n".join(f.actual for f in failures))


if __name__ == "__main__":
    unittest.main()
