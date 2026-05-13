#!/usr/bin/env python3
"""Rewrite the README.md "Current Status" block from datapackage.json stats.

The dynamic block is delimited by HTML comment markers:

    <!-- begin:status -->
    ...generated content (heading + numbers + license breakdown)...
    <!-- end:status -->

    Any static prose after <!-- end:status --> is left untouched.

The script reads stats directly from datapackage.json (the on-disk CI-gated
manifest) so that the README and the manifest share a single source of truth.

Use --check to verify the on-disk README matches what would be generated
without touching the tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATAPACKAGE_PATH = REPO_ROOT / "datapackage.json"
README_PATH = REPO_ROOT / "README.md"

BEGIN_MARKER = "<!-- begin:status -->"
END_MARKER = "<!-- end:status -->"


def _load_datapackage(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}") from exc


def build_readme_section(datapackage: dict[str, Any]) -> str:
    """Return the content that belongs between the status markers.

    Does not include a leading or trailing newline — the caller inserts those
    when splicing the text back into the surrounding README.
    """
    stats = datapackage["stats"]
    record_count = stats["record_count"]
    entry_source_count = stats["entry_source_count"]
    size_mib = f"{stats['scan_byte_count'] / (1024 * 1024):.2f}"
    source_status = stats["source_status_breakdown"]
    candidate_count = source_status.get("candidate", 0)
    rejected_count = source_status.get("rejected", 0)

    # Build name → title map from scan-scoped license listings in the manifest.
    license_title_map: dict[str, str] = {
        lic["name"]: lic["title"]
        for lic in datapackage.get("licenses", [])
        if lic.get("scope") == "scans"
    }

    # Sort by count descending, then by license ID ascending for stability.
    license_items = sorted(
        stats["license_breakdown"].items(),
        key=lambda item: (-item[1], item[0]),
    )
    license_lines: list[str] = []
    for license_id, count in license_items:
        title = license_title_map.get(license_id)
        if title:
            license_lines.append(f"- {count} `{license_id}` ({title})")
        else:
            license_lines.append(f"- {count} `{license_id}`")
    license_block = "\n".join(license_lines)

    paragraph = (
        f"The corpus currently contains {record_count} ingested scans drawn from "
        f"{entry_source_count} verified sources, totalling ~{size_mib} MiB on disk. "
        f"The source-level index also tracks {candidate_count} candidate leads "
        f"still being researched and {rejected_count} source records kept for "
        f"provenance after being rejected as out of scope."
    )

    return (
        f"## Current Status\n"
        f"\n"
        f"{paragraph}\n"
        f"\n"
        f"License breakdown across the {record_count} entries:\n"
        f"\n"
        f"{license_block}"
    )


def _replace_status_section(
    readme_text: str,
    new_section: str,
    readme_path: Path,
) -> str:
    if BEGIN_MARKER not in readme_text:
        raise SystemExit(f"{readme_path}: missing '{BEGIN_MARKER}' marker")
    if END_MARKER not in readme_text:
        raise SystemExit(f"{readme_path}: missing '{END_MARKER}' marker")
    before, rest = readme_text.split(BEGIN_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    return before + BEGIN_MARKER + "\n" + new_section + "\n" + END_MARKER + after


def update(
    datapackage_path: Path = DATAPACKAGE_PATH,
    readme_path: Path = README_PATH,
) -> bool:
    """Rewrite the status section. Returns True if the file was changed."""
    datapackage = _load_datapackage(datapackage_path)
    section = build_readme_section(datapackage)
    readme_text = readme_path.read_text(encoding="utf-8")
    new_text = _replace_status_section(readme_text, section, readme_path)
    if new_text == readme_text:
        return False
    readme_path.write_text(new_text, encoding="utf-8")
    return True


def check(
    datapackage_path: Path = DATAPACKAGE_PATH,
    readme_path: Path = README_PATH,
) -> list[Path]:
    if not readme_path.exists():
        raise SystemExit(f"{readme_path}: file does not exist")
    datapackage = _load_datapackage(datapackage_path)
    section = build_readme_section(datapackage)
    readme_text = readme_path.read_text(encoding="utf-8")
    expected = _replace_status_section(readme_text, section, readme_path)
    if readme_text != expected:
        return [readme_path]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rewrite README.md 'Current Status' block from datapackage.json."
    )
    parser.add_argument("--datapackage", type=Path, default=DATAPACKAGE_PATH)
    parser.add_argument("--readme", type=Path, default=README_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify the on-disk README status section matches what would be generated. "
            "Exit 1 if not."
        ),
    )
    args = parser.parse_args()

    if args.check:
        stale = check(datapackage_path=args.datapackage, readme_path=args.readme)
        if stale:
            for path in stale:
                try:
                    display = path.relative_to(REPO_ROOT)
                except ValueError:
                    display = path
                print(f"stale: {display}", file=sys.stderr)
            print(
                "Run `python3 scripts/update_readme_status.py` to regenerate.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print("ok: README.md status section is up to date")
        return

    changed = update(datapackage_path=args.datapackage, readme_path=args.readme)
    try:
        display = args.readme.relative_to(REPO_ROOT)
    except ValueError:
        display = args.readme
    if changed:
        print(f"wrote: {display}")
    else:
        print(f"ok: {display} already up to date")


if __name__ == "__main__":
    main()
