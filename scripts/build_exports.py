#!/usr/bin/env python3
"""Build deterministic CSV / Parquet exports from data/index/*.jsonl.

Emits four files:

  - exports/entries.csv    one row per scan entry (committed).
  - exports/sources.csv    one row per source row (committed).
  - exports/creators.csv   one row per (entry, creator) pair (committed).
  - dist/entries.parquet   same shape as entries.csv, Parquet-encoded
                           (build artefact under dist/, not committed).

The script is fully deterministic: same JSONL in, byte-identical CSV out.
The Parquet payload is also deterministic within a single pyarrow version
(its `created_by` metadata pins the writer version).

Use `--check` to verify the on-disk CSVs match what would be generated
without touching the tree. Parquet is not checked because it is not
committed.

Design notes
------------

* entries.csv flattens `files[].role == "original"`. Schema permits multiple
  files per entry with different roles (`original`, `normalized`,
  `thumbnail`, ...); the flat CSV picks the canonical original and exposes
  the total via `file_count`. Add a separate `exports/entry_files.csv` if
  and when consumers need access to non-original roles.
* Creators are one-to-many per entry. Parallel-array flattening
  ("name1; name2", "role1; role2") loses positional alignment when nulls
  appear in the middle; instead, creators ship in their own CSV with one
  row per creator. entries.csv carries `creator_count` for quick filtering
  without a join.
* Maintenance note: each new schema field is a three-place edit — the
  column tuple list below, the per-row projection function, and the
  REQUIRED test column list in tests/test_build_exports.py. A Frictionless
  Table Schema would collapse this to one place; that is a follow-up.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as exc:  # pragma: no cover - exercised when deps are absent.
    raise SystemExit(
        "Missing dependency: pyarrow. Install development dependencies with "
        "`python3 -m pip install -r requirements-dev.txt`."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES_PATH = REPO_ROOT / "data" / "index" / "entries.jsonl"
ENTRIES_CSV_PATH = REPO_ROOT / "exports" / "entries.csv"
SOURCES_CSV_PATH = REPO_ROOT / "exports" / "sources.csv"
CREATORS_CSV_PATH = REPO_ROOT / "exports" / "creators.csv"
ENTRIES_PARQUET_PATH = REPO_ROOT / "dist" / "entries.parquet"

# Separator used inside flattened CSV/Parquet cells for array-valued fields
# (languages, script, exclusion_reasons, etc.). Picked to be visually obvious
# and to never appear in any current corpus value; the writer raises
# ValueError if a value collides with this token so silent collisions cannot
# happen.
LIST_SEPARATOR = "; "


# ---- Column lists -----------------------------------------------------------
#
# Each column is a `(name, pyarrow_type)` pair. Row projection is a separate
# pass below, so this list is purely a description of the schema and the
# Parquet wire types.

ENTRY_COLUMNS: list[tuple[str, pa.DataType]] = [
    ("entry_id", pa.string()),
    ("source_id", pa.string()),
    ("source_record_id", pa.string()),
    ("sequence_index", pa.int64()),
    ("sequence_label", pa.string()),
    ("sequence_physical_unit_count", pa.int64()),
    ("title", pa.string()),
    ("creator_count", pa.int64()),
    ("date_created", pa.string()),
    ("date_created_precision", pa.string()),
    ("accessed_at", pa.string()),
    ("languages", pa.string()),
    ("script", pa.string()),
    ("document_type", pa.string()),
    ("handwriting_extent", pa.string()),
    ("handwriting_hebrew_extent", pa.string()),
    ("handwriting_notes", pa.string()),
    ("file_count", pa.int64()),
    ("file_role", pa.string()),
    ("file_local_path", pa.string()),
    ("file_source_url", pa.string()),
    ("file_provider_file_id", pa.string()),
    ("file_sha256", pa.string()),
    ("file_mime_type", pa.string()),
    ("file_bytes", pa.int64()),
    ("file_width_px", pa.int64()),
    ("file_height_px", pa.int64()),
    ("rights_basis", pa.string()),
    ("license_expression", pa.string()),
    ("commercial_use_allowed", pa.bool_()),
    ("derivatives_allowed", pa.bool_()),
    ("scan_redistribution_allowed", pa.bool_()),
    ("attribution_required", pa.bool_()),
    ("attribution_text", pa.string()),
    ("attribution_url", pa.string()),
    ("rights_verification_status", pa.string()),
    ("rights_evidence_text", pa.string()),
    ("rights_verified_at", pa.string()),
    ("provenance_acquired_at", pa.string()),
    ("provenance_acquired_by", pa.string()),
    ("provenance_source_landing_url", pa.string()),
    ("provenance_notes", pa.string()),
    ("holding_institution", pa.string()),
    ("holding_shelfmark", pa.string()),
    ("quality_usable_for_htr", pa.bool_()),
    ("quality_legibility", pa.string()),
    ("quality_exclusion_reasons", pa.string()),
    ("quality_notes", pa.string()),
    ("transcription_status", pa.string()),
    ("transcription_text_path", pa.string()),
    ("transcription_alto_path", pa.string()),
    ("transcription_hocr_path", pa.string()),
    ("transcription_source_url", pa.string()),
    ("transcription_created_by", pa.string()),
    ("transcription_rights_basis", pa.string()),
    ("transcription_license_expression", pa.string()),
    ("transcription_commercial_use_allowed", pa.bool_()),
    ("transcription_derivatives_allowed", pa.bool_()),
    ("transcription_redistribution_allowed", pa.bool_()),
    ("transcription_attribution_required", pa.bool_()),
    ("transcription_rights_verification_status", pa.string()),
    ("transcription_rights_evidence_text", pa.string()),
    ("transcription_rights_verified_at", pa.string()),
]

SOURCE_COLUMNS: list[tuple[str, pa.DataType]] = [
    ("source_id", pa.string()),
    ("record_type", pa.string()),
    ("status", pa.string()),
    ("priority", pa.string()),
    ("provider", pa.string()),
    ("title", pa.string()),
    ("description", pa.string()),
    ("urls_canonical", pa.string()),
    ("urls_landing", pa.string()),
    ("urls_api", pa.string()),
    ("urls_download", pa.string()),
    ("urls_related", pa.string()),
    ("rights_basis", pa.string()),
    ("license_expression", pa.string()),
    ("commercial_use_allowed", pa.bool_()),
    ("derivatives_allowed", pa.bool_()),
    ("scan_redistribution_allowed", pa.bool_()),
    ("attribution_required", pa.bool_()),
    ("rights_evidence_text", pa.string()),
    ("rights_terms_url", pa.string()),
    ("rights_verification_status", pa.string()),
    ("rights_verified_at", pa.string()),
    ("scope_date_range", pa.string()),
    ("scope_languages", pa.string()),
    ("scope_document_types", pa.string()),
    ("scope_creator_names", pa.string()),
    ("scope_expected_handwriting", pa.string()),
    ("scope_estimated_scan_count", pa.int64()),
    ("ingest_method", pa.string()),
    ("ingest_access_notes", pa.string()),
    ("ingest_agent_notes", pa.string()),
    ("ingest_blocked_reason", pa.string()),
    ("evidence_count", pa.int64()),
]

CREATOR_COLUMNS: list[tuple[str, pa.DataType]] = [
    ("entry_id", pa.string()),
    ("position", pa.int64()),
    ("name", pa.string()),
    ("role", pa.string()),
    ("death_year", pa.int64()),
    ("authority_url", pa.string()),
]

NON_NULLABLE_FIELDS = frozenset({
    "entry_id", "source_id", "sequence_index", "position",
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


def _join_list(values: list[Any] | None, *, field: str) -> str | None:
    """Join a list of scalars with LIST_SEPARATOR; raise on collision.

    Returns None for empty/missing lists so the CSV cell ends up blank
    rather than carrying a meaningless empty separator. Library-level
    error path is ValueError; the entry-point script translates that to a
    SystemExit with file/row context.
    """
    if not values:
        return None
    rendered: list[str] = []
    for item in values:
        text = "" if item is None else str(item)
        if LIST_SEPARATOR in text:
            raise ValueError(
                f"{field}: value {text!r} contains the list separator "
                f"{LIST_SEPARATOR!r}; pick a different separator or "
                f"sanitise the input"
            )
        rendered.append(text)
    return LIST_SEPARATOR.join(rendered)


def _pick_original_file(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the single `role == "original"` file for an entry.

    The schema allows multiple roles per entry (`original`, `normalized`,
    `thumbnail`, ...); the flat CSV is anchored on the canonical scan, so
    we require exactly one original. Zero or multiple originals indicate a
    data bug and abort the export.
    """
    originals = [f for f in entry["files"] if f["role"] == "original"]
    if len(originals) != 1:
        raise ValueError(
            f"{entry['entry_id']}: expected exactly one file with "
            f"role=='original', found {len(originals)}. Fix the entry or "
            f"extend build_exports.py before ingesting this row."
        )
    return originals[0]


def _project_entry(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        original = _pick_original_file(entry)
        files = entry["files"]
        rights = entry["rights"]
        provenance = entry["provenance"]
        quality = entry["quality"]
        transcription = entry["transcription"]
        transcription_rights = transcription["rights"]

        return {
            "entry_id": entry["entry_id"],
            "source_id": entry["source_id"],
            "source_record_id": entry.get("source_record_id"),
            "sequence_index": entry["sequence"]["index"],
            "sequence_label": entry["sequence"].get("label"),
            "sequence_physical_unit_count": entry["sequence"]["physical_unit_count"],
            "title": entry["title"],
            "creator_count": len(entry.get("creators", [])),
            "date_created": entry["dates"].get("created"),
            "date_created_precision": entry["dates"]["created_precision"],
            "accessed_at": entry["dates"].get("accessed_at"),
            "languages": _join_list(entry.get("languages"), field="languages"),
            "script": _join_list(entry.get("script"), field="script"),
            "document_type": entry["document_type"],
            "handwriting_extent": entry["handwriting"]["extent"],
            "handwriting_hebrew_extent": entry["handwriting"]["hebrew_extent"],
            "handwriting_notes": entry["handwriting"].get("notes"),
            "file_count": len(files),
            "file_role": original["role"],
            "file_local_path": original.get("local_path"),
            "file_source_url": original.get("source_url"),
            "file_provider_file_id": original.get("provider_file_id"),
            "file_sha256": original.get("sha256"),
            "file_mime_type": original.get("mime_type"),
            "file_bytes": original.get("bytes"),
            "file_width_px": original.get("width_px"),
            "file_height_px": original.get("height_px"),
            "rights_basis": rights["rights_basis"],
            "license_expression": rights.get("license_expression"),
            "commercial_use_allowed": rights.get("commercial_use_allowed"),
            "derivatives_allowed": rights.get("derivatives_allowed"),
            "scan_redistribution_allowed": rights.get("scan_redistribution_allowed"),
            "attribution_required": rights.get("attribution_required"),
            "attribution_text": rights.get("attribution_text"),
            "attribution_url": rights.get("attribution_url"),
            "rights_verification_status": rights["verification_status"],
            "rights_evidence_text": rights.get("evidence_text"),
            "rights_verified_at": rights.get("verified_at"),
            "provenance_acquired_at": provenance.get("acquired_at"),
            "provenance_acquired_by": provenance.get("acquired_by"),
            "provenance_source_landing_url": provenance.get("source_landing_url"),
            "provenance_notes": provenance.get("notes"),
            "holding_institution": entry.get("holding_institution"),
            "holding_shelfmark": entry.get("holding_shelfmark"),
            "quality_usable_for_htr": quality.get("usable_for_htr"),
            "quality_legibility": quality["legibility"],
            "quality_exclusion_reasons": _join_list(
                quality.get("exclusion_reasons"), field="quality.exclusion_reasons"
            ),
            "quality_notes": quality.get("notes"),
            "transcription_status": transcription["status"],
            "transcription_text_path": transcription.get("text_path"),
            "transcription_alto_path": transcription.get("alto_path"),
            "transcription_hocr_path": transcription.get("hocr_path"),
            "transcription_source_url": transcription.get("source_url"),
            "transcription_created_by": transcription["created_by"],
            "transcription_rights_basis": transcription_rights["rights_basis"],
            "transcription_license_expression": transcription_rights.get(
                "license_expression"
            ),
            "transcription_commercial_use_allowed": transcription_rights.get(
                "commercial_use_allowed"
            ),
            "transcription_derivatives_allowed": transcription_rights.get(
                "derivatives_allowed"
            ),
            "transcription_redistribution_allowed": transcription_rights.get(
                "redistribution_allowed"
            ),
            "transcription_attribution_required": transcription_rights.get(
                "attribution_required"
            ),
            "transcription_rights_verification_status": transcription_rights[
                "verification_status"
            ],
            "transcription_rights_evidence_text": transcription_rights.get(
                "evidence_text"
            ),
            "transcription_rights_verified_at": transcription_rights.get(
                "verified_at"
            ),
        }
    except ValueError as exc:
        raise SystemExit(f"{entry.get('entry_id', '<no entry_id>')}: {exc}") from exc


def _project_source(source: dict[str, Any]) -> dict[str, Any]:
    try:
        urls = source["urls"]
        rights = source["rights"]
        scope = source["scope"]
        ingest = source["ingest"]
        return {
            "source_id": source["source_id"],
            "record_type": source["record_type"],
            "status": source["status"],
            "priority": source["priority"],
            "provider": source["provider"],
            "title": source["title"],
            "description": source.get("description"),
            "urls_canonical": urls["canonical"],
            "urls_landing": urls.get("landing"),
            "urls_api": urls.get("api"),
            "urls_download": urls.get("download"),
            "urls_related": _join_list(urls.get("related"), field="urls.related"),
            "rights_basis": rights["rights_basis"],
            "license_expression": rights.get("license_expression"),
            "commercial_use_allowed": rights.get("commercial_use_allowed"),
            "derivatives_allowed": rights.get("derivatives_allowed"),
            "scan_redistribution_allowed": rights.get("scan_redistribution_allowed"),
            "attribution_required": rights.get("attribution_required"),
            "rights_evidence_text": rights.get("evidence_text"),
            "rights_terms_url": rights.get("terms_url"),
            "rights_verification_status": rights["verification_status"],
            "rights_verified_at": rights.get("verified_at"),
            "scope_date_range": scope.get("date_range"),
            "scope_languages": _join_list(
                scope.get("languages"), field="scope.languages"
            ),
            "scope_document_types": _join_list(
                scope.get("document_types"), field="scope.document_types"
            ),
            "scope_creator_names": _join_list(
                scope.get("creator_names"), field="scope.creator_names"
            ),
            "scope_expected_handwriting": scope["expected_handwriting"],
            "scope_estimated_scan_count": scope.get("estimated_scan_count"),
            "ingest_method": ingest["method"],
            "ingest_access_notes": ingest.get("access_notes"),
            "ingest_agent_notes": ingest.get("agent_notes"),
            "ingest_blocked_reason": ingest.get("blocked_reason"),
            "evidence_count": len(source.get("evidence", [])),
        }
    except ValueError as exc:
        raise SystemExit(
            f"{source.get('source_id', '<no source_id>')}: {exc}"
        ) from exc


def _project_creators(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield one dict per creator on the entry. Empty list if entry has none."""
    return [
        {
            "entry_id": entry["entry_id"],
            "position": position,
            "name": creator["name"],
            "role": creator["role"],
            "death_year": creator.get("death_year"),
            "authority_url": creator.get("authority_url"),
        }
        for position, creator in enumerate(entry.get("creators", []))
    ]


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _serialise_csv(
    columns: list[tuple[str, pa.DataType]],
    rows: list[dict[str, Any]],
) -> bytes:
    names = [name for name, _t in columns]
    buffer = io.StringIO()
    # `unix` dialect uses LF terminators and QUOTE_ALL; QUOTE_MINIMAL keeps
    # the output diff-friendly (only quote when a comma, quote, or newline
    # appears in the field).
    writer = csv.writer(buffer, dialect="unix", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(names)
    for row in rows:
        writer.writerow([_csv_cell(row[name]) for name in names])
    return buffer.getvalue().encode("utf-8")


def _build_parquet_bytes(
    columns: list[tuple[str, pa.DataType]],
    rows: list[dict[str, Any]],
) -> bytes:
    fields = []
    for name, dtype in columns:
        nullable = name not in NON_NULLABLE_FIELDS
        fields.append(pa.field(name, dtype, nullable=nullable))
    schema = pa.schema(fields)

    arrays = []
    for name, dtype in columns:
        arrays.append(pa.array([row[name] for row in rows], type=dtype))
    table = pa.Table.from_arrays(arrays, schema=schema)

    sink = io.BytesIO()
    pq.write_table(
        table,
        sink,
        compression="snappy",
        version="2.6",
        use_dictionary=True,
        write_statistics=True,
    )
    return sink.getvalue()


def _project_rows(
    items: list[dict[str, Any]],
    projector: Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]],
    *,
    sort_key: str,
    flatten: bool = False,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for item in items:
        result = projector(item)
        if flatten:
            projected.extend(result)
        else:
            projected.append(result)
    projected.sort(key=lambda row: (row[sort_key], row.get("position", 0)))
    return projected


def _render(sources_path: Path, entries_path: Path) -> dict[str, bytes]:
    sources = _load_jsonl(sources_path)
    entries = _load_jsonl(entries_path)

    entry_rows = _project_rows(entries, _project_entry, sort_key="entry_id")
    source_rows = _project_rows(sources, _project_source, sort_key="source_id")
    creator_rows = _project_rows(
        entries, _project_creators, sort_key="entry_id", flatten=True
    )

    return {
        "entries_csv": _serialise_csv(ENTRY_COLUMNS, entry_rows),
        "sources_csv": _serialise_csv(SOURCE_COLUMNS, source_rows),
        "creators_csv": _serialise_csv(CREATOR_COLUMNS, creator_rows),
        "entries_parquet": _build_parquet_bytes(ENTRY_COLUMNS, entry_rows),
    }


def generate(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    entries_csv_path: Path = ENTRIES_CSV_PATH,
    sources_csv_path: Path = SOURCES_CSV_PATH,
    creators_csv_path: Path = CREATORS_CSV_PATH,
    entries_parquet_path: Path = ENTRIES_PARQUET_PATH,
) -> dict[str, Path]:
    rendered = _render(sources_path, entries_path)
    targets = {
        "entries_csv": entries_csv_path,
        "sources_csv": sources_csv_path,
        "creators_csv": creators_csv_path,
        "entries_parquet": entries_parquet_path,
    }
    for path in targets.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    for kind, path in targets.items():
        path.write_bytes(rendered[kind])
    return targets


def check(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    entries_csv_path: Path = ENTRIES_CSV_PATH,
    sources_csv_path: Path = SOURCES_CSV_PATH,
    creators_csv_path: Path = CREATORS_CSV_PATH,
) -> list[Path]:
    # Parquet lives under dist/ (a build artefact) and is not committed, so
    # --check intentionally only validates the CSV exports — those are what
    # CI protects against drift.
    rendered = _render(sources_path, entries_path)
    stale: list[Path] = []
    for kind, path in (
        ("entries_csv", entries_csv_path),
        ("sources_csv", sources_csv_path),
        ("creators_csv", creators_csv_path),
    ):
        actual = path.read_bytes() if path.exists() else b""
        if actual != rendered[kind]:
            stale.append(path)
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--entries", type=Path, default=ENTRIES_PATH)
    parser.add_argument("--entries-csv", type=Path, default=ENTRIES_CSV_PATH)
    parser.add_argument("--sources-csv", type=Path, default=SOURCES_CSV_PATH)
    parser.add_argument("--creators-csv", type=Path, default=CREATORS_CSV_PATH)
    parser.add_argument("--entries-parquet", type=Path, default=ENTRIES_PARQUET_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify on-disk CSV exports match what would be generated. Exit 1 if not.",
    )
    args = parser.parse_args()

    if args.check:
        stale = check(
            sources_path=args.sources,
            entries_path=args.entries,
            entries_csv_path=args.entries_csv,
            sources_csv_path=args.sources_csv,
            creators_csv_path=args.creators_csv,
        )
        if stale:
            for path in stale:
                try:
                    display = path.relative_to(REPO_ROOT)
                except ValueError:
                    display = path
                print(f"stale: {display}", file=sys.stderr)
            print(
                "Run `python3 scripts/build_exports.py` to regenerate.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print("ok: CSV exports are up to date")
        return

    written = generate(
        sources_path=args.sources,
        entries_path=args.entries,
        entries_csv_path=args.entries_csv,
        sources_csv_path=args.sources_csv,
        creators_csv_path=args.creators_csv,
        entries_parquet_path=args.entries_parquet,
    )
    for label, path in written.items():
        try:
            display = path.relative_to(REPO_ROOT)
        except ValueError:
            display = path
        print(f"wrote {label}: {display}")


if __name__ == "__main__":
    main()
