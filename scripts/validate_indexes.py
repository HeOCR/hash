#!/usr/bin/env python3
"""Lightweight validation for the JSONL dataset indexes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES_PATH = REPO_ROOT / "data" / "index" / "entries.jsonl"

SOURCE_REQUIRED = {
    "source_id",
    "record_type",
    "status",
    "priority",
    "provider",
    "title",
    "urls",
    "rights",
    "scope",
    "ingest",
    "evidence",
}

ENTRY_REQUIRED = {
    "entry_id",
    "source_id",
    "source_record_id",
    "sequence",
    "title",
    "creators",
    "dates",
    "languages",
    "script",
    "document_type",
    "handwriting",
    "files",
    "rights",
    "provenance",
    "quality",
    "transcription",
}


def load_jsonl(path: Path, required: set[str], id_key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []

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

            missing = sorted(required - row.keys())
            if missing:
                raise SystemExit(
                    f"{path}:{line_number}: missing required fields: {', '.join(missing)}"
                )

            row_id = row.get(id_key)
            if not isinstance(row_id, str) or not row_id:
                raise SystemExit(f"{path}:{line_number}: {id_key} must be a non-empty string")
            if row_id in seen:
                raise SystemExit(f"{path}:{line_number}: duplicate {id_key}: {row_id}")
            seen.add(row_id)
            rows.append(row)
    return rows


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--entries", type=Path, default=ENTRIES_PATH)
    args = parser.parse_args()

    sources = load_jsonl(args.sources, SOURCE_REQUIRED, "source_id")
    entries = load_jsonl(args.entries, ENTRY_REQUIRED, "entry_id")
    validate_entries(entries, {source["source_id"] for source in sources})

    print(f"ok: {len(sources)} sources, {len(entries)} entries")


if __name__ == "__main__":
    main()
