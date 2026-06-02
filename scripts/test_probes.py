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
        # Numeric subtypes (double here) are rejected at parse time per the
        # v1.1 carve-out; use a non-numeric atomic to exercise the happy path.
        s = _src('# PROBE-TYPE-IS: string on "name"', "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.kind, "TYPE-IS")
        self.assertEqual(p.type_expr, "string")
        self.assertEqual(p.span_text, "name")

    def test_type_is_array_aliases(self):
        for spelling, canon in [
            ("Array[int]", "array<int>"),
            ("array<int>", "array<int>"),
        ]:
            s = _src(f'# PROBE-TYPE-IS: {spelling} on "items"', "x = 1")
            p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
            self.assertEqual(p.type_expr, canon)

    def test_type_is_decimal_parametric_normalizes(self):
        # decimal(p, s) parses + normalizes, then the numeric-subtype carve-
        # out rejects it. Asserting both forms via the parse-time error keeps
        # coverage of the normalizer path.
        with self.assertRaisesRegex(probes.ProbeError, "numeric-subtype"):
            probes.extract_from_source(
                _src('# PROBE-TYPE-IS: decimal(10,2) on "p"', "x = 1"),
                "f.pyk", CATALOG,
            )
        # Pure normalizer (no marker context) still works as before.
        self.assertEqual(probes._normalize_type_expr("decimal(10,2)"), "decimal(10, 2)")

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
        # The probe itself fails to match the diagnostic, and the unmatched
        # diagnostic on a claimed line becomes an "unclaimed" failure (I1).
        kinds = sorted(f.expected[:14] for f in failures)
        self.assertIn("code D0030 wit", kinds)
        self.assertTrue(any("no unclaimed" in f.expected for f in failures))
        self.assertEqual(len(failures), 2)

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


# ---------------------------------------------------------------------------
# Round-2 regression tests (blockers B1-B9, importants I1-I10).
# Every test in this section maps to a specific finding and would fail
# against the round-1 implementation.
# ---------------------------------------------------------------------------


class ParserRound2Tests(unittest.TestCase):
    """B7 + B8 + I8 + I10: parser/tokenizer hardening."""

    def test_b7_utf8_in_on_slot_preserved(self):
        # `café` must survive verbatim; the round-1 unicode_escape step
        # corrupted non-ASCII to 'cafÃ©'.
        s = _src(
            '# PROBE-EXPECTS: D0030 on "café"',
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.span_text, "café")

    def test_b7_quoted_backslash_escape(self):
        s = _src(
            r'# PROBE-EXPECTS: D0030 on "say \"hi\""',
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.span_text, 'say "hi"')

    def test_b8_double_dash_inside_quoted_span_not_eaten(self):
        # The rationale `--` delimiter must not truncate quoted spans
        # that legitimately contain `--`.
        s = _src(
            '# PROBE-EXPECTS: D0030 on "foo--bar" -- legit rationale',
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.span_text, "foo--bar")
        self.assertEqual(p.rationale, "legit rationale")

    def test_b8_slots_in_any_order_with_dashed_span(self):
        s = _src(
            '# PROBE-EXPECTS: D0030 -- rat on "foo--bar" id=q1',
            "x = 1",
        )
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.span_text, "foo--bar")
        self.assertEqual(p.id, "q1")
        self.assertEqual(p.rationale, "rat")

    def test_i8_indented_marker_treated_as_normal_comment(self):
        # Indented `# PROBE-...` must NOT parse (spec: column-0 invariant).
        s = _src(
            "def f():",
            "    # PROBE-EXPECTS: D0030",
            "    x = 1",
        )
        self.assertEqual(probes.extract_from_source(s, "f.pyk", CATALOG), [])

    def test_i8_indented_typo_does_not_trigger_didyoumean(self):
        # Indented typo shouldn't raise — it's a normal comment.
        s = _src(
            "def f():",
            "    # PROBE-EXPECTSS: D0030",
            "    x = 1",
        )
        self.assertEqual(probes.extract_from_source(s, "f.pyk", CATALOG), [])

    def test_i10_no_tokenize_fallback_on_broken_python(self):
        # Round-1 fell back to a regex line scan when tokenization failed,
        # which re-introduced in-string false matches. The new behavior
        # hard-errors so broken sources never silently leak probes.
        s = '"""\nunterminated docstring with # PROBE-EXPECTS: D0030\nx = 1\n'
        with self.assertRaisesRegex(probes.ProbeError, "failed to tokenize"):
            probes.extract_from_source(s, "f.pyk", CATALOG)


class SynthesizerRound2Tests(unittest.TestCase):
    """B1 + B2 + B6 + B9: per-type distinct, scope-aware, ident-safe, struct-aware."""

    def test_b1_non_numeric_targets_d0081(self):
        # Round-3 directive (TM): within-family numeric-subtype probes are
        # rejected at parse time (see test_numeric_subtype_probe_rejected
        # below), so _TYPE_TARGET only carries non-numeric atomics. Each
        # one fires D0081 by adding a numeric literal to the column.
        from probes import _TYPE_TARGET
        for t in ("string", "binary", "date", "timestamp", "boolean", "bool"):
            self.assertEqual(_TYPE_TARGET[t], "D0081")
        for t in ("int", "long", "short", "byte", "double", "float", "decimal"):
            self.assertNotIn(t, _TYPE_TARGET)

    def test_b2_type_is_synth_injects_inside_enclosing_function(self):
        # Marker at column 0 per spec; its target line resolves to the next
        # logical statement, which is inside `f`. The injected expression
        # must be indented to match the function body, not appended at
        # module scope where `d` is undefined. v1.2: the enclosing function
        # must declare a DataFrame[Schema] parameter for the synth to bind;
        # use `def f(d: DataFrame[S])` so the helper resolves df_ident = "d".
        src = _src(
            "from pykrete import col, lit",
            "from pyspark.sql import DataFrame",
            "class S(Schema):",
            "    name: string",
            "def f(d: DataFrame[S]):",
            "    if True:",
            "# PROBE-TYPE-IS: string on \"name\"",
            "        x = d.select(\"name\")",
            "        return x",
        )
        probes_list = probes.extract_from_source(src, "f.pyk", CATALOG)
        type_probes = [p for p in probes_list if p.kind == "TYPE-IS"]
        self.assertEqual(len(type_probes), 1)
        plan = probes._synthesize_type_probes(src, type_probes)
        synth_lines = plan.appended_source.splitlines()
        injected = [line for line in synth_lines if "_pyk_probe_" in line]
        self.assertTrue(injected, "no injected probe expression found")
        for line in injected:
            self.assertTrue(line.startswith("    "),
                            f"injected line not indented inside function: {line!r}")
            # v1.2: synth wraps in `{df_ident}.select(...)` for typed binding.
            self.assertIn("d.select(", line)

    def test_v12_module_scope_probe_is_unsynthesizable(self):
        # v1.2: module-scope target has no enclosing FunctionDef.args to
        # walk; the probe falls through to the unsynthesizable path. No
        # silent pass — the expectation is recorded as <unsynthesizable>.
        src = _src(
            "from pykrete import col, lit",
            "# PROBE-TYPE-IS: string on \"name\"",
            "df = something",
        )
        probes_list = probes.extract_from_source(src, "f.pyk", CATALOG)
        type_probes = [p for p in probes_list if p.kind == "TYPE-IS"]
        plan = probes._synthesize_type_probes(src, type_probes)
        self.assertEqual(len(plan.expectations), 1)
        _, target_code, _ = plan.expectations[0]
        self.assertEqual(target_code, "<unsynthesizable>")
        # Synth source carries no injected probe statement.
        injected = [line for line in plan.appended_source.splitlines()
                    if "_pyk_probe_" in line]
        self.assertEqual(injected, [])

    def test_b6_dotted_id_yields_valid_python_ident(self):
        ident = probes._safe_ident("a.b-c", 0)
        # Must be a legal Python identifier (no dot, no hyphen).
        import keyword
        import re as _re
        self.assertTrue(_re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident))
        self.assertFalse(keyword.iskeyword(ident))

    def test_b6_purely_invalid_id_falls_back_to_positional(self):
        ident = probes._safe_ident("123-abc", 7)
        self.assertEqual(ident, "_pyk_probe_7")

    def test_b9_dotted_span_renders_as_getfield(self):
        # Round-1 emitted col("addr.city") which Spark / pykrete reads as a
        # literal column lookup, not struct-field access.
        expr = probes._column_accessor("addr.city")
        self.assertEqual(expr, "col('addr').getField('city')")
        # Single-segment: plain col().
        expr2 = probes._column_accessor("amount")
        self.assertEqual(expr2, "col('amount')")
        # Triple-nested: chained getField.
        expr3 = probes._column_accessor("a.b.c")
        self.assertEqual(expr3, "col('a').getField('b').getField('c')")


class V12FirstDataFrameParamTests(unittest.TestCase):
    """v1.2: AST param-resolution helper for the PROBE-TYPE-IS scope-binding fix.

    Covers the annotation-shape policy locked in the v1.2 spec:
    - bare `DataFrame[Schema]` -> match
    - generic wrappers (list[...], Optional[...], Union[...], PEP 604 `... | None`) -> skip
    - string forward refs -> skip (not parsed)
    - type aliases -> skip (no name binder)
    - bare `DataFrame` (no schema parameter) -> skip
    - variadics (*args, **kwargs) -> skip
    - module-scope (no enclosing FunctionDef) -> None at caller
    """

    import ast as _ast

    def _func(self, src: str) -> "probes.ast.FunctionDef":
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                return node
        raise AssertionError(f"no FunctionDef in source: {src!r}")

    def test_single_dataframe_param(self):
        src = "def f(df: DataFrame[A]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "df")

    def test_two_dataframe_params_first_wins(self):
        src = "def f(a: DataFrame[A], b: DataFrame[B]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "a")

    def test_optional_dataframe_skipped(self):
        # Optional[DataFrame[A]] is a generic wrapper; falls through.
        src = "def f(maybe: Optional[DataFrame[A]], df: DataFrame[B]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "df")

    def test_list_dataframe_skipped(self):
        src = "def f(dfs: list[DataFrame[A]], df: DataFrame[B]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "df")

    def test_string_forward_ref_skipped(self):
        # String forward refs are ast.Constant, not ast.Subscript; not parsed.
        src = 'def f(df: "DataFrame[A]") -> DataFrame: ...'
        self.assertIsNone(probes._first_dataframe_param(self._func(src)))

    def test_bare_dataframe_skipped(self):
        # No schema parameter -> annotation is ast.Name, not ast.Subscript.
        src = "def f(df: DataFrame) -> DataFrame: ..."
        self.assertIsNone(probes._first_dataframe_param(self._func(src)))

    def test_variadic_args_skipped(self):
        # *args / **kwargs are never named scalar bindings.
        src = "def f(*dfs: DataFrame[A], **kwargs: DataFrame[B]) -> DataFrame: ..."
        self.assertIsNone(probes._first_dataframe_param(self._func(src)))

    def test_pep604_optional_skipped(self):
        # `DataFrame[A] | None` is ast.BinOp(|), not Subscript.
        src = "def f(maybe: DataFrame[A] | None, df: DataFrame[B]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "df")

    def test_keyword_only_dataframe_matches(self):
        # Positional-or-keyword first, then keyword-only — `kw` is the only
        # DataFrame param so it wins.
        src = "def f(x: int, *, kw: DataFrame[A]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "kw")

    def test_positional_only_first(self):
        # Positional-only walked first.
        src = "def f(a: DataFrame[A], /, b: DataFrame[B]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "a")

    def test_qualified_dataframe_name(self):
        # `pykrete.types.DataFrame[X]` — attribute chain ending in DataFrame.
        src = "def f(df: pykrete.types.DataFrame[A]) -> DataFrame: ..."
        self.assertEqual(probes._first_dataframe_param(self._func(src)), "df")

    def test_module_scope_returns_none(self):
        # `_enclosing_function` returns None at module scope; the synth
        # path treats that as unsynthesizable per spec.
        src = _src(
            "from pykrete import col, lit",
            "x = 1",
        )
        self.assertIsNone(probes._enclosing_function(src, 2))


class V12SynthRewriteTests(unittest.TestCase):
    """v1.2: synthesizer wraps in `{df_ident}.select(...)` and tags
    unsynthesizable on missing DataFrame parameter or module-scope target."""

    def test_synth_wraps_in_df_select(self):
        src = _src(
            "from pyspark.sql import DataFrame",
            "from pyspark.sql.functions import col, lit",
            "class S(Schema):",
            "    label: string",
            "def f(df: DataFrame[S]) -> DataFrame:",
            "# PROBE-TYPE-IS: string on \"label\"",
            "    return df",
        )
        probes_list = probes.extract_from_source(src, "f.pyk", CATALOG)
        type_probes = [p for p in probes_list if p.kind == "TYPE-IS"]
        self.assertEqual(len(type_probes), 1)
        plan = probes._synthesize_type_probes(src, type_probes)
        synth = plan.appended_source
        # Synth must wrap the accessor in df.select(...) using the first
        # DataFrame[Schema] param's ident.
        self.assertIn("df.select(col('label') + lit(1))", synth)
        # And tag as the D0081 target (string -> non-numeric arithmetic).
        self.assertEqual(plan.expectations[0][1], "D0081")

    def test_synth_picks_first_dataframe_param(self):
        # Two DataFrame params; first-wins binds to `a`.
        src = _src(
            "from pyspark.sql import DataFrame",
            "from pyspark.sql.functions import col, lit",
            "class A(Schema):",
            "    label: string",
            "class B(Schema):",
            "    label: string",
            "def f(a: DataFrame[A], b: DataFrame[B]) -> DataFrame:",
            "# PROBE-TYPE-IS: string on \"label\"",
            "    return a",
        )
        probes_list = probes.extract_from_source(src, "f.pyk", CATALOG)
        type_probes = [p for p in probes_list if p.kind == "TYPE-IS"]
        plan = probes._synthesize_type_probes(src, type_probes)
        self.assertIn("a.select(col('label') + lit(1))", plan.appended_source)

    def test_synth_unsynthesizable_when_no_dataframe_param(self):
        # Function takes a non-DataFrame parameter — probe is unsynthesizable
        # per the v1.2 "no silent pass" rule, not synthesized as a bare expr.
        src = _src(
            "from pyspark.sql.functions import col, lit",
            "def f(spark):",
            "# PROBE-TYPE-IS: string on \"label\"",
            "    return spark",
        )
        probes_list = probes.extract_from_source(src, "f.pyk", CATALOG)
        type_probes = [p for p in probes_list if p.kind == "TYPE-IS"]
        plan = probes._synthesize_type_probes(src, type_probes)
        self.assertEqual(plan.expectations[0][1], "<unsynthesizable>")
        injected = [line for line in plan.appended_source.splitlines()
                    if "_pyk_probe_" in line]
        self.assertEqual(injected, [])


class VerifierRound2Tests(unittest.TestCase):
    """B4 + B5 + I1 + I6 + I9 (parts covered in checker tests below)."""

    def _probe(self, **kw) -> probes.Probe:
        defaults = dict(
            kind="EXPECTS",
            fixture_path="f.pyk",
            comment_line=1,
            target_line=2,
            id="p",
        )
        defaults.update(kw)
        return probes.Probe(**defaults)

    def test_b4_bipartite_distinct_matching_n_eq_m(self):
        d1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
              "code": "D0030", "ruleName": "u", "message": "a"}
        d2 = {"file": "f.pyk", "line": 2, "column": 8, "endLine": 2, "endColumn": 12,
              "code": "D0030", "ruleName": "u", "message": "b"}
        actual = {"diagnostics": [d1, d2]}
        p1 = self._probe(expected_code="D0030", id="p1")
        p2 = self._probe(expected_code="D0030", id="p2")
        failures = probes.verify_against_json([p1, p2], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_b4_bipartite_uses_augmentation_when_first_fit_blocks(self):
        # Two probes, two candidates. Probe p1 only matches d1 (via on);
        # probe p2 matches both d1 and d2. Greedy first-fit would let
        # p2 grab d1, then p1 has nothing. Bipartite must reassign.
        src = "x = y + z\n"
        # Build candidates so d1 has span "y" and d2 has span "z".
        d1 = {"file": "f.pyk", "line": 1, "column": 5, "endLine": 1, "endColumn": 6,
              "code": "D0030", "ruleName": "u", "message": "first"}
        d2 = {"file": "f.pyk", "line": 1, "column": 9, "endLine": 1, "endColumn": 10,
              "code": "D0030", "ruleName": "u", "message": "second"}
        actual = {"diagnostics": [d1, d2]}
        # p2 is unrestricted (no span); p1 pins span "y".
        # Sort order: p2 then p1; first-fit would assign p2->d1, p1 left
        # with d2 whose span is "z" not "y", so p1 fails. Bipartite augments.
        p2 = self._probe(expected_code="D0030", id="p2", target_line=1)
        p1 = self._probe(expected_code="D0030", id="p1", target_line=1, span_text="y")
        failures = probes.verify_against_json(
            [p2, p1], actual, "f.pyk", fixture_source=src,
        )
        self.assertEqual(failures, [])

    def test_b4_n_gt_m_one_probe_fails(self):
        d1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
              "code": "D0030", "ruleName": "u", "message": "a"}
        actual = {"diagnostics": [d1]}
        p1 = self._probe(expected_code="D0030", id="p1")
        p2 = self._probe(expected_code="D0030", id="p2")
        failures = probes.verify_against_json([p1, p2], actual, "f.pyk")
        # Exactly one probe should fail; no unclaimed-extra.
        probe_failures = [f for f in failures if "_unclaimed" not in f.probe.id]
        self.assertEqual(len(probe_failures), 1)

    def test_b4_same_code_different_line_independent(self):
        d1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
              "code": "D0030", "ruleName": "u", "message": "a"}
        d2 = {"file": "f.pyk", "line": 5, "column": 1, "endLine": 5, "endColumn": 5,
              "code": "D0030", "ruleName": "u", "message": "b"}
        actual = {"diagnostics": [d1, d2]}
        p1 = self._probe(expected_code="D0030", target_line=2, id="p1")
        p2 = self._probe(expected_code="D0030", target_line=5, id="p2")
        failures = probes.verify_against_json([p1, p2], actual, "f.pyk")
        self.assertEqual(failures, [])

    def test_b5_basename_donor_collision_caught_by_relpath_match(self):
        # Two donors with the same fixture filename ("transforms.pyk").
        # Diagnostic against donor A must not satisfy a probe from donor B.
        d_from_a = {
            "file": "cross-codebase/quinn/annotated/transforms.pyk",
            "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
            "code": "D0030", "ruleName": "u", "message": "x",
        }
        actual = {"diagnostics": [d_from_a]}
        p = self._probe(expected_code="D0030", target_line=2,
                        fixture_path="cross-codebase/sparklab/annotated/transforms.pyk")
        # When given fixture_relpath = donor B's path, donor A diag doesn't
        # match it.
        failures = probes.verify_against_json(
            [p], actual, "transforms.pyk",
            fixture_relpath="cross-codebase/sparklab/annotated/transforms.pyk",
        )
        self.assertEqual(len(failures), 1)

    def test_i1_unclaimed_extra_diagnostic_surfaces(self):
        # Probe expects one D0030; checker fires two. Round-1 silently
        # accepted; round-2 surfaces the extra.
        d1 = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
              "code": "D0030", "ruleName": "u", "message": "claimed"}
        d2 = {"file": "f.pyk", "line": 2, "column": 8, "endLine": 2, "endColumn": 12,
              "code": "D0030", "ruleName": "u", "message": "extra"}
        actual = {"diagnostics": [d1, d2]}
        p = self._probe(expected_code="D0030", id="p1")
        failures = probes.verify_against_json([p], actual, "f.pyk")
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].probe.id.startswith("_unclaimed"))

    def test_i6_on_slot_requires_fixture_source_no_silent_fallback(self):
        # Round-1 silently fell back to substring-of-message match.
        d = {"file": "f.pyk", "line": 2, "column": 1, "endLine": 2, "endColumn": 5,
             "code": "D0030", "ruleName": "u",
             "message": "the column foo does not exist"}
        actual = {"diagnostics": [d]}
        p = self._probe(expected_code="D0030", span_text="foo")
        # Without fixture_source, the `on` constraint cannot be checked.
        # The probe itself fails to match (no candidate), and the unmatched
        # diagnostic on the claimed line surfaces as unclaimed-extra (I1).
        # The substring-fallback behaviour from round-1 is gone.
        failures = probes.verify_against_json([p], actual, "f.pyk")
        # The probe failure (no fixture_source means we can't match span).
        probe_failures = [f for f in failures if not f.probe.id.startswith("_unclaimed")]
        self.assertEqual(len(probe_failures), 1)
        self.assertIn("D0030", probe_failures[0].expected)


class StagingRound2Tests(unittest.TestCase):
    """B3: full-directory staging so cross-file imports resolve."""

    def test_b3_staging_copies_sibling_files(self):
        # Set up a 2-file fixture: main.pyk + schema.pyk.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "schema.pyk").write_text("# sibling module\n", encoding="utf-8")
            main = d / "main.pyk"
            main.write_text("# main\nx = 1\n", encoding="utf-8")
            # Drive _stage_and_check, intercepting the inner _run_checker so
            # we just observe what gets staged.
            captured = {}
            real_run = probes._run_checker

            def fake_run(p, *, strict=False):
                captured["path"] = p
                captured["siblings"] = sorted(x.name for x in p.parent.iterdir())
                return {"diagnostics": []}
            probes._run_checker = fake_run  # type: ignore[assignment]
            try:
                probes._stage_and_check("# main\nx = 1\n", main, strict=False)
            finally:
                probes._run_checker = real_run  # type: ignore[assignment]
            self.assertIn("schema.pyk", captured["siblings"])
            self.assertIn("main.pyk", captured["siblings"])


class CliRound2Tests(unittest.TestCase):
    """I2 + I3 + I4 + I5: CLI hardening."""

    def test_i4_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            probes.main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_i4_help_flag(self):
        with self.assertRaises(SystemExit) as cm:
            probes.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_i4_unknown_subcommand_errors(self):
        with self.assertRaises(SystemExit):
            probes.main(["nonsense"])

    def test_i5_failed_probe_ids_in_run_output(self):
        # Drive _cmd_run by hand against a fixture that will fail.
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "f.pyk"
            fixture.write_text(
                "# PROBE-RESOLVES: id=will-fail\n"
                "x = 1\n",
                encoding="utf-8",
            )
            # Stub verify to return a synthetic failure.
            real_verify = probes.verify

            def fake_verify(path, **kw):
                p = probes.Probe(
                    kind="RESOLVES", fixture_path=str(path),
                    comment_line=1, target_line=2, id="will-fail",
                )
                return [p], [probes.ProbeFailure(probe=p, expected="x", actual="y")]
            probes.verify = fake_verify  # type: ignore[assignment]
            # Capture stdout.
            import io as _io
            real_stdout = sys.stdout
            sys.stdout = _io.StringIO()
            try:
                exit_code = probes.main(["run", str(tmp)])
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = real_stdout
                probes.verify = real_verify  # type: ignore[assignment]
            self.assertEqual(exit_code, 1)
            import json as _json
            payload = _json.loads(out)
            self.assertIn("failedProbeIds", payload)
            self.assertEqual(len(payload["failedProbeIds"]), 1)
            self.assertIn("will-fail", payload["failedProbeIds"][0])

    def test_i3_missing_pykrete_bin_raises_named_error(self):
        old = os.environ.get("PYKRETE_BIN")
        os.environ["PYKRETE_BIN"] = "/this/path/definitely/does/not/exist/pykrete"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "f.pyk"
                f.write_text("x = 1\n", encoding="utf-8")
                with self.assertRaises(probes.CheckerError) as cm:
                    probes._run_checker(f)
                self.assertIn("PYKRETE_BIN", str(cm.exception))
                self.assertIn("not found", str(cm.exception))
        finally:
            if old is None:
                del os.environ["PYKRETE_BIN"]
            else:
                os.environ["PYKRETE_BIN"] = old

    def test_i2_timeout_raises_checker_error(self):
        # Use a tiny script that sleeps forever as the "pykrete binary".
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake_pykrete.sh"
            fake.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
            fake.chmod(0o755)
            f = Path(tmp) / "f.pyk"
            f.write_text("x = 1\n", encoding="utf-8")
            old_bin = os.environ.get("PYKRETE_BIN")
            old_to = os.environ.get("PYKRETE_TIMEOUT")
            os.environ["PYKRETE_BIN"] = str(fake)
            os.environ["PYKRETE_TIMEOUT"] = "1"
            try:
                with self.assertRaises(probes.CheckerError) as cm:
                    probes._run_checker(f)
                self.assertIn("timed out", str(cm.exception))
            finally:
                if old_bin is None:
                    del os.environ["PYKRETE_BIN"]
                else:
                    os.environ["PYKRETE_BIN"] = old_bin
                if old_to is None:
                    if "PYKRETE_TIMEOUT" in os.environ:
                        del os.environ["PYKRETE_TIMEOUT"]
                else:
                    os.environ["PYKRETE_TIMEOUT"] = old_to


class PerDonorIdUniquenessTests(unittest.TestCase):
    """I7: per-donor (cross-file) probe id uniqueness."""

    def test_donor_root_extracts_donor_segment(self):
        donor = probes._donor_root(Path("cross-codebase/quinn/annotated/file.pyk"))
        self.assertEqual(donor, "quinn")

    def test_donor_root_fallback_outside_cross_codebase(self):
        donor = probes._donor_root(Path("/tmp/foo/bar.pyk"))
        self.assertEqual(donor, "foo")


@unittest.skipUnless(
    _pykrete_available(),
    "PYKRETE_BIN not set / pykrete not on PATH; skipping end-to-end smoke",
)
class EndToEndSmokeTests(unittest.TestCase):
    def test_resolves_passes_expects_fires(self):
        # Markers must be at column 0 (spec I8). The body indentation makes
        # this awkward to write inline; the runner only looks at marker
        # column position, not at the target statement's position.
        fixture = (
            "from pykrete import col\n"
            "\n"
            "class Order(Schema):\n"
            "    region: string\n"
            "    amount: double\n"
            "\n"
            "def f(orders: DataFrame[Order]) -> DataFrame[Order]:\n"
            "# PROBE-RESOLVES: id=keeps-region\n"
            "    df = orders.select(\"region\", \"amount\")\n"
            # The span slice covers `\"product\"` literally (quotes included)
            # because pykrete's diagnostic column range covers the string lit.
            "# PROBE-EXPECTS: D0030 id=drops-product on \"\\\"product\\\"\"\n"
            "# PROBE-EXPECTS: D0050 id=drops-product-d0050\n"
            "    return df.select(col(\"product\"))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smoke.pyk"
            path.write_text(fixture, encoding="utf-8")
            _, failures = probes.verify(path)
        self.assertEqual(failures, [], msg="\n".join(f.actual for f in failures))

    def test_type_is_synth_runs_without_crash(self):
        # v1.2: the synth wraps the accessor in `{df_ident}.select(...)`,
        # binding `col("region")` to orders' tracked schema. region IS string,
        # so D0081 fires (lit(1) + string = non-numeric arithmetic) and the
        # probe passes. v1.1 was silent-inconclusive here; v1.2 is honest.
        fixture = (
            "from pykrete import col, lit\n"
            "\n"
            "class Order(Schema):\n"
            "    region: string\n"
            "    amount: double\n"
            "\n"
            "def f(orders: DataFrame[Order]) -> DataFrame[Order]:\n"
            "# PROBE-TYPE-IS: string on \"region\" id=region-is-str\n"
            "    return orders\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smoke_type.pyk"
            path.write_text(fixture, encoding="utf-8")
            probes_list, failures = probes.verify(path)
        self.assertEqual(len(probes_list), 1)
        self.assertEqual(failures, [], msg="\n".join(f.actual for f in failures))


# ---------------------------------------------------------------------------
# Round-3 closeout tests.
# ---------------------------------------------------------------------------


class Round3ClosesOutTests(unittest.TestCase):
    """B1 parse-time numeric reject, B5 production wiring, B7/B8 docs+tests, I9 crash."""

    def test_numeric_subtype_probe_rejected_at_parse_time(self):
        # B1: every numeric subtype is rejected at parse time. Trust claim
        # is "v1.1 verifies schema tracking correctness"; a vacuous green
        # on int-vs-double would violate it.
        for t in ("int", "long", "short", "byte", "double", "float", "decimal"):
            s = _src(f'# PROBE-TYPE-IS: {t} on "amount"', "x = 1")
            with self.assertRaisesRegex(
                probes.ProbeError, "numeric-subtype assertion"
            ):
                probes.extract_from_source(s, "f.pyk", CATALOG)
        # Cross-family stays clean.
        s = _src('# PROBE-TYPE-IS: string on "name"', "x = 1")
        out = probes.extract_from_source(s, "f.pyk", CATALOG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].type_expr, "string")

    def test_numeric_subtype_decimal_parametric_also_rejected(self):
        s = _src('# PROBE-TYPE-IS: decimal(10,2) on "p"', "x = 1")
        with self.assertRaisesRegex(probes.ProbeError, "numeric-subtype"):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_b8_unterminated_quoted_string_hard_fails(self):
        # Round-2 silently swallowed unterminated quoted spans (the slot
        # regex didn't match, the outer scanner consumed to EOL). Now the
        # tokenizer raises a named ParseError on the marker line.
        s = _src('# PROBE-EXPECTS: D0030 on "foo', "x = 1")
        with self.assertRaisesRegex(
            probes.ProbeError, "unterminated quoted string"
        ):
            probes.extract_from_source(s, "f.pyk", CATALOG)

    def test_b7_literal_backslash_n_not_a_newline(self):
        # B7 escape behavior: only \" and \\ are unescaped. \n is preserved
        # as the two-character sequence backslash + n, NOT a newline. This
        # locks the documented behavior (see scripts/PROBES.md "Quoting rules").
        s = _src(r'# PROBE-EXPECTS: D0030 on "a\nb"', "x = 1")
        p = probes.extract_from_source(s, "f.pyk", CATALOG)[0]
        self.assertEqual(p.span_text, "a\\nb")
        self.assertNotIn("\n", p.span_text)

    def test_i9_empty_stdout_with_nonzero_exit_is_crash(self):
        # B-script that exits 1 with empty stdout — must surface as
        # CheckerError, not silently parse as "no diagnostics".
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "crashing_pykrete.sh"
            fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake.chmod(0o755)
            f = Path(tmp) / "f.pyk"
            f.write_text("x = 1\n", encoding="utf-8")
            old = os.environ.get("PYKRETE_BIN")
            os.environ["PYKRETE_BIN"] = str(fake)
            try:
                with self.assertRaises(probes.CheckerError) as cm:
                    probes._run_checker(f)
                self.assertIn("empty stdout", str(cm.exception))
                self.assertIn("crash", str(cm.exception))
            finally:
                if old is None:
                    del os.environ["PYKRETE_BIN"]
                else:
                    os.environ["PYKRETE_BIN"] = old

    def test_two_donors_same_basename(self):
        # B5 end-to-end: two fixtures with the same basename under different
        # donor roots. Each probe must only pass on its own donor's diagnostic.
        # We stub _run_checker so the test does not need a real pykrete binary.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cross-codebase"
            donor_a = root / "donor_a" / "annotated"
            donor_b = root / "donor_b" / "annotated"
            donor_a.mkdir(parents=True)
            donor_b.mkdir(parents=True)
            fixture_a = donor_a / "x.pyk"
            fixture_b = donor_b / "x.pyk"
            # Each fixture has a PROBE-RESOLVES on its own line 2.
            # If diagnostics leaked across donors, donor_b's RESOLVES would
            # incorrectly see the diagnostic that pykrete fires for donor_a.
            fixture_a.write_text(
                "# PROBE-RESOLVES: id=a-clean\n"
                "x = 1\n",
                encoding="utf-8",
            )
            fixture_b.write_text(
                "# PROBE-RESOLVES: id=b-clean\n"
                "x = 1\n",
                encoding="utf-8",
            )

            # Fake checker: emits a D0030 on whichever fixture it's asked
            # about. The diagnostic file is the staged tempdir copy's name.
            real_run = probes._run_checker

            def fake_run(p, *, strict=False):
                return {
                    "diagnostics": [
                        {
                            "file": p.name,
                            "line": 2,
                            "column": 1,
                            "endLine": 2,
                            "endColumn": 2,
                            "code": "D0030",
                            "ruleName": "u",
                            "message": "fake",
                        }
                    ]
                }

            probes._run_checker = fake_run  # type: ignore[assignment]
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                # Drive _cmd_run end-to-end through main() so the relpath
                # threading is exercised in production.
                import io as _io
                stdout_buf = _io.StringIO()
                real_stdout = sys.stdout
                sys.stdout = stdout_buf
                try:
                    exit_code = probes.main(["run", "cross-codebase"])
                finally:
                    sys.stdout = real_stdout
            finally:
                probes._run_checker = real_run  # type: ignore[assignment]
                os.chdir(old_cwd)

            # Both fixtures should report a RESOLVES failure (their own
            # diagnostic fires on line 2). Neither should vacuously pass
            # because the other donor's diag matched their basename.
            self.assertEqual(exit_code, 1)
            import json as _json
            payload = _json.loads(stdout_buf.getvalue())
            failed_ids = payload["failedProbeIds"]
            joined = " ".join(failed_ids)
            self.assertIn("a-clean", joined)
            self.assertIn("b-clean", joined)
            self.assertEqual(payload["probesTotal"], 2)
            self.assertEqual(payload["failuresTotal"], 2)


class FixtureRelpathTests(unittest.TestCase):
    def test_relpath_for_cross_codebase_fixture(self):
        rp = probes._fixture_relpath(Path("cross-codebase/quinn/annotated/f.pyk"))
        self.assertEqual(rp, "quinn/annotated/f.pyk")

    def test_relpath_for_non_cross_codebase_fixture(self):
        # Outside cross-codebase, falls back to a CWD-relative or absolute
        # POSIX path — but the test just checks it's a string (env-dependent).
        rp = probes._fixture_relpath(Path("/tmp/foo/bar.pyk"))
        self.assertIsInstance(rp, str)
        self.assertTrue(rp.endswith("foo/bar.pyk"))


# PR #3a (v1.1 split): the gate-flip in PR #3c is only safe if the runner
# actually fails when a probe's expectation is broken. This test seeds a
# real probes_negative/ fixture, mutates the captured diagnostics in two
# ways the gate must catch (dropped expected diagnostic; injected unrelated
# diagnostic on the probe-claimed line), and asserts verify_against_json
# returns ProbeFailure entries both times. Without this regression test,
# a refactor that quietly broadened "pass" to include silent-no-op would
# only surface when a CI run on real code happened to produce no diags.
REPO_ROOT = Path(__file__).resolve().parent.parent


class NegativeProbeCoverageRegressionTests(unittest.TestCase):
    """PR #3a gate-flip safety: the runner must catch deliberately-broken probes."""

    NEG_FIXTURE = (
        REPO_ROOT
        / "cross-codebase"
        / "spark"
        / "probes_negative"
        / "drop_then_reference.pyk"
    )

    def _load_fixture_and_golden(self):
        self.assertTrue(
            self.NEG_FIXTURE.is_file(),
            f"probes_negative fixture missing: {self.NEG_FIXTURE}",
        )
        golden_path = self.NEG_FIXTURE.with_suffix(".golden.json")
        self.assertTrue(
            golden_path.is_file(),
            f"paired golden missing: {golden_path}",
        )
        source = self.NEG_FIXTURE.read_text(encoding="utf-8")
        golden = probes.json.loads(golden_path.read_text(encoding="utf-8"))
        relpath = probes._fixture_relpath(self.NEG_FIXTURE)
        probes_list = probes.extract(self.NEG_FIXTURE, catalog=CATALOG)
        non_type = [p for p in probes_list if p.kind != "TYPE-IS"]
        self.assertTrue(non_type, "fixture must declare at least one non-TYPE-IS probe")
        return source, golden, relpath, non_type

    def test_baseline_golden_satisfies_probes(self):
        # Sanity check before mutation: the unmutated golden must satisfy
        # every probe. Otherwise the negative-mutation assertions below are
        # vacuous.
        source, golden, relpath, non_type = self._load_fixture_and_golden()
        failures = probes.verify_against_json(
            non_type,
            golden,
            self.NEG_FIXTURE.name,
            fixture_source=source,
            fixture_relpath=relpath,
        )
        self.assertEqual(
            failures, [],
            msg="\n".join(f"{f.probe.id}: {f.actual}" for f in failures),
        )

    def test_dropping_expected_diagnostic_fails(self):
        # Mutate: drop one diagnostic that a PROBE-EXPECTS targets. The
        # runner MUST surface a failure — silent pass here would mean a
        # refactor could regress the checker without anyone noticing.
        source, golden, relpath, non_type = self._load_fixture_and_golden()
        expects_probes = [p for p in non_type if p.kind == "EXPECTS"]
        self.assertTrue(expects_probes, "fixture must have at least one PROBE-EXPECTS")
        target_probe = expects_probes[0]
        mutated = dict(golden)
        mutated["diagnostics"] = [
            d for d in golden["diagnostics"]
            if not (
                d.get("code") == target_probe.expected_code
                and d.get("line") == target_probe.target_line
            )
        ]
        self.assertNotEqual(
            len(mutated["diagnostics"]),
            len(golden["diagnostics"]),
            "mutation must actually drop a diagnostic",
        )
        failures = probes.verify_against_json(
            non_type,
            mutated,
            self.NEG_FIXTURE.name,
            fixture_source=source,
            fixture_relpath=relpath,
        )
        self.assertTrue(
            failures,
            "runner returned no failures despite a dropped expected diagnostic",
        )
        self.assertTrue(
            any(f.probe.id == target_probe.id for f in failures),
            f"expected a ProbeFailure naming {target_probe.id!r}, got"
            f" {[f.probe.id for f in failures]!r}",
        )

    def test_injecting_unrelated_diagnostic_fails(self):
        # Mutate: add an unexpected diagnostic on the probe-claimed line.
        # The bipartite matcher's "unclaimed extra diagnostic" rule (I1)
        # must surface this — without it, a checker that emits noise
        # alongside the expected diagnostic could slip a regression past
        # the gate.
        source, golden, relpath, non_type = self._load_fixture_and_golden()
        expects_probes = [p for p in non_type if p.kind == "EXPECTS"]
        target_probe = expects_probes[0]
        injected = {
            "code": "D0050",
            "ruleName": "returnColumnsMismatch",
            "severity": "error",
            "source": "pykrete",
            "message": "synthetic unrelated diagnostic for regression test",
            "file": target_probe.fixture_path,
            "line": target_probe.target_line,
            "column": 1,
            "endLine": target_probe.target_line,
            "endColumn": 2,
            "suggestion": None,
            "relatedInformation": [],
        }
        mutated = dict(golden)
        mutated["diagnostics"] = list(golden["diagnostics"]) + [injected]
        failures = probes.verify_against_json(
            non_type,
            mutated,
            self.NEG_FIXTURE.name,
            fixture_source=source,
            fixture_relpath=relpath,
        )
        self.assertTrue(
            failures,
            "runner returned no failures despite an injected unrelated diagnostic",
        )
        self.assertTrue(
            any("unclaimed" in f.expected for f in failures),
            f"expected an 'unclaimed' failure for the injected diagnostic, got"
            f" expected={[f.expected for f in failures]!r}",
        )


if __name__ == "__main__":
    unittest.main()
