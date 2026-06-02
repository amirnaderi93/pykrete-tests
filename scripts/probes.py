#!/usr/bin/env python3
"""Schema-tracking probes for pykrete-tests (v1.1).

Spec: pykrete repo `docs/design/schema-tracking-probes.md` (commit 565183e).

Usage:
    python scripts/probes.py extract <fixture.pyk>...
    python scripts/probes.py run [<path>...]   # default scope; recursive
    python scripts/probes.py --version
    python scripts/probes.py --help

Env vars:
    PYKRETE_BIN     path to the pykrete binary (default: `pykrete` on PATH)
    PROBES_CATALOG  path to diagnostic_catalog.json (default: sibling of this script)
    PYKRETE_TIMEOUT seconds for the pykrete subprocess (default: 30)

Exit codes:
    0   all probes satisfied (or no probes found)
    1   at least one probe failed
    2   usage error / parse error / catalog drift / runtime error
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional, Union

# Single source of truth for the probes-layer schema version.
PROBES_SCHEMA_VERSION = "1"

# Runner own version (independent of probesSchemaVersion).
RUNNER_VERSION = "1.1.0"

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


class CheckerError(Exception):
    """Raised when the pykrete subprocess itself errors out (not a probe failure)."""


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

# Column-0 strict (I8): marker comments MUST start at column 0, no leading
# whitespace allowed. Indented `# PROBE-...` is treated as a normal comment.
_MARKER_HEAD = re.compile(r"^#\s*PROBE-([A-Z][A-Z\-]*)\b\s*:?\s*(.*?)\s*$")

# Detector mirrors the strictness; we don't want indented "looks-like" markers
# to either parse or surface as typo hints.
_MARKER_DETECT = re.compile(r"^#\s*PROBE-([A-Z][A-Z\-]*)\b\s*(:|\s|$)")


class _UnterminatedQuoteError(Exception):
    pass


def _tokenize_slots(text: str) -> list[tuple[str, str]]:
    """Tokenize the marker tail into (slot_name, value) pairs.

    Two-pass:
      1. Scan left-to-right, skipping over quoted spans and regex bodies so
         `--` / slot keywords *inside* them never trigger a slot. Collect
         the (start, end, kind, value, [flags]) of each slot.
      2. The head (positional payload) is everything before the first slot;
         the rationale extends from `-- ` to the next slot start or EOL —
         but the spec rationale "extends to EOL" is honored by parsing
         rationale LAST. Concretely: we ignore the rationale opener until
         every other slot has been extracted.

    Slot openers recognised (all at a space boundary, outside quotes/regex):
      - `id=<handle>`
      - `on "<text>"`
      - `match /<regex>/[flags]`
      - `-- <rationale>`   (always consumes to EOL)
    """
    n = len(text)
    found: list[tuple[int, int, str, str, str]] = []
    rationale_pos: Optional[tuple[int, int, str]] = None

    i = 0
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            closed = False
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    closed = True
                    break
                j += 1
            if not closed:
                raise _UnterminatedQuoteError(
                    f"unterminated quoted string starting at column {i}"
                )
            i = j
            continue
        if c == "/":
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == "/":
                    j += 1
                    while j < n and text[j] in "imsx":
                        j += 1
                    break
                j += 1
            i = j
            continue
        at_boundary = (i == 0) or text[i - 1].isspace()
        if at_boundary:
            rest = text[i:]
            m = re.match(r"id=([A-Za-z0-9_.\-]+)", rest)
            if m:
                found.append((i, i + m.end(), "id", m.group(1), ""))
                i += m.end()
                continue
            m = re.match(r'on\s+"((?:[^"\\]|\\.)*)"', rest)
            if m:
                found.append((i, i + m.end(), "on", m.group(1), ""))
                i += m.end()
                continue
            m = re.match(r"match\s+/((?:[^/\\]|\\.)*)/([imsx]*)", rest)
            if m:
                found.append((i, i + m.end(), "match", m.group(1), m.group(2) or ""))
                i += m.end()
                continue
            m = re.match(r"--\s+", rest)
            if m and rationale_pos is None:
                rationale_pos = (i, i + m.end(), "rationale")
                i += m.end()
                continue
        i += 1

    # Compute head: everything before the first slot / rationale.
    boundary_positions = [s for s, _, _, _, _ in found]
    if rationale_pos is not None:
        boundary_positions.append(rationale_pos[0])
    first_slot = min(boundary_positions) if boundary_positions else n
    head = text[:first_slot].strip()

    # Rationale value: text from rationale_pos end to the start of the next
    # slot AFTER it (if any), else EOL.
    rationale_value: Optional[str] = None
    if rationale_pos is not None:
        r_start, r_payload_start, _ = rationale_pos
        later_slots = [s for s, _, _, _, _ in found if s > r_start]
        r_end = min(later_slots) if later_slots else n
        rationale_value = text[r_payload_start:r_end].strip()

    tokens: list[tuple[str, str]] = []
    if head:
        tokens.append(("", head))
    for _, _, kind, value, flags in found:
        if kind == "match":
            tokens.append(("match", value))
            if flags:
                tokens.append(("match_flags", flags))
        else:
            tokens.append((kind, value))
    if rationale_value is not None:
        tokens.append(("rationale", rationale_value))
    return tokens


def _unescape_on_value(raw: str) -> str:
    """Unescape `\\"` inside `on "..."`. Keep UTF-8 bytes intact (B7).

    The previous impl round-tripped through `unicode_escape`, which corrupts
    non-ASCII (e.g. `café` -> `cafÃ©`). We only need to handle `\\"` and `\\\\`.
    """
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in ('"', "\\"):
                out.append(nxt)
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


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

    try:
        slots = _tokenize_slots(body)
    except _UnterminatedQuoteError as exc:
        raise ProbeError(
            f"{fixture_path}:{line_no}: {exc} in PROBE-{kind_raw} marker"
        ) from exc
    head_value = ""
    probe_id: Optional[str] = None
    span: Optional[str] = None
    match_regex: Optional[str] = None
    match_flags: Optional[str] = None
    rationale: Optional[str] = None
    seen: set[str] = set()
    for name, value in slots:
        if name == "":
            head_value = value
            continue
        if name in seen and name != "match_flags":
            raise ProbeError(
                f"{fixture_path}:{line_no}: duplicate slot {name!r}"
            )
        seen.add(name)
        if name == "id":
            probe_id = value
        elif name == "on":
            span = _unescape_on_value(value)
        elif name == "match":
            match_regex = value
        elif name == "match_flags":
            match_flags = value
        elif name == "rationale":
            rationale = value

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
    rest = head_value

    if kind_raw == "EXPECTS":
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
        type_base = type_expr.split("(", 1)[0].split("<", 1)[0]
        if type_base in _NUMERIC_FAMILY:
            raise ProbeError(
                f"{fixture_path}:{line_no}: PROBE-TYPE-IS with numeric-subtype"
                f" assertion ({type_base!r}) is not supported in v1.1 —"
                f" within-family subtype distinguishability is deferred to"
                f" v1.2 (requires pykrete-core D-codes for"
                f" numeric-subtype-mismatch). Drop the probe or use a"
                f" cross-family assertion (e.g., int vs string)."
            )
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

# v1.1 carve-out (TM directive, round 3): the synthesizer fires
# family-level D0080-D0082, which cannot tell int from long or double from
# float. A green for a within-family TYPE-IS probe would be vacuous — and
# vacuous greens violate the v1.1 trust claim. Reject these at parse time
# with a named error so fixture authors learn at write time, not at run.
_NUMERIC_FAMILY = {
    "int", "long", "short", "byte", "double", "float", "decimal",
}


def _normalize_type_expr(expr: str) -> str:
    expr = expr.strip()
    m = re.fullmatch(r"Array\[(.+)\]", expr)
    if m:
        return f"array<{_normalize_type_expr(m.group(1))}>"
    m = re.fullmatch(r"array<(.+)>", expr)
    if m:
        return f"array<{_normalize_type_expr(m.group(1))}>"
    m = re.fullmatch(r"decimal\(\s*(\d+)\s*,\s*(\d+)\s*\)", expr)
    if m:
        return f"decimal({m.group(1)}, {m.group(2)})"
    if expr in _ATOMIC_ALIASES:
        return expr
    raise ProbeError(f"unsupported type expression {expr!r} for PROBE-TYPE-IS")


# ---------------------------------------------------------------------------
# Target-line + scope resolution (Q10).
# ---------------------------------------------------------------------------


def _statement_start_lines(source: str) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    starts: set[int] = set()
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


def _enclosing_function(
    source: str, target_line: int
) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    """Return the innermost FunctionDef/AsyncFunctionDef enclosing target_line.

    Returns None if target_line is at module scope. Used by the TYPE-IS
    synthesizer to inject inside the function rather than appending at
    module scope where `df` is undefined (B2).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    enclosing: Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]] = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            if start <= target_line <= end:
                if enclosing is None or node.lineno > enclosing.lineno:
                    enclosing = node
    return enclosing


def _is_dataframe_schema_annotation(annotation: Optional[ast.expr]) -> bool:
    """Return True iff the annotation is a bare `DataFrame[Schema]` subscript.

    Matches `DataFrame[X]` and `pykrete.types.DataFrame[X]` (any
    attribute chain ending in `DataFrame`). Rejects every wrapped or
    non-literal shape per the v1.2 first-wins annotation-shape policy:
    generic wrappers (`list[...]`, `Optional[...]`, `Union[..., None]`,
    PEP 604 `... | None`), string forward refs, type aliases (not
    inspected; the annotation must literally be a Subscript), and bare
    `DataFrame` with no schema parameter.
    """
    if annotation is None:
        return False
    if not isinstance(annotation, ast.Subscript):
        return False
    value = annotation.value
    if isinstance(value, ast.Name):
        return value.id == "DataFrame"
    if isinstance(value, ast.Attribute):
        return value.attr == "DataFrame"
    return False


def _first_dataframe_param(
    func: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> Optional[str]:
    """Return the identifier of the first `DataFrame[Schema]` parameter (v1.2).

    Walks `func.args` in declaration order — positional-only, then
    positional-or-keyword, then keyword-only — and returns the first
    parameter whose annotation is a bare `DataFrame[Schema]` subscript
    per `_is_dataframe_schema_annotation`. Variadics (`*args`,
    `**kwargs`) are never named scalar bindings and are skipped.

    Returns None if no parameter matches. The synthesizer treats None
    as the unsynthesizable fallthrough (no silent pass).

    Locks the v1.2 first-wins resolution policy; any change is a
    `probesSchemaVersion` semver-minor amendment.
    """
    walk_order: list[ast.arg] = []
    walk_order.extend(func.args.posonlyargs)
    walk_order.extend(func.args.args)
    walk_order.extend(func.args.kwonlyargs)
    for arg in walk_order:
        if _is_dataframe_schema_annotation(arg.annotation):
            return arg.arg
    return None


# ---------------------------------------------------------------------------
# Extraction.
# ---------------------------------------------------------------------------


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
    # Tokenize-only path (I10): if tokenization fails the source is broken
    # Python and we hard-fail; the fallback regex scan re-introduced
    # in-string false-match hazards (probes inside docstrings being parsed).
    comment_lines: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                # spec: column-0 markers only. tok.start[1] is the column
                # of the `#` character; reject anything indented.
                if tok.start[1] == 0:
                    comment_lines.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise ProbeError(
            f"{fixture_path}: source failed to tokenize ({exc});"
            f" cannot extract probes from broken Python"
        ) from exc

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
    """Reduce path to repo-relative POSIX (spec Q14, B5).

    Both probe.fixture_path and the diagnostic `file` field must reduce
    via the same rule. Mismatch is a hard error in the verifier, not
    silent zero-match.
    """
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

# Non-numeric atomic types map to D0081 (nonNumericArithmetic) by adding an
# int literal — if the tracked type IS numeric, D0081 will not fire and the
# probe correctly fails. Numeric subtypes are rejected at parse time (B1,
# round-3 directive); their entries were removed because the synthesizer
# could not distinguish int from long today, which would make a within-
# family green vacuous. v1.2 will re-enable numeric subtypes once
# pykrete-core ships numeric-subtype-mismatch D-codes.
_TYPE_TARGET: dict[str, str] = {
    "string": "D0081",
    "binary": "D0081",
    "date": "D0081",
    "timestamp": "D0081",
    "boolean": "D0081",
    "bool": "D0081",
}


@dataclass
class _SynthPlan:
    appended_source: str  # the full modified source
    expectations: list[tuple[Probe, str, int]] = field(default_factory=list)


def _is_valid_python_ident(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s))


def _safe_ident(probe_id: str, fallback_index: int) -> str:
    """Build a valid Python identifier from a probe id (B6).

    Probe ids allow `.` and `-`, neither valid in Python identifiers. We
    replace each with `_`. If the result is still invalid (empty / starts
    with a digit / collides with a keyword), fall back to a positional name.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", probe_id)
    if cleaned and not cleaned[0].isdigit() and _is_valid_python_ident(cleaned):
        return f"_pyk_probe_{cleaned}"
    return f"_pyk_probe_{fallback_index}"


def _column_accessor(span_text: str) -> str:
    """Emit a Spark column-access expression for a (possibly dotted) span (B9).

    Per spec line 173, dotted accessors target struct fields. We render
    `addr.city` as `col("addr").getField("city")` so the checker sees a real
    struct-field reference, not a literal column lookup of `"addr.city"`.
    Single-segment names render as `col("name")`.
    """
    parts = span_text.split(".")
    if len(parts) == 1:
        return f"col({parts[0]!r})"
    expr = f"col({parts[0]!r})"
    for piece in parts[1:]:
        expr += f".getField({piece!r})"
    return expr


def _synthesize_type_probes(
    source: str,
    type_probes: list[Probe],
) -> _SynthPlan:
    """Per spec (a): inject one synthetic expression per TYPE-IS probe.

    Critically (B2): the synthetic expression must live in the same scope
    as the target-line binding. For function-local targets we splice the
    expression in immediately after the target line, indented to match;
    for module-scope targets we append.
    """
    if not type_probes:
        return _SynthPlan(appended_source=source, expectations=[])

    lines = source.splitlines()
    expectations: list[tuple[Probe, str, int]] = []

    inserts: list[tuple[int, int, Probe, str, str]] = []
    # (insert_after_orig_line, original_probe_index, probe, code_line, target_code)
    for idx, probe in enumerate(type_probes):
        if probe.target_line is None or probe.span_text is None or probe.type_expr is None:
            continue
        type_base = probe.type_expr.split("(", 1)[0].split("<", 1)[0]
        target_code = _TYPE_TARGET.get(type_base)
        if target_code is None:
            expectations.append((probe, "<unsynthesizable>", -1))
            continue
        enclosing = _enclosing_function(source, probe.target_line)
        if enclosing is None:
            # v1.2: module-scope probe has no FunctionDef.args to inspect.
            # No silent pass — record as unsynthesizable.
            expectations.append((probe, "<unsynthesizable>", -1))
            continue
        df_ident = _first_dataframe_param(enclosing)
        if df_ident is None:
            # v1.2: no DataFrame[Schema] param in scope — synth cannot bind
            # col(...) to a typed receiver, so the probe is unsynthesizable.
            expectations.append((probe, "<unsynthesizable>", -1))
            continue
        ident = _safe_ident(probe.id, idx)
        accessor = _column_accessor(probe.span_text)
        # v1.2 scope-binding fix: wrap synth in `{df}.select(...)` so the
        # accessor binds to df's tracked schema; v1.1's bare-statement form
        # left col("x") with no typed receiver, silencing D-codes.
        expr = f'{ident} = {df_ident}.select({accessor} + lit(1))'
        target_idx = probe.target_line - 1
        if target_idx < len(lines):
            indent_match = re.match(r"\s*", lines[target_idx])
            indent = indent_match.group(0) if indent_match else "    "
        else:
            indent = "    "
        insert_after = probe.target_line
        code_line = indent + expr
        inserts.append((insert_after, idx, probe, code_line, target_code))

    # Sort by insert_after ascending (top-down). Insertions at the same
    # `insert_after` preserve probe order.
    inserts.sort(key=lambda x: (x[0], x[1]))
    new_lines = list(lines)
    cumulative_offset = 0
    last_insert_after = None
    same_line_count = 0
    for insert_after, _probe_idx, probe, code_line, target_code in inserts:
        if insert_after == last_insert_after:
            same_line_count += 1
        else:
            same_line_count = 0
            last_insert_after = insert_after
        insert_idx = insert_after + cumulative_offset
        new_lines.insert(insert_idx, code_line)
        final_line = insert_idx + 1
        expectations.append((probe, target_code, final_line))
        cumulative_offset += 1

    synth_source = "\n".join(new_lines)
    if source.endswith("\n"):
        synth_source += "\n"
    return _SynthPlan(appended_source=synth_source, expectations=expectations)


# ---------------------------------------------------------------------------
# Checker invocation.
# ---------------------------------------------------------------------------


_DEFAULT_TIMEOUT_SEC = 30


def _pykrete_bin() -> str:
    return os.environ.get("PYKRETE_BIN", "pykrete")


def _pykrete_timeout() -> int:
    raw = os.environ.get("PYKRETE_TIMEOUT")
    if not raw:
        return _DEFAULT_TIMEOUT_SEC
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_TIMEOUT_SEC


def _run_checker(fixture_path: Path, *, strict: bool = False) -> dict:
    cwd = fixture_path.parent
    if strict:
        (cwd / "pykrete.json").write_text(
            json.dumps({"typeCheckingMode": "strict"}),
            encoding="utf-8",
        )
    binary = _pykrete_bin()
    if not (Path(binary).is_file() or shutil.which(binary)):
        raise CheckerError(
            f"PYKRETE_BIN={binary!r} not found; set PYKRETE_BIN to a built"
            f" pykrete binary or place `pykrete` on PATH"
        )
    cmd = [binary, "check", "--format", "json", fixture_path.name]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_pykrete_timeout(),
        )
    except subprocess.TimeoutExpired as exc:
        raise CheckerError(
            f"pykrete subprocess timed out after {_pykrete_timeout()}s"
            f" (cmd={shlex.join(cmd)}); raise PYKRETE_TIMEOUT to extend"
        ) from exc
    except FileNotFoundError as exc:
        raise CheckerError(
            f"PYKRETE_BIN={binary!r} not found; set PYKRETE_BIN to a built"
            f" pykrete binary or place `pykrete` on PATH"
        ) from exc

    out = proc.stdout
    # Distinguish "crashed" from "found diagnostics" (I9). pykrete's normal
    # exit on diagnostics is 0; a non-empty stdout that parses as JSON is
    # treated as a successful check regardless of exit code. An empty stdout
    # with non-zero exit is a crash.
    if not out.strip():
        stderr = proc.stderr.strip()
        raise CheckerError(
            f"pykrete returned empty stdout (exit={proc.returncode}, stderr={stderr!r});"
            f" treat as crash, not a probe failure"
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise CheckerError(
            f"pykrete --format json output was not valid JSON: {exc}\n{out!r}"
        ) from exc


def _stage_and_check(
    source: str,
    fixture_path: Path,
    *,
    strict: bool,
    fixture_relpath: Optional[str] = None,
) -> dict:
    """Stage the entire directory of `fixture_path` to a tempdir then run check.

    Resolves B3: probes inside a fixture that `from schema import Sales`
    require the sibling files to be present for import resolution.

    When `fixture_relpath` is provided, rewrite each diagnostic's `file`
    field that points at the staged copy to the supplied relpath. This
    makes the verifier's strict repo-relative match (B5) actually fire
    in production, not just in unit tests.
    """
    src_dir = fixture_path.parent
    with tempfile.TemporaryDirectory() as tmp:
        dst_dir = Path(tmp) / src_dir.name
        shutil.copytree(src_dir, dst_dir)
        dst_path = dst_dir / fixture_path.name
        dst_path.write_text(source, encoding="utf-8")
        result = _run_checker(dst_path, strict=strict)
        if fixture_relpath is not None:
            staged_basename = fixture_path.name
            for d in result.get("diagnostics") or []:
                diag_file = d.get("file", "")
                if Path(diag_file).name == staged_basename:
                    d["file"] = fixture_relpath
        return result


# ---------------------------------------------------------------------------
# Verifier.
# ---------------------------------------------------------------------------


def verify(
    fixture_path: str | os.PathLike,
    *,
    catalog: Optional[Catalog] = None,
    repo_root: Optional[Path] = None,
    fixture_relpath: Optional[str] = None,
) -> tuple[list[Probe], list[ProbeFailure]]:
    if catalog is None:
        catalog = load_catalog()
    fixture_path = Path(fixture_path)
    source = fixture_path.read_text(encoding="utf-8")
    probes = extract(fixture_path, catalog=catalog, repo_root=repo_root)
    if not probes:
        return probes, []

    if fixture_relpath is None:
        fixture_relpath = _normalize_path(fixture_path, repo_root)

    non_type_probes = [p for p in probes if p.kind != "TYPE-IS"]
    type_probes = [p for p in probes if p.kind == "TYPE-IS"]

    failures: list[ProbeFailure] = []
    if non_type_probes:
        actual = _stage_and_check(
            source, fixture_path, strict=False, fixture_relpath=fixture_relpath,
        )
        failures.extend(
            verify_against_json(
                non_type_probes,
                actual,
                fixture_path.name,
                fixture_source=source,
                fixture_relpath=fixture_relpath,
            )
        )
    if type_probes:
        plan = _synthesize_type_probes(source, type_probes)
        synth_count = sum(1 for _, code, _ in plan.expectations if code != "<unsynthesizable>")
        if synth_count > 0:
            actual = _stage_and_check(
                plan.appended_source, fixture_path, strict=True,
                fixture_relpath=fixture_relpath,
            )
            failures.extend(_verify_type_probes(plan, actual, fixture_relpath))
        else:
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
    fixture_relpath: Optional[str] = None,
) -> list[ProbeFailure]:
    """Stateless verifier — public API for unit tests (no checker invocation).

    `fixture_source` MUST be non-None when any probe uses `on "..."` (I6).
    Substring-of-message fallback was silently broadening span semantics.

    `fixture_relpath` enables repo-relative path matching (B5). When set,
    diagnostics must match by relative path (resolved as POSIX); when None,
    we fall back to basename matching (with a deprecation note — callers
    should always pass a relpath in v1.1).
    """
    diagnostics = actual.get("diagnostics") or []
    failures: list[ProbeFailure] = []

    def _matches_fixture(diag: dict) -> bool:
        diag_file = diag.get("file", "")
        if fixture_relpath is not None:
            # Strict repo-relative match (B5). Diagnostic file is usually an
            # absolute path; we accept either an exact equal or a suffix
            # match on `/<relpath>` so the absolute-path form resolves the
            # same as the relpath form. Basename-only is rejected.
            return diag_file == fixture_relpath or diag_file.endswith("/" + fixture_relpath)
        return Path(diag_file).name == fixture_name

    if fixture_source is not None:
        for d in diagnostics:
            if _matches_fixture(d):
                d.setdefault("_pykSpanText", _slice_span(fixture_source, d))

    by_line: dict[int, list[dict]] = {}
    for d in diagnostics:
        if not _matches_fixture(d):
            continue
        by_line.setdefault(d["line"], []).append(d)

    expects_by_line: dict[int, list[Probe]] = {}
    for probe in probes:
        if probe.kind == "EXPECTS" and probe.target_line is not None:
            expects_by_line.setdefault(probe.target_line, []).append(probe)

    # Bipartite matching for stacked EXPECTS (B4 + I1). For each line:
    # - probes and candidates form a bipartite graph; edges connect a probe
    #   to a candidate iff that candidate satisfies the probe's filters
    #   (code, span, regex).
    # - find a maximum matching (greedy with augmenting paths — Hungarian-
    #   light, fine for N,M < 10).
    # - unmatched probes -> failure; unmatched candidates on a marker line
    #   that are NOT claimed by ANY probe and that share the same line are
    #   surfaced as "unexpected extra diagnostic" failures (I1).
    matched_candidate_for_probe: dict[int, dict] = {}
    matched_probes_on_line: dict[int, set[int]] = {}
    for line, line_probes in expects_by_line.items():
        candidates = list(by_line.get(line, []))
        if fixture_source is not None:
            for d in candidates:
                d.setdefault("_pykSpanText", _slice_span(fixture_source, d))
        match = _bipartite_match(line_probes, candidates)
        for probe in line_probes:
            cand = match.get(id(probe))
            if cand is None:
                failures.append(_expects_failure(probe, candidates))
            else:
                matched_candidate_for_probe[id(probe)] = cand
                matched_probes_on_line.setdefault(line, set()).add(id(cand))

    # I1: any candidate on a probe-claimed line that wasn't matched by any
    # marker is an unclaimed extra diagnostic. Probes implicitly assert
    # "these are the diagnostics on this line"; silently-extra would mean
    # a checker regression slips by.
    for line, line_probes in expects_by_line.items():
        matched = matched_probes_on_line.get(line, set())
        for diag in by_line.get(line, []):
            if id(diag) not in matched:
                synthetic_probe = Probe(
                    kind="EXPECTS",
                    fixture_path=line_probes[0].fixture_path,
                    comment_line=line_probes[0].comment_line,
                    target_line=line,
                    id=f"_unclaimed_L{line}",
                )
                failures.append(
                    ProbeFailure(
                        probe=synthetic_probe,
                        expected=f"no unclaimed diagnostics on line {line}"
                                 f" (all must be matched by PROBE-EXPECTS markers)",
                        actual=f"unclaimed: {_diag_summary([diag])}",
                    )
                )

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
                    and _matches_fixture(d)]
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
                    and _matches_fixture(d)]
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


def _candidate_satisfies(probe: Probe, diag: dict) -> bool:
    """Edge-existence check for the bipartite match (B4)."""
    if diag.get("code") != probe.expected_code:
        return False
    if probe.span_text is not None:
        actual_span = diag.get("_pykSpanText")
        if actual_span is None:
            # Spec requires fixture_source for `on`. If unavailable, the
            # caller has a bug; reject the match rather than substring-
            # fallback (I6).
            return False
        if actual_span != probe.span_text:
            return False
    if probe.match_regex is not None:
        flags = 0
        for f in probe.match_flags or "":
            flags |= {"i": re.I, "m": re.M, "s": re.S, "x": re.X}[f]
        if not re.search(probe.match_regex, diag.get("message", ""), flags):
            return False
    return True


def _bipartite_match(probes_list: list[Probe], diags: list[dict]) -> dict[int, dict]:
    """Maximum bipartite matching probe -> diagnostic.

    Returns a dict {id(probe): diag} for matched pairs. Unmatched probes
    are absent from the dict. Uses Kuhn's algorithm (augmenting paths).
    """
    eligible: dict[int, list[int]] = {
        id(p): [i for i, d in enumerate(diags) if _candidate_satisfies(p, d)]
        for p in probes_list
    }
    diag_owner: dict[int, int] = {}  # diag_index -> id(probe)

    def try_augment(p_id: int, visited: set[int]) -> bool:
        for di in eligible[p_id]:
            if di in visited:
                continue
            visited.add(di)
            if di not in diag_owner or try_augment(diag_owner[di], visited):
                diag_owner[di] = p_id
                return True
        return False

    for probe in probes_list:
        try_augment(id(probe), set())

    out: dict[int, dict] = {}
    for di, p_id in diag_owner.items():
        out[p_id] = diags[di]
    return out


def _slice_span(source: str, diag: dict) -> Optional[str]:
    """Slice fixture text by 1-indexed UTF-8 character units (spec Q12)."""
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
    fixture_relpath: str,
) -> list[ProbeFailure]:
    diagnostics = actual.get("diagnostics") or []
    failures: list[ProbeFailure] = []

    def _matches(d: dict) -> bool:
        diag_file = d.get("file", "")
        return diag_file == fixture_relpath or diag_file.endswith("/" + fixture_relpath)

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
            if d.get("code") == target_code and d.get("line") == synth_line and _matches(d)
        ]
        if not hits:
            other = [d for d in diagnostics if d.get("line") == synth_line and _matches(d)]
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


def _cmd_extract(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    out_records: list[dict] = []
    for fixture in _iter_fixtures(args.paths):
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


def _donor_root(fixture: Path) -> str:
    """Best-effort donor identification: the second path segment.

    A fixture under `cross-codebase/<donor>/...` is keyed by `<donor>`;
    anything else falls back to the immediate parent dir name. Per-donor
    ID uniqueness (Q1 / I7) is enforced at run time across fixtures
    that share the same donor key.
    """
    parts = fixture.parts
    if "cross-codebase" in parts:
        i = parts.index("cross-codebase")
        if i + 1 < len(parts):
            return parts[i + 1]
    return fixture.parent.name


def _fixture_relpath(fixture: Path) -> str:
    """Path of `fixture` relative to the cross-codebase root (B5).

    The repo-relative form lets the verifier reject diagnostics that
    come from a different donor with the same basename. For fixtures
    under `cross-codebase/<donor>/...`, anchor at `<donor>/...`. For
    fixtures elsewhere, fall back to a CWD-relative or absolute POSIX
    path; callers can override by passing a custom relpath.
    """
    parts = fixture.parts
    if "cross-codebase" in parts:
        i = parts.index("cross-codebase")
        return Path(*parts[i + 1:]).as_posix()
    try:
        return fixture.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return fixture.resolve().as_posix()


def _cmd_run(args: argparse.Namespace) -> int:
    paths = args.paths or ["."]
    catalog = load_catalog()
    total_probes = 0
    total_failures = 0
    fixtures_with_probes = 0
    failed_probe_ids: list[str] = []
    summary: list[dict] = []
    ids_per_donor: dict[str, dict[str, str]] = {}
    for fixture in _iter_fixtures(paths):
        relpath = _fixture_relpath(fixture)
        try:
            probes_list, failures = verify(
                fixture, catalog=catalog, fixture_relpath=relpath,
            )
        except ProbeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except CheckerError as exc:
            print(f"CHECKER ERROR ({fixture}): {exc}", file=sys.stderr)
            return 2
        if not probes_list:
            continue
        donor = _donor_root(fixture)
        donor_ids = ids_per_donor.setdefault(donor, {})
        for p in probes_list:
            prior = donor_ids.get(p.id)
            if prior is not None and prior != str(fixture):
                print(
                    f"duplicate probe id {p.id!r} within donor {donor!r}:"
                    f" {prior} and {fixture}",
                    file=sys.stderr,
                )
                return 2
            donor_ids[p.id] = str(fixture)
        fixtures_with_probes += 1
        total_probes += len(probes_list)
        total_failures += len(failures)
        for failure in failures:
            failed_probe_ids.append(f"{fixture}:{failure.probe.id}")
        summary.append({
            "fixture": str(fixture),
            "probes": len(probes_list),
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
        "failedProbeIds": failed_probe_ids,
        "perFixture": summary,
    }, indent=2))
    return 1 if total_failures else 0


def _build_parser() -> argparse.ArgumentParser:
    catalog_commit = ""
    try:
        catalog = load_catalog()
        catalog_commit = catalog.source_commit
    except ProbeError:
        pass
    version_str = (
        f"probes.py {RUNNER_VERSION}"
        f" (probesSchemaVersion={PROBES_SCHEMA_VERSION},"
        f" pykreteSourceCommit={catalog_commit or 'unknown'})"
    )
    parser = argparse.ArgumentParser(
        prog="probes.py",
        description="Schema-tracking probe extractor + verifier for pykrete-tests v1.1.",
    )
    parser.add_argument("--version", action="version", version=version_str)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser(
        "extract", help="Parse markers and print probe records as JSON."
    )
    p_extract.add_argument("paths", nargs="+", help="One or more .pyk files or directories.")
    p_extract.set_defaults(func=_cmd_extract)

    p_run = sub.add_parser(
        "run", help="Verify every .pyk under the given paths (defaults to CWD)."
    )
    p_run.add_argument("paths", nargs="*", help="Directories or files; default: current dir.")
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
