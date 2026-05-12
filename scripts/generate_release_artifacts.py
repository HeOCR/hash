#!/usr/bin/env python3
"""Generate deterministic release artefacts from data/index/*.jsonl.

Emits three files at the repo root:

  - NOTICE.md         human-readable attribution roll-up.
  - CITATION.cff      Citation File Format 1.2.0.
  - datapackage.json  Frictionless Data Package manifest.

The script is fully deterministic: same indexes in, byte-identical files out.
No datetime.now(), no random ordering, no UUIDs. `released_at` is derived from
the most recent `provenance.acquired_at` in entries.jsonl so the timestamp
reflects the corpus state, not the time the script happened to run.

Use `--check` to verify the on-disk artefacts match what would be generated
without touching the tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised when deps are absent.
    raise SystemExit(
        "Missing dependency: PyYAML. Install development dependencies with "
        "`python3 -m pip install -r requirements-dev.txt`."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES_PATH = REPO_ROOT / "data" / "index" / "entries.jsonl"
RECIPE_PATH = REPO_ROOT / "scripts" / "release_recipe.json"
NOTICE_PATH = REPO_ROOT / "NOTICE.md"
CITATION_PATH = REPO_ROOT / "CITATION.cff"
DATAPACKAGE_PATH = REPO_ROOT / "datapackage.json"

# Licenses whose terms require attribution. Drives both NOTICE.md inclusion and
# the consistency check below. Keep in sync with the schema's accepted licenses
# in AGENTS.md.
ATTRIBUTION_REQUIRING_LICENSES: frozenset[str] = frozenset({
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def _load_recipe(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}") from exc


def _derive_released_at(entries: list[dict[str, Any]]) -> str:
    acquired = [
        entry["provenance"]["acquired_at"]
        for entry in entries
        if entry.get("provenance") and entry["provenance"].get("acquired_at")
    ]
    if not acquired:
        raise SystemExit("no provenance.acquired_at values found in entries.jsonl")
    return max(acquired)


def _license_breakdown(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(entry["rights"]["license_expression"] for entry in entries)
    return {key: counts[key] for key in sorted(counts)}


def _institution_breakdown(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        entry["holding_institution"]
        for entry in entries
        if entry.get("holding_institution")
    )
    return {key: counts[key] for key in sorted(counts)}


def _scan_byte_count(entries: list[dict[str, Any]]) -> int:
    total = 0
    for entry in entries:
        for file_obj in entry["files"]:
            byte_size = file_obj.get("bytes")
            if isinstance(byte_size, int):
                total += byte_size
    return total


def _check_attribution_consistency(entries: list[dict[str, Any]]) -> None:
    # Any entry whose license demands attribution must carry the flag, text,
    # and url. The schema enforces text+url *given* the flag; this layer catches
    # the prior failure mode of "license is CC-BY-SA but ingester forgot the
    # flag", which would silently drop the entry from NOTICE.md.
    for entry in entries:
        rights = entry["rights"]
        license_expr = rights.get("license_expression")
        if license_expr in ATTRIBUTION_REQUIRING_LICENSES:
            if rights.get("attribution_required") is not True:
                raise SystemExit(
                    f"{entry['entry_id']}: license {license_expr} requires "
                    f"rights.attribution_required: true (found "
                    f"{rights.get('attribution_required')!r})"
                )
            for field in ("attribution_text", "attribution_url"):
                value = rights.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise SystemExit(
                        f"{entry['entry_id']}: license {license_expr} requires "
                        f"rights.{field}, but it is null, blank, or whitespace-only"
                    )


def _attribution_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [
        entry
        for entry in entries
        if entry["rights"].get("license_expression") in ATTRIBUTION_REQUIRING_LICENSES
    ]
    return sorted(selected, key=lambda entry: entry["entry_id"])


def _notice_stanza(entry: dict[str, Any], recipe: dict[str, Any]) -> str:
    license_names: dict[str, str] = recipe["license_names"]
    license_urls: dict[str, str] = recipe["license_urls"]
    rights = entry["rights"]
    license_expr = rights["license_expression"]
    license_name = license_names.get(license_expr, license_expr)
    license_url = license_urls.get(license_expr)

    if license_url:
        license_line = f"- License: [{license_name} ({license_expr})]({license_url})"
    else:
        license_line = f"- License: {license_name} ({license_expr})"

    lines = [
        f"### {entry['title']}",
        "",
        f"- Entry: `{entry['entry_id']}`",
        license_line,
        f"- Licensor: {rights['attribution_text']}",
        f"- Source page: <{rights['attribution_url']}>",
    ]

    file_url = entry["files"][0].get("source_url") if entry.get("files") else None
    if file_url and file_url != rights["attribution_url"]:
        lines.append(f"- Scan file URL: <{file_url}>")

    holding = entry.get("holding_institution")
    if holding:
        shelf = entry.get("holding_shelfmark")
        if shelf:
            lines.append(f"- Holding institution: {holding} ({shelf})")
        else:
            lines.append(f"- Holding institution: {holding}")

    return "\n".join(lines)


NOTICE_TEMPLATE = """\
# NOTICE

This file is generated by `scripts/generate_release_artifacts.py` from \
`data/index/entries.jsonl`. Do not edit by hand.

Repository-authored metadata is dedicated to the public domain under \
CC0 1.0 Universal. See [`LICENSE`](LICENSE) and [`LICENSE.md`](LICENSE.md) \
for the full compound-licensing policy.

Scan files carry per-entry rights. The entries listed below carry a license \
that requires attribution (currently {license_set}). Anyone redistributing or \
reusing these scans must keep the listed credit and link to the source page \
on which the rights claim was verified.

- Corpus release: `{version}`
- Released at: `{released_at}`

## Attribution-required entries

{stanzas}

## Full per-entry rights

Every entry, attribution-required or not, ships with its rights record in \
[`data/index/entries.jsonl`](data/index/entries.jsonl). Consumers that need \
machine-readable rights metadata should read that file directly; the \
manifest at [`datapackage.json`](datapackage.json) summarises the license \
breakdown.
"""


def build_notice(
    entries: list[dict[str, Any]],
    recipe: dict[str, Any],
    released_at: str,
) -> str:
    required = _attribution_entries(entries)
    if required:
        stanzas = "\n\n".join(_notice_stanza(entry, recipe) for entry in required)
    else:
        stanzas = "_No entries in this release require attribution._"

    license_set = ", ".join(sorted(ATTRIBUTION_REQUIRING_LICENSES))
    return NOTICE_TEMPLATE.format(
        license_set=license_set,
        version=recipe["version"],
        released_at=released_at,
        stanzas=stanzas,
    )


def build_citation(
    entries: list[dict[str, Any]],
    recipe: dict[str, Any],
    released_at: str,
) -> str:
    license_counts = _license_breakdown(entries)
    breakdown_summary = ", ".join(
        f"{count} {license_id}" for license_id, count in license_counts.items()
    )
    entry_source_count = len({entry["source_id"] for entry in entries})

    abstract = (
        f"{recipe['description']} Release {recipe['version']} contains "
        f"{len(entries)} scan entries drawn from {entry_source_count} verified sources "
        f"({breakdown_summary})."
    )

    document: dict[str, Any] = {
        "cff-version": "1.2.0",
        "message": "Please cite this dataset using the metadata below.",
        "type": "dataset",
        "title": recipe["title"],
        "abstract": abstract,
        "authors": [{"name": author["name"]} for author in recipe["authors"]],
        "version": recipe["version"],
        "date-released": released_at[:10],
        "repository-code": recipe["repository_code"],
        "url": recipe["homepage"],
        "license": recipe["metadata_license"]["spdx"],
        "keywords": sorted(recipe["keywords"]),
    }
    identifiers = recipe.get("citation_identifiers") or []
    if identifiers:
        document["identifiers"] = identifiers

    header = "# Generated by scripts/generate_release_artifacts.py. Do not edit by hand.\n"
    body = yaml.safe_dump(
        document,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
    )
    return header + body


def build_datapackage(
    entries: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    recipe: dict[str, Any],
    released_at: str,
    entries_path: Path,
    sources_path: Path,
) -> dict[str, Any]:
    license_names: dict[str, str] = recipe["license_names"]
    license_urls: dict[str, str] = recipe["license_urls"]
    license_counts = _license_breakdown(entries)
    institutions = _institution_breakdown(entries)

    source_status_counts = Counter(source.get("status") for source in sources)
    source_status_breakdown = {
        key: source_status_counts[key]
        for key in sorted(source_status_counts)
        if key is not None
    }

    license_listings: list[dict[str, Any]] = []
    license_listings.append({
        "name": recipe["metadata_license"]["spdx"],
        "path": recipe["metadata_license"]["url"],
        "title": license_names.get(
            recipe["metadata_license"]["spdx"], recipe["metadata_license"]["spdx"]
        ),
        "scope": "metadata",
    })
    for license_id in sorted(license_counts):
        listing: dict[str, Any] = {
            "name": license_id,
            "title": license_names.get(license_id, license_id),
            "scope": "scans",
        }
        url = license_urls.get(license_id)
        if url:
            listing["path"] = url
        license_listings.append(listing)

    resource_path_for: dict[str, Path] = {
        "entries": entries_path,
        "sources": sources_path,
    }
    resource_records_for: dict[str, int] = {
        "entries": len(entries),
        "sources": len(sources),
    }

    resources: list[dict[str, Any]] = []
    for name in sorted(recipe["resources"]):
        spec = recipe["resources"][name]
        resource: dict[str, Any] = {
            "name": name,
            "path": spec["path"],
            "profile": "data-resource",
            "format": spec["format"],
            "mediatype": spec["mediatype"],
            "encoding": spec["encoding"],
            "description": spec["description"],
            "record_count": resource_records_for[name],
            "bytes": resource_path_for[name].stat().st_size,
        }
        if name == "entries":
            resource["schema"] = recipe["schema_urls"]["entry"]
        elif name == "sources":
            resource["schema"] = recipe["schema_urls"]["source"]
        resources.append(resource)

    return {
        "profile": "data-package",
        "name": recipe["name"],
        "title": recipe["title"],
        "description": recipe["description"],
        "version": recipe["version"],
        "released_at": released_at,
        "homepage": recipe["homepage"],
        "keywords": sorted(recipe["keywords"]),
        "contributors": [
            {"title": author["name"], "role": author.get("role", "author")}
            for author in recipe["authors"]
        ],
        "licenses": license_listings,
        "schemas": {
            "entry": recipe["schema_urls"]["entry"],
            "source": recipe["schema_urls"]["source"],
        },
        "stats": {
            "record_count": len(entries),
            "entry_source_count": len({entry["source_id"] for entry in entries}),
            "source_record_count": len(sources),
            "source_status_breakdown": source_status_breakdown,
            "scan_byte_count": _scan_byte_count(entries),
            "attribution_required_count": len(_attribution_entries(entries)),
            "license_breakdown": license_counts,
            "institution_breakdown": institutions,
        },
        "resources": resources,
    }


def _serialise_text(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _serialise_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _render(
    sources_path: Path,
    entries_path: Path,
    recipe_path: Path,
) -> dict[str, str]:
    sources = _load_jsonl(sources_path)
    entries = _load_jsonl(entries_path)
    recipe = _load_recipe(recipe_path)
    _check_attribution_consistency(entries)
    released_at = _derive_released_at(entries)

    return {
        "notice": _serialise_text(build_notice(entries, recipe, released_at)),
        "citation": _serialise_text(build_citation(entries, recipe, released_at)),
        "datapackage": _serialise_json(
            build_datapackage(
                entries, sources, recipe, released_at,
                entries_path=entries_path, sources_path=sources_path,
            )
        ),
    }


def generate(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    recipe_path: Path = RECIPE_PATH,
    notice_path: Path = NOTICE_PATH,
    citation_path: Path = CITATION_PATH,
    datapackage_path: Path = DATAPACKAGE_PATH,
) -> dict[str, Path]:
    rendered = _render(sources_path, entries_path, recipe_path)
    notice_path.write_text(rendered["notice"], encoding="utf-8")
    citation_path.write_text(rendered["citation"], encoding="utf-8")
    datapackage_path.write_text(rendered["datapackage"], encoding="utf-8")
    return {
        "notice": notice_path,
        "citation": citation_path,
        "datapackage": datapackage_path,
    }


def check(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    recipe_path: Path = RECIPE_PATH,
    notice_path: Path = NOTICE_PATH,
    citation_path: Path = CITATION_PATH,
    datapackage_path: Path = DATAPACKAGE_PATH,
) -> list[Path]:
    rendered = _render(sources_path, entries_path, recipe_path)
    stale: list[Path] = []
    for kind, path in (
        ("notice", notice_path),
        ("citation", citation_path),
        ("datapackage", datapackage_path),
    ):
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual != rendered[kind]:
            stale.append(path)
    return stale


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--entries", type=Path, default=ENTRIES_PATH)
    parser.add_argument("--recipe", type=Path, default=RECIPE_PATH)
    parser.add_argument("--notice", type=Path, default=NOTICE_PATH)
    parser.add_argument("--citation", type=Path, default=CITATION_PATH)
    parser.add_argument("--datapackage", type=Path, default=DATAPACKAGE_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify on-disk artefacts match what would be generated. Exit 1 if not.",
    )
    args = parser.parse_args()

    if args.check:
        stale = check(
            sources_path=args.sources,
            entries_path=args.entries,
            recipe_path=args.recipe,
            notice_path=args.notice,
            citation_path=args.citation,
            datapackage_path=args.datapackage,
        )
        if stale:
            for path in stale:
                try:
                    display = path.relative_to(REPO_ROOT)
                except ValueError:
                    display = path
                print(f"stale: {display}", file=sys.stderr)
            print(
                "Run `python3 scripts/generate_release_artifacts.py` to regenerate.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print("ok: release artefacts are up to date")
        return

    written = generate(
        sources_path=args.sources,
        entries_path=args.entries,
        recipe_path=args.recipe,
        notice_path=args.notice,
        citation_path=args.citation,
        datapackage_path=args.datapackage,
    )
    for label, path in written.items():
        try:
            display = path.relative_to(REPO_ROOT)
        except ValueError:
            display = path
        print(f"wrote {label}: {display}")


if __name__ == "__main__":
    main()
