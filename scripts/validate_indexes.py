#!/usr/bin/env python3
"""Validate the JSONL dataset indexes against their JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import SchemaError
except ImportError as exc:  # pragma: no cover - exercised when deps are absent.
    raise SystemExit(
        "Missing dependency: jsonschema. Install development dependencies with "
        "`python3 -m pip install -r requirements-dev.txt`."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES_PATH = REPO_ROOT / "data" / "index" / "entries.jsonl"
SOURCE_SCHEMA_PATH = REPO_ROOT / "schemas" / "source.schema.json"
ENTRY_SCHEMA_PATH = REPO_ROOT / "schemas" / "entry.schema.json"
RECIPE_PATH = REPO_ROOT / "scripts" / "release_recipe.json"
RECIPE_SCHEMA_PATH = REPO_ROOT / "schemas" / "release_recipe.schema.json"


def load_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON schema: {exc}") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SystemExit(f"{path}: invalid JSON schema: {exc.message}") from exc
    return schema


def load_jsonl(path: Path, validator: Draft202012Validator, id_key: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"{path}:{line_number}: row must be a JSON object")

            errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
            if errors:
                first = errors[0]
                location = ".".join(str(part) for part in first.path) or "<root>"
                raise SystemExit(f"{path}:{line_number}: {location}: {first.message}")

            row_id = row.get(id_key)
            if not isinstance(row_id, str) or not row_id:
                raise SystemExit(f"{path}:{line_number}: {id_key} must be a non-empty string")
            if row_id in seen:
                raise SystemExit(f"{path}:{line_number}: duplicate {id_key}: {row_id}")
            seen.add(row_id)
            rows.append(row)
    return rows


def validate_recipe(path: Path, validator: Draft202012Validator) -> None:
    if not path.exists():
        raise SystemExit(f"{path}: file does not exist")
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(recipe, dict):
        raise SystemExit(f"{path}: recipe must be a JSON object")

    errors = sorted(validator.iter_errors(recipe), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise SystemExit(f"{path}: {location}: {first.message}")

    # Cross-keyset checks the schema cannot express. The generator falls back to
    # the SPDX id when license_names is missing an entry, so a missing name
    # silently degrades NOTICE.md / CITATION.cff output instead of erroring.
    license_names: dict[str, str] = recipe["license_names"]
    license_urls: dict[str, str] = recipe["license_urls"]
    metadata_spdx = recipe["metadata_license"]["spdx"]
    if metadata_spdx not in license_names:
        raise SystemExit(
            f"{path}: metadata_license.spdx: "
            f"{metadata_spdx!r} must also appear as a key in license_names"
        )
    missing_names = sorted(set(license_urls) - set(license_names))
    if missing_names:
        raise SystemExit(
            f"{path}: license_urls: "
            f"keys missing from license_names: {missing_names}"
        )


def validate_entries(entries: list[dict[str, Any]], source_ids: set[str]) -> None:
    entry_ids: set[str] = set()
    for entry in entries:
        entry_id = entry["entry_id"]
        source_id = entry["source_id"]
        if source_id not in source_ids:
            raise SystemExit(f"{entry_id}: unknown source_id: {source_id}")
        if not entry_id.startswith(f"{source_id}__p"):
            raise SystemExit(f"{entry_id}: entry_id must start with source_id plus __p")
        if entry_id in entry_ids:
            raise SystemExit(f"{entry_id}: duplicate entry_id")
        entry_ids.add(entry_id)

        rights = entry["rights"]
        if rights.get("attribution_required") is True:
            attribution_text = rights.get("attribution_text")
            if not isinstance(attribution_text, str) or not attribution_text.strip():
                raise SystemExit(
                    f"{entry_id}: rights.attribution_required is true but "
                    f"rights.attribution_text is null, blank, or whitespace-only"
                )
            attribution_url = rights.get("attribution_url")
            if not isinstance(attribution_url, str) or not attribution_url.strip():
                raise SystemExit(
                    f"{entry_id}: rights.attribution_required is true but "
                    f"rights.attribution_url is null, blank, or whitespace-only"
                )


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_entry_files(entries: list[dict[str, Any]], repo_root: Path) -> int:
    verified = 0
    for entry in entries:
        entry_id = entry["entry_id"]
        for file_obj in entry["files"]:
            local_path = file_obj["local_path"]
            if local_path is None:
                continue

            local_path_obj = Path(local_path)
            if local_path_obj.is_absolute() or ".." in local_path_obj.parts:
                raise SystemExit(
                    f"{entry_id}: local_path must be repo-relative without '..': {local_path}"
                )

            absolute = repo_root / local_path_obj
            if not absolute.is_file():
                raise SystemExit(f"{entry_id}: file does not exist: {local_path}")

            expected_bytes = file_obj["bytes"]
            if expected_bytes is not None:
                actual_bytes = absolute.stat().st_size
                if actual_bytes != expected_bytes:
                    raise SystemExit(
                        f"{entry_id}: byte size mismatch for {local_path}: "
                        f"expected {expected_bytes}, got {actual_bytes}"
                    )

            expected_sha = file_obj["sha256"]
            if expected_sha is not None:
                actual_sha = _sha256_file(absolute)
                if actual_sha != expected_sha:
                    raise SystemExit(
                        f"{entry_id}: sha256 mismatch for {local_path}: "
                        f"expected {expected_sha}, got {actual_sha}"
                    )

            verified += 1
    return verified


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--entries", type=Path, default=ENTRIES_PATH)
    parser.add_argument("--source-schema", type=Path, default=SOURCE_SCHEMA_PATH)
    parser.add_argument("--entry-schema", type=Path, default=ENTRY_SCHEMA_PATH)
    parser.add_argument("--recipe", type=Path, default=RECIPE_PATH)
    parser.add_argument("--recipe-schema", type=Path, default=RECIPE_SCHEMA_PATH)
    args = parser.parse_args()

    source_validator = Draft202012Validator(
        load_schema(args.source_schema), format_checker=FormatChecker()
    )
    entry_validator = Draft202012Validator(
        load_schema(args.entry_schema), format_checker=FormatChecker()
    )
    recipe_validator = Draft202012Validator(
        load_schema(args.recipe_schema), format_checker=FormatChecker()
    )

    # Recipe first: it is one small file, so a typo should not cost a full
    # file-integrity hash pass before surfacing.
    validate_recipe(args.recipe, recipe_validator)
    sources = load_jsonl(args.sources, source_validator, "source_id")
    entries = load_jsonl(args.entries, entry_validator, "entry_id")
    validate_entries(entries, {source["source_id"] for source in sources})
    verified = validate_entry_files(entries, REPO_ROOT)

    print(
        f"ok: {len(sources)} sources, {len(entries)} entries, "
        f"{verified} files verified, recipe ok"
    )


if __name__ == "__main__":
    main()
