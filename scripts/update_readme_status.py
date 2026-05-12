#!/usr/bin/env python3
"""Rewrite the README.md "Current Status" block from datapackage.json stats.

The block is delimited by HTML comment markers:

    <!-- begin:status -->
    ...
    <!-- end:status -->

The script reads stats directly from datapackage.json (the on-disk CI-gated
manifest) so that the README and the manifest are always derived from the same
source of truth.

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

# Verbatim static paragraph at the end of the "Current Status" block.
# This text never changes unless the licensing policy itself changes, so it
# is intentionally hard-coded here rather than derived from the manifest.
_STATIC_PARAGRAPH = (
    "The repository uses a compound licensing model: repository-authored metadata\n"
    "is dedicated to the public domain under CC0 1.0 (see [`LICENSE`](LICENSE)),\n"
    "while per-scan rights are recorded individually in each entry. See\n"
    "[`LICENSE.md`](LICENSE.md) for the full policy, including the CC BY-SA\n"
    "ShareAlike caveat and the rules for remix-friendly release bundles."
)


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
    size_mb = f"{stats['scan_byte_count'] / (1024 * 1024):.2f}"
    source_status = stats["source_status_breakdown"]
    candidate_count = source_status.get("candidate", 0)
    rejected_count = source_status.get("rejected", 0)

    # Build name → title map from the scan-scoped license listings in the manifest.
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

    return (
        f"## Current Status\n"
        f"\n"
        f"The corpus currently contains {record_count} ingested scans drawn from "
        f"{entry_source_count} verified sources,\n"
        f"totalling ~{size_mb} MB on disk. The source-level index also tracks "
        f"{candidate_count} candidate\n"
        f"leads still being researched and {rejected_count} source records kept "
        f"for provenance after\n"
        f"being rejected as out of scope.\n"
        f"\n"
        f"License breakdown across the {record_count} entries:\n"
        f"\n"
        f"{license_block}\n"
        f"\n"
        f"{_STATIC_PARAGRAPH}"
    )


def _replace_status_section(readme_text: str, new_section: str) -> str:
    if BEGIN_MARKER not in readme_text:
        raise SystemExit(f"README.md: missing '{BEGIN_MARKER}' marker")
    if END_MARKER not in readme_text:
        raise SystemExit(f"README.md: missing '{END_MARKER}' marker")
    before, rest = readme_text.split(BEGIN_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    return before + BEGIN_MARKER + "\n" + new_section + "\n" + END_MARKER + after


def update(
    datapackage_path: Path = DATAPACKAGE_PATH,
    readme_path: Path = README_PATH,
) -> None:
    datapackage = _load_datapackage(datapackage_path)
    section = build_readme_section(datapackage)
    readme_text = readme_path.read_text(encoding="utf-8")
    new_text = _replace_status_section(readme_text, section)
    readme_path.write_text(new_text, encoding="utf-8")


def check(
    datapackage_path: Path = DATAPACKAGE_PATH,
    readme_path: Path = README_PATH,
) -> list[Path]:
    datapackage = _load_datapackage(datapackage_path)
    section = build_readme_section(datapackage)
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    expected = _replace_status_section(readme_text, section)
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

    update(datapackage_path=args.datapackage, readme_path=args.readme)
    try:
        display = args.readme.relative_to(REPO_ROOT)
    except ValueError:
        display = args.readme
    print(f"wrote: {display}")


if __name__ == "__main__":
    main()
