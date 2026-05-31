#!/usr/bin/env python3
"""Schema-tracking probes for pykrete-tests (v1.1).

Spec: pykrete repo `docs/design/schema-tracking-probes.md` (commit 565183e).

Usage:
    python scripts/probes.py extract <fixture.pyk>
    python scripts/probes.py verify <fixture.pyk>
    python scripts/probes.py run [<path>...]   # default scope; recursive

Env vars:
    PYKRETE_BIN   path to the pykrete binary (default: `pykrete` on PATH)
    PROBES_CATALOG  path to diagnostic_catalog.json (default: sibling of this script)

Exit codes:
    0   all probes satisfied (or no probes found)
    1   at least one probe failed
    2   usage error / parse error / catalog drift
"""

from __future__ import annotations

import ast
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

# Single source of truth for the probes-layer schema version.
PROBES_SCHEMA_VERSION = "1"

ProbeKind = Literal[
    "EXPECTS",
    "RESOLVES",
    "TYPE-IS",
    "FILE-CLEAN-OF",
    "FILE-COUNT",
]

_ALLOWED_KINDS: tuple[str, ...] = (
    "EXPECTS",
    "RESOLVES",
    "TYPE-IS",
    "FILE-CLEAN-OF",
    "FILE-COUNT",
)


# ---------------------------------------------------------------------------
# Data classes (probesSchemaVersion: 1 — stable, frozen, additive-only).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    kind: ProbeKind
    fixture_path: str
    comment_line: int
    target_line: Optional[int]
    id: str
    rationale: Optional[str] = None
    expected_code: Optional[str] = None
    expected_codes: Optional[tuple[str, ...]] = None
    expected_count: Optional[int] = None
    span_text: Optional[str] = None
    match_regex: Optional[str] = None
    match_flags: Optional[str] = None
    type_expr: Optional[str] = None


@dataclass(frozen=True)
class ProbeFailure:
    probe: Probe
    expected: str
    actual: str


# ---------------------------------------------------------------------------
# Catalog handling.
# ---------------------------------------------------------------------------


class ProbeError(Exception):
    """Raised for parse/catalog errors that the user should fix."""


@dataclass(frozen=True)
class Catalog:
    schema_version: str
    source_commit: str
    codes: frozenset[str]
    by_code: dict[str, dict]

    def has(self, code: str) -> bool:
        return code in self.codes


def load_catalog(path: Optional[Path] = None) -> Catalog:
    if path is None:
        env = os.environ.get("PROBES_CATALOG")
        path = Path(env) if env else Path(__file__).parent / "diagnostic_catalog.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProbeError(f"diagnostic catalog not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProbeError(f"diagnostic catalog at {path} is not valid JSON: {exc}") from exc
    schema_version = data.get("catalogSchemaVersion")
    if schema_version != "1":
        raise ProbeError(
            f"unsupported catalogSchemaVersion {schema_version!r} (expected '1')"
        )
    source_commit = data.get("pykreteSourceCommit", "")
    entries = data.get("diagnostics") or []
    codes = {e["code"] for e in entries}
    by_code = {e["code"]: e for e in entries}
    return Catalog(
        schema_version=schema_version,
        source_commit=source_commit,
        codes=frozenset(codes),
        by_code=by_code,
    )


# ---------------------------------------------------------------------------
# Marker grammar.
# ---------------------------------------------------------------------------

# The strict regex for the leading marker comment ("# PROBE-<KIND>:" / "# PROBE-<KIND>").
# Captures kind (uppercase + hyphen + uppercase) and the rest (may be empty).
_MARKER_HEAD = re.compile(r"^\s*#\s*PROBE-([A-Z][A-Z\-]*)\b\s*:?\s*(.*?)\s*$")

# A laxer probe-detector (used to surface typos and silent-skip far drift).
# Matches anything that starts "# PROBE-..." even if the kind is misspelled.
_MARKER_DETECT = re.compile(r"^\s*#\s*PROBE-([A-Z][A-Z\-]*)\b\s*(:|\s|$)")


def _strip_id_slot(text: str) -> tuple[str, Optional[str]]:
    """Pull `id=<handle>` out of text; return (rest, id_or_none)."""
    m = re.search(r"\bid=([A-Za-z0-9_.\-]+)", text)
    if not m:
        return text, None
    return (text[: m.start()] + text[m.end() :]).strip(), m.group(1)


def _strip_rationale_slot(text: str) -> tuple[str, Optional[str]]:
    """Pull `-- <rationale>` (to end of line) out of text."""
    m = re.search(r"\s--\s+(.+?)\s*$", text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)


def _strip_on_slot(text: str) -> tuple[str, Optional[str]]:
    """Pull `on "<text>"` out of text. Supports \\" escape."""
    m = re.search(r'\bon\s+"((?:[^"\\]|\\.)*)"', text)
    if not m:
        return text, None
    span = m.group(1).encode("utf-8").decode("unicode_escape")
    return (text[: m.start()] + text[m.end() :]).strip(), span


def _strip_match_slot(text: str) -> tuple[str, Optional[str], Optional[str]]:
    """Pull `match /<regex>/[flags]` out of text. Returns (rest, regex, flags)."""
    # Regex bodies are between forward slashes; backslash escapes any char.
    m = re.search(r"\bmatch\s+/((?:[^/\\]|\\.)*)/([imsx]*)", text)
    if not m:
        return text, None, None
    return (text[: m.start()] + text[m.end() :]).strip(), m.group(1), m.group(2) or None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        curr = [j]
        for i, ca in enumerate(a, 1):
            curr.append(min(prev[i] + 1, curr[-1] + 1, prev[i - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _suggest_kind(bad: str) -> Optional[str]:
    candidates = [(k, _levenshtein(bad, k)) for k in _ALLOWED_KINDS]
    candidates.sort(key=lambda x: x[1])
    best_kind, best_dist = candidates[0]
    if best_dist <= 2:
        return best_kind
    return None


def _parse_marker(
    fixture_path: str,
    line_no: int,
    raw_line: str,
    catalog: Catalog,
) -> Optional[dict]:
    """Parse one comment line into a partial probe dict, or None if not a marker.

    Raises ProbeError on malformed but recognized markers.
    """
    head = _MARKER_HEAD.match(raw_line)
    if not head:
        detect = _MARKER_DETECT.match(raw_line)
        if not detect:
            return None
        bad_kind = detect.group(1)
        suggestion = _suggest_kind(bad_kind)
        if suggestion is not None and bad_kind != suggestion:
            raise ProbeError(
                f"{fixture_path}:{line_no}: unknown probe kind 'PROBE-{bad_kind}'"
                f" — did you mean 'PROBE-{suggestion}'?"
            )
        # Far drift: silently skip so future unrelated `# PROBE-FOO` upstream
        # comments don't red-fail CI. (See spec round-1 Q6.)
        return None

    kind_raw, body = head.group(1), head.group(2)
    if kind_raw not in _ALLOWED_KINDS:
        suggestion = _suggest_kind(kind_raw)
        if suggestion is not None and kind_raw != suggestion:
            raise ProbeError(
                f"{fixture_path}:{line_no}: unknown probe kind 'PROBE-{kind_raw}'"
                f" — did you mean 'PROBE-{suggestion}'?"
            )
        return None

    rest, rationale = _strip_rationale_slot(body)
    rest, probe_id = _strip_id_slot(rest)
    rest, span = _strip_on_slot(rest)
    rest, match_regex, match_flags = _strip_match_slot(rest)

    partial: dict = {
        "kind": kind_raw,
        "fixture_path": fixture_path,
        "comment_line": line_no,
        "id": probe_id,
        "rationale": rationale,
        "span_text": span,
        "match_regex": match_regex,
        "match_flags": match_flags,
    }

    if kind_raw == "EXPECTS":
        # Required: a D-code as the first remaining token.
        m = re.match(r"^(D\d{4})\b\s*(.*)$", rest)
        if not m:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-EXPECTS requires a D-code"
                f" (e.g. `PROBE-EXPECTS: D0030`); got body {body!r}"
            )
        code, leftover = m.group(1), m.group(2).strip()
        if leftover:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-EXPECTS has unrecognized trailing text:"
                f" {leftover!r}"
            )
        if not catalog.has(code):
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-EXPECTS references unknown D-code {code!r};"
                f" not present in vendored diagnostic catalog"
            )
        partial["expected_code"] = code

    elif kind_raw == "RESOLVES":
        if rest:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-RESOLVES takes no positional args;"
                f" leftover {rest!r}"
            )
        if span is not None or match_regex is not None:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-RESOLVES does not support `on` / `match`"
            )

    elif kind_raw == "TYPE-IS":
        if match_regex is not None:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-TYPE-IS does not support `match`"
            )
        if span is None:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-TYPE-IS requires `on \"<column>\"`"
            )
        type_expr = rest.strip()
        if not type_expr:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-TYPE-IS requires a type expression"
                f" (e.g. `PROBE-TYPE-IS: double on \"amount\"`)"
            )
        try:
            type_expr = _normalize_type_expr(type_expr)
        except ProbeError as exc:
            raise ProbeError(f"{fixture_path}:{line_no}: {exc}") from exc
        partial["type_expr"] = type_expr

    elif kind_raw == "FILE-CLEAN-OF":
        if span is not None or match_regex is not None:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-FILE-CLEAN-OF does not support"
                f" `on` / `match`"
            )
        codes = [c.strip() for c in rest.split(",") if c.strip()]
        if not codes:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-FILE-CLEAN-OF requires at least one D-code"
            )
        for code in codes:
            if not re.fullmatch(r"D\d{4}", code):
                raise ProbeError(
                    f"{fixture_path}:{line_no}: invalid D-code {code!r}"
                )
            if not catalog.has(code):
                raise ProbeError(
                    f"{fixture_path}:{line_no}: unknown D-code {code!r}"
                )
        if len(codes) == 1:
            partial["expected_code"] = codes[0]
        else:
            partial["expected_codes"] = tuple(codes)

    elif kind_raw == "FILE-COUNT":
        m = re.match(r"^(D\d{4})\s*==\s*(\d+)\s*$", rest)
        if not m:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-FILE-COUNT requires"
                f" `<D-code> == <N>`; got {rest!r}"
            )
        code, count = m.group(1), int(m.group(2))
        if not catalog.has(code):
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-FILE-COUNT references unknown D-code"
                f" {code!r}"
            )
        partial["expected_code"] = code
        partial["expected_count"] = count

    else:
        return None

    return partial


_ATOMIC_ALIASES = {
    "int", "long", "double", "float", "string", "boolean", "bool",
    "date", "timestamp", "binary", "byte", "short", "decimal",
}


def _normalize_type_expr(expr: str) -> str:
    expr = expr.strip()
    # Array[T] -> array<T>; tolerate either spelling per spec.
    m = re.fullmatch(r"Array\[(.+)\]", expr)
    if m:
        return f"array<{_normalize_type_expr(m.group(1))}>"
    m = re.fullmatch(r"array<(.+)>", expr)
    if m:
        return f"array<{_normalize_type_expr(m.group(1))}>"
    # decimal(p, s) — pass through with whitespace normalized.
    m = re.fullmatch(r"decimal\(\s*(\d+)\s*,\s*(\d+)\s*\)", expr)
    if m:
        return f"decimal({m.group(1)}, {m.group(2)})"
    if expr in _ATOMIC_ALIASES:
        return expr
    raise ProbeError(f"unsupported type expression {expr!r} for PROBE-TYPE-IS")


# ---------------------------------------------------------------------------
# Target-line resolution (Q10).
# ---------------------------------------------------------------------------


def _statement_start_lines(source: str) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    starts: set[int] = set()
    # FunctionDef/AsyncFunctionDef/ClassDef lineno points at the `def`/`class`
    # keyword on Python 3.8+, not the first decorator (spec Q10).
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            line = getattr(node, "lineno", None)
            if isinstance(line, int):
                starts.add(line)
    return starts


def _resolve_target_line(
    source: str,
    comment_line: int,
    n_lines: int,
) -> Optional[int]:
    starts = _statement_start_lines(source)
    if not starts:
        return None
    for candidate in range(comment_line + 1, n_lines + 1):
        if candidate in starts:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Extraction.
# ---------------------------------------------------------------------------


def _path_to_posix(p: str) -> str:
    return Path(p).as_posix()


def extract(
    fixture_path: str | os.PathLike,
    *,
    catalog: Optional[Catalog] = None,
    repo_root: Optional[Path] = None,
) -> list[Probe]:
    if catalog is None:
        catalog = load_catalog()
    fixture_path = Path(fixture_path)
    source = fixture_path.read_text(encoding="utf-8")
    rel = _normalize_path(fixture_path, repo_root)
    return extract_from_source(source, rel, catalog)


def extract_from_source(
    source: str,
    fixture_path: str,
    catalog: Catalog,
) -> list[Probe]:
    """Pure-from-source extract. fixture_path is used verbatim for output."""
    lines = source.splitlines()
    n_lines = len(lines)
    # tokenize to skip comments inside strings (spec Q11).
    comment_lines: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comment_lines.append((tok.start[0], tok.string))
    except tokenize.TokenizeError:
        # Fall back: scan line-by-line. This still avoids in-string matches
        # for well-formed source.
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                comment_lines.append((i, stripped))

    partials: list[tuple[int, dict]] = []
    for line_no, comment in comment_lines:
        partial = _parse_marker(fixture_path, line_no, comment, catalog)
        if partial is None:
            continue
        partials.append((line_no, partial))

    probes: list[Probe] = []
    used_ids: set[str] = set()
    for line_no, partial in partials:
        kind = partial["kind"]
        if kind in ("FILE-CLEAN-OF", "FILE-COUNT"):
            target = None
        else:
            target = _resolve_target_line(source, line_no, n_lines)
            if target is None:
                raise ProbeError(
                    f"{fixture_path}:{line_no}: probe targets nonexistent statement"
                    f" after line {line_no}"
                )
        pid = partial["id"]
        if pid is None:
            pid = _synthesize_id(fixture_path, line_no, kind)
        if pid in used_ids:
            raise ProbeError(
                f"{fixture_path}:{line_no}: duplicate probe id {pid!r} in file"
            )
        used_ids.add(pid)
        probes.append(
            Probe(
                kind=kind,  # type: ignore[arg-type]
                fixture_path=fixture_path,
                comment_line=line_no,
                target_line=target,
                id=pid,
                rationale=partial.get("rationale"),
                expected_code=partial.get("expected_code"),
                expected_codes=partial.get("expected_codes"),
                expected_count=partial.get("expected_count"),
                span_text=partial.get("span_text"),
                match_regex=partial.get("match_regex"),
                match_flags=partial.get("match_flags"),
                type_expr=partial.get("type_expr"),
            )
        )
    return probes


def _synthesize_id(fixture_path: str, line_no: int, kind: str) -> str:
    stem = Path(fixture_path).stem
    return f"{stem}-L{line_no}-{kind.lower()}"


def _normalize_path(p: Path, repo_root: Optional[Path]) -> str:
    p = Path(p)
    if repo_root is not None:
        try:
            return p.resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except ValueError:
            return p.resolve().as_posix()
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


# ---------------------------------------------------------------------------
# Synthesizer (PROBE-TYPE-IS rewrite — spec "Golden format" option (a)).
# ---------------------------------------------------------------------------

# Numeric types synthesize a comparison against a string lit (D0082);
# non-numeric types synthesize arithmetic against an int lit (D0081).
_TYPE_SYNTH = {
    "int": "numeric",
    "long": "numeric",
    "short": "numeric",
    "byte": "numeric",
    "double": "numeric",
    "float": "numeric",
    "decimal": "numeric",
    "string": "non_numeric",
    "binary": "non_numeric",
    "date": "non_numeric",
    "timestamp": "non_numeric",
    "boolean": "non_numeric",
    "bool": "non_numeric",
}


@dataclass
class _SynthPlan:
    appended_lines: list[str]
    expectations: list[tuple[Probe, str, int]]


def _synthesize_type_probes(
    source: str,
    type_probes: list[Probe],
) -> _SynthPlan:
    # Per spec "Golden format" option (a): append one synthetic expression
    # per TYPE-IS probe and run pykrete in strict mode. The expression
    # fires D0081/D0082 iff the column's tracked type matches the
    # assertion. If the synth line yields no diagnostic, the probe is
    # reported as "synthesis inconclusive" (never silently passing).
    plan = _SynthPlan(appended_lines=[], expectations=[])
    if not type_probes:
        return plan
    base_line = len(source.splitlines())
    if not source.endswith("\n"):
        base_line += 1
    next_line = base_line + 1
    for probe in type_probes:
        if probe.target_line is None or probe.span_text is None or probe.type_expr is None:
            continue
        column = probe.span_text
        type_base = probe.type_expr.split("(", 1)[0].split("<", 1)[0]
        kind = _TYPE_SYNTH.get(type_base)
        if kind is None:
            plan.expectations.append((probe, "<unsynthesizable>", -1))
            continue
        ident = f'_pyk_probe_{probe.id.replace("-", "_")}'
        if kind == "numeric":
            expr = f'{ident} = (col({column!r}) > lit("x"))'
            target_code = "D0082"
        else:
            expr = f'{ident} = (col({column!r}) + lit(1))'
            target_code = "D0081"
        plan.appended_lines.append(expr)
        plan.expectations.append((probe, target_code, next_line))
        next_line += 1
    return plan


# ---------------------------------------------------------------------------
# Checker invocation.
# ---------------------------------------------------------------------------


def _pykrete_bin() -> str:
    return os.environ.get("PYKRETE_BIN", "pykrete")


def _run_checker(fixture_path: Path, *, strict: bool = False) -> dict:
    """Invoke pykrete check on fixture_path; return parsed JSON.

    When strict=True, write a sidecar pykrete.json in fixture_path.parent
    so D0081/D0082 (strict-only) can fire. We assume the caller has staged
    the fixture in an isolated directory.
    """
    cwd = fixture_path.parent
    if strict:
        (cwd / "pykrete.json").write_text(
            json.dumps({"typeCheckingMode": "strict"}),
            encoding="utf-8",
        )
    proc = subprocess.run(
        [_pykrete_bin(), "check", "--format", "json", fixture_path.name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    out = proc.stdout
    if not out.strip():
        raise ProbeError(
            f"pykrete returned empty stdout (stderr: {proc.stderr.strip()!r})"
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise ProbeError(
            f"pykrete --format json output was not valid JSON: {exc}\n{out!r}"
        ) from exc


def _stage_and_check(
    source: str,
    fixture_name: str,
    *,
    strict: bool,
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / fixture_name
        path.write_text(source, encoding="utf-8")
        return _run_checker(path, strict=strict)


# ---------------------------------------------------------------------------
# Verifier.
# ---------------------------------------------------------------------------


def verify(
    fixture_path: str | os.PathLike,
    *,
    catalog: Optional[Catalog] = None,
    repo_root: Optional[Path] = None,
) -> tuple[list[Probe], list[ProbeFailure]]:
    if catalog is None:
        catalog = load_catalog()
    fixture_path = Path(fixture_path)
    source = fixture_path.read_text(encoding="utf-8")
    probes = extract(fixture_path, catalog=catalog, repo_root=repo_root)
    if not probes:
        return probes, []

    # Split: non-TYPE-IS probes verify against the unmodified fixture (in
    # standard mode); TYPE-IS probes verify against a synthesized fixture
    # checked in strict mode.
    non_type_probes = [p for p in probes if p.kind != "TYPE-IS"]
    type_probes = [p for p in probes if p.kind == "TYPE-IS"]

    failures: list[ProbeFailure] = []
    if non_type_probes:
        actual = _stage_and_check(source, fixture_path.name, strict=False)
        failures.extend(
            verify_against_json(
                non_type_probes,
                actual,
                fixture_path.name,
                fixture_source=source,
            )
        )
    if type_probes:
        plan = _synthesize_type_probes(source, type_probes)
        if plan.appended_lines:
            synth_source = source
            if not synth_source.endswith("\n"):
                synth_source += "\n"
            synth_source += "\n".join(plan.appended_lines) + "\n"
            actual = _stage_and_check(synth_source, fixture_path.name, strict=True)
            failures.extend(
                _verify_type_probes(plan, actual, fixture_path.name)
            )
        else:
            # All TYPE-IS probes were unsynthesizable.
            for probe in type_probes:
                failures.append(
                    ProbeFailure(
                        probe=probe,
                        expected=f"type {probe.type_expr} on {probe.span_text!r}",
                        actual="probe-to-diagnostic synthesizer cannot encode this type",
                    )
                )
    return probes, failures


def verify_against_json(
    probes: list[Probe],
    actual: dict,
    fixture_name: str,
    *,
    fixture_source: Optional[str] = None,
) -> list[ProbeFailure]:
    """Stateless verifier — public API for unit tests (no checker invocation).

    When fixture_source is provided, `on "<text>"` matches by slicing the
    diagnostic's (line, column)..(endLine, endColumn) per spec Q12. When
    None, falls back to substring-against-message match.
    """
    diagnostics = actual.get("diagnostics") or []
    failures: list[ProbeFailure] = []

    if fixture_source is not None:
        for d in diagnostics:
            if Path(d.get("file", "")).name == fixture_name:
                d.setdefault("_pykSpanText", _slice_span(fixture_source, d))

    by_line: dict[int, list[dict]] = {}
    for d in diagnostics:
        if Path(d.get("file", "")).name != fixture_name:
            continue
        by_line.setdefault(d["line"], []).append(d)

    expects_by_line: dict[int, list[Probe]] = {}
    for probe in probes:
        if probe.kind == "EXPECTS" and probe.target_line is not None:
            expects_by_line.setdefault(probe.target_line, []).append(probe)

    matched_diag_ids: set[int] = set()

    for line, line_probes in expects_by_line.items():
        candidates = list(by_line.get(line, []))
        for probe in line_probes:
            match = _find_match(probe, candidates, matched_diag_ids)
            if match is None:
                failures.append(_expects_failure(probe, candidates))
            else:
                matched_diag_ids.add(id(match))

    for probe in probes:
        if probe.kind == "RESOLVES":
            line_diags = by_line.get(probe.target_line or -1, [])
            if line_diags:
                failures.append(
                    ProbeFailure(
                        probe=probe,
                        expected=f"no diagnostic on line {probe.target_line}",
                        actual=_diag_summary(line_diags),
                    )
                )
        elif probe.kind == "FILE-CLEAN-OF":
            codes = (
                probe.expected_codes
                if probe.expected_codes is not None
                else (probe.expected_code,)
            )
            hits = [d for d in diagnostics if d.get("code") in codes
                    and Path(d.get("file", "")).name == fixture_name]
            if hits:
                failures.append(
                    ProbeFailure(
                        probe=probe,
                        expected=f"no diagnostic with code in {list(codes)}",
                        actual=_diag_summary(hits),
                    )
                )
        elif probe.kind == "FILE-COUNT":
            code = probe.expected_code
            hits = [d for d in diagnostics if d.get("code") == code
                    and Path(d.get("file", "")).name == fixture_name]
            if len(hits) != (probe.expected_count or 0):
                lines = sorted({d["line"] for d in hits})
                failures.append(
                    ProbeFailure(
                        probe=probe,
                        expected=f"{probe.expected_count} occurrence(s) of {code}",
                        actual=f"{len(hits)} (lines {lines})",
                    )
                )
    return failures


def _find_match(
    probe: Probe,
    candidates: list[dict],
    consumed: set[int],
) -> Optional[dict]:
    for diag in candidates:
        if id(diag) in consumed:
            continue
        if diag.get("code") != probe.expected_code:
            continue
        if probe.span_text is not None:
            actual_span = diag.get("_pykSpanText")
            if actual_span is None:
                if probe.span_text not in (diag.get("message") or ""):
                    continue
            elif actual_span != probe.span_text:
                continue
        if probe.match_regex is not None:
            flags = 0
            for f in probe.match_flags or "":
                flags |= {"i": re.I, "m": re.M, "s": re.S, "x": re.X}[f]
            if not re.search(probe.match_regex, diag.get("message", ""), flags):
                continue
        return diag
    return None


def _slice_span(source: str, diag: dict) -> Optional[str]:
    """Slice fixture text by the diagnostic's (line, col)..(endLine, endCol).
    1-indexed UTF-8 character units (spec Q12)."""
    try:
        line = diag["line"]
        col = diag["column"]
        end_line = diag["endLine"]
        end_col = diag["endColumn"]
    except KeyError:
        return None
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return None
    if line == end_line:
        row = lines[line - 1]
        return row[col - 1 : end_col - 1]
    pieces = [lines[line - 1][col - 1 :]]
    for i in range(line, end_line - 1):
        pieces.append(lines[i])
    if end_line <= len(lines):
        pieces.append(lines[end_line - 1][: end_col - 1])
    return "\n".join(pieces)


def _expects_failure(probe: Probe, candidates: list[dict]) -> ProbeFailure:
    pieces = [f"code {probe.expected_code}"]
    if probe.span_text is not None:
        pieces.append(f"span text {probe.span_text!r}")
    if probe.match_regex is not None:
        pieces.append(f"message matching /{probe.match_regex}/{probe.match_flags or ''}")
    expected = " with ".join(pieces) + f" on line {probe.target_line}"
    if not candidates:
        actual = f"no diagnostic on line {probe.target_line}"
    else:
        actual = _diag_summary(candidates)
    return ProbeFailure(probe=probe, expected=expected, actual=actual)


def _diag_summary(diags: list[dict]) -> str:
    parts = []
    for d in diags:
        parts.append(
            f"{d.get('code')} [{d.get('ruleName')}] at"
            f" {d.get('line')}:{d.get('column')}-{d.get('endLine')}:{d.get('endColumn')}"
            f" {d.get('message', '')[:80]!r}"
        )
    return "; ".join(parts)


def _verify_type_probes(
    plan: _SynthPlan,
    actual: dict,
    fixture_name: str,
) -> list[ProbeFailure]:
    diagnostics = actual.get("diagnostics") or []
    failures: list[ProbeFailure] = []
    for probe, target_code, synth_line in plan.expectations:
        if target_code == "<unsynthesizable>":
            failures.append(
                ProbeFailure(
                    probe=probe,
                    expected=f"type {probe.type_expr} on {probe.span_text!r}",
                    actual="probe-to-diagnostic synthesizer cannot encode this type",
                )
            )
            continue
        hits = [
            d for d in diagnostics
            if d.get("code") == target_code and d.get("line") == synth_line
            and Path(d.get("file", "")).name == fixture_name
        ]
        if not hits:
            other = [d for d in diagnostics if d.get("line") == synth_line
                     and Path(d.get("file", "")).name == fixture_name]
            failures.append(
                ProbeFailure(
                    probe=probe,
                    expected=f"type {probe.type_expr} on {probe.span_text!r}"
                             f" (synthesized: expect {target_code} at line {synth_line})",
                    actual=_diag_summary(other) or "no diagnostic at synth line — synthesis inconclusive",
                )
            )
    return failures


# ---------------------------------------------------------------------------
# CLI / reporting.
# ---------------------------------------------------------------------------


def _format_failure(failure: ProbeFailure) -> str:
    p = failure.probe
    if p.kind in ("FILE-CLEAN-OF", "FILE-COUNT"):
        anchor = "file-scoped"
        target = ""
    else:
        anchor = f"comment line {p.comment_line}"
        target = f"  target line {p.target_line}"
    return (
        f"PROBE FAILURE: {p.fixture_path}\n"
        f"  {anchor}{target}  id={p.id}\n"
        f"    PROBE-{p.kind}"
        + (f" {p.expected_code}" if p.expected_code else "")
        + (f" {list(p.expected_codes)}" if p.expected_codes else "")
        + (f" {p.type_expr}" if p.type_expr else "")
        + (f' on "{p.span_text}"' if p.span_text else "")
        + "\n"
        f"    expected: {failure.expected}\n"
        f"    actual:   {failure.actual}"
    )


def _iter_fixtures(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix == ".pyk":
                yield p
        elif p.is_dir():
            yield from sorted(p.rglob("*.pyk"))


def _cmd_extract(argv: list[str]) -> int:
    if not argv:
        print("usage: probes.py extract <fixture.pyk>...", file=sys.stderr)
        return 2
    catalog = load_catalog()
    out_records: list[dict] = []
    for fixture in _iter_fixtures(argv):
        try:
            probes = extract(fixture, catalog=catalog)
        except ProbeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        for p in probes:
            out_records.append(dataclasses.asdict(p))
    json.dump(
        {"probesSchemaVersion": PROBES_SCHEMA_VERSION, "probes": out_records},
        sys.stdout,
        indent=2,
        default=list,
    )
    sys.stdout.write("\n")
    return 0


def _cmd_run(argv: list[str]) -> int:
    paths = argv or ["."]
    catalog = load_catalog()
    total_probes = 0
    total_failures = 0
    fixtures_with_probes = 0
    summary: list[dict] = []
    for fixture in _iter_fixtures(paths):
        try:
            probes, failures = verify(fixture, catalog=catalog)
        except ProbeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not probes:
            continue
        fixtures_with_probes += 1
        total_probes += len(probes)
        total_failures += len(failures)
        summary.append({
            "fixture": str(fixture),
            "probes": len(probes),
            "failures": len(failures),
        })
        for failure in failures:
            print(_format_failure(failure), file=sys.stderr)
    print(json.dumps({
        "probesSchemaVersion": PROBES_SCHEMA_VERSION,
        "catalogSourceCommit": catalog.source_commit,
        "fixturesWithProbes": fixtures_with_probes,
        "probesTotal": total_probes,
        "failuresTotal": total_failures,
        "perFixture": summary,
    }, indent=2))
    return 1 if total_failures else 0


def _cmd_verify(argv: list[str]) -> int:
    # Alias for `run` against explicit fixtures.
    if not argv:
        print("usage: probes.py verify <fixture.pyk>...", file=sys.stderr)
        return 2
    return _cmd_run(argv)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, *rest = argv
    if cmd == "extract":
        return _cmd_extract(rest)
    if cmd == "verify":
        return _cmd_verify(rest)
    if cmd == "run":
        return _cmd_run(rest)
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
