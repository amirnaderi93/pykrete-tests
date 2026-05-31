#!/usr/bin/env python3
"""Build a refreshed diagnostic_catalog.json from a pykrete-core source tree.

Parses the `DIAGNOSTIC_CATALOG` array literal out of
`crates/pykrete/src/diagnostics.rs`, merges per-code severity/stable
fields from the previous vendored catalog (preserving manual curation
where the code already existed), and writes a JSON file matching the
existing vendored shape.

Used by `.github/workflows/catalog-drift-watch.yml`. Standalone CLI so
fixture authors can run it locally to preview drift before the weekly
GHA opens a PR.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Matches each tuple entry inside `DIAGNOSTIC_CATALOG = &[ ... ]`:
#   ("D0001", "parseError"),
_ENTRY_RE = re.compile(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def parse_catalog(diagnostics_rs: str) -> list[tuple[str, str]]:
    decl_start = diagnostics_rs.find("DIAGNOSTIC_CATALOG")
    if decl_start == -1:
        raise SystemExit("could not find DIAGNOSTIC_CATALOG in diagnostics.rs")
    # The declaration is `... DIAGNOSTIC_CATALOG: &[(&str, &str)] = &[ ... ];`
    # Skip past the `= &[` opener and read until the matching `];`.
    body_start = diagnostics_rs.find("= &[", decl_start)
    if body_start == -1:
        raise SystemExit("malformed DIAGNOSTIC_CATALOG block — no '= &['")
    body_start += len("= &[")
    end = diagnostics_rs.find("];", body_start)
    if end == -1:
        raise SystemExit("malformed DIAGNOSTIC_CATALOG block — no closing '];'")
    block = diagnostics_rs[body_start:end]
    return _ENTRY_RE.findall(block)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--diagnostics", required=True, type=Path,
                   help="path to upstream crates/pykrete/src/diagnostics.rs")
    p.add_argument("--commit", required=True,
                   help="pykrete-core commit SHA (recorded as pykreteSourceCommit)")
    p.add_argument("--previous", required=True, type=Path,
                   help="path to the existing vendored diagnostic_catalog.json")
    p.add_argument("--out", required=True, type=Path,
                   help="where to write the refreshed catalog JSON")
    p.add_argument("--summary", required=True, type=Path,
                   help="where to write a human-readable drift summary")
    args = p.parse_args(argv)

    diagnostics_src = args.diagnostics.read_text(encoding="utf-8")
    entries = parse_catalog(diagnostics_src)
    if not entries:
        raise SystemExit("DIAGNOSTIC_CATALOG block parsed to zero entries")

    prev = json.loads(args.previous.read_text(encoding="utf-8"))
    prev_by_code = {e["code"]: e for e in prev.get("diagnostics", [])}

    new_entries = []
    added = []
    renamed = []
    for code, rule_name in entries:
        old = prev_by_code.get(code)
        if old is None:
            added.append((code, rule_name))
            new_entries.append({
                "code": code,
                "ruleName": rule_name,
                "severity": "error",
                "stable": False,
            })
        else:
            if old.get("ruleName") != rule_name:
                renamed.append((code, old.get("ruleName"), rule_name))
            new_entries.append({
                "code": code,
                "ruleName": rule_name,
                "severity": old.get("severity", "error"),
                "stable": old.get("stable", True),
            })

    upstream_codes = {c for c, _ in entries}
    removed = [c for c in prev_by_code if c not in upstream_codes]

    # Match the vendored catalog's wire format exactly so a no-drift run
    # produces a zero-line diff. Each diagnostic entry sits on a single
    # line; em-dashes etc. stay un-escaped.
    diag_lines = []
    for e in new_entries:
        diag_lines.append(
            "    " + json.dumps(
                {"code": e["code"], "ruleName": e["ruleName"],
                 "severity": e["severity"], "stable": e["stable"]},
                ensure_ascii=False,
            )
        )
    header = {
        "_comment": prev.get("_comment", ""),
        "_pykreteSourceCommit": args.commit,
        "catalogSchemaVersion": prev.get("catalogSchemaVersion", "1"),
        "pykreteSourceCommit": args.commit,
    }
    header_lines = []
    for k, v in header.items():
        header_lines.append(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},")
    out_text = (
        "{\n"
        + "\n".join(header_lines) + "\n"
        + "  \"diagnostics\": [\n"
        + ",\n".join(diag_lines) + "\n"
        + "  ]\n"
        + "}\n"
    )
    args.out.write_text(out_text, encoding="utf-8")

    lines = [f"pykreteSourceCommit: {args.commit}", ""]
    if added:
        lines.append(f"Added ({len(added)}):")
        for code, rn in added:
            lines.append(f"  + {code}  {rn}")
        lines.append("")
    if renamed:
        lines.append(f"Renamed ({len(renamed)}):")
        for code, old_rn, new_rn in renamed:
            lines.append(f"  ~ {code}  {old_rn} -> {new_rn}")
        lines.append("")
    if removed:
        lines.append(f"Removed ({len(removed)}):")
        for code in removed:
            lines.append(f"  - {code}")
        lines.append("")
    if not (added or renamed or removed):
        lines.append("No code-level drift; commit hash change only.")
    args.summary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(f"wrote {args.out} ({len(new_entries)} codes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
