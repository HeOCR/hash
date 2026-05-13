#!/usr/bin/env python3
"""Build deterministic CSV / Parquet exports from data/index/*.jsonl.

Emits three files:

  - exports/entries.csv   flat tabular view of entries.jsonl (committed).
  - exports/sources.csv   flat tabular view of sources.jsonl (committed).
  - dist/entries.parquet  same shape as entries.csv, Parquet-encoded
                          (build artefact under dist/, not committed).

The script is fully deterministic: same JSONL in, byte-identical CSV out.
The Parquet payload is also deterministic within a single pyarrow version
(its `created_by` metadata pins the writer version).

Use `--check` to verify the on-disk CSVs match what would be generated
without touching the tree. Parquet is not checked because it is not
committed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable

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
ENTRIES_PARQUET_PATH = REPO_ROOT / "dist" / "entries.parquet"

# Separator used inside flattened CSV/Parquet cells for array-valued fields
# (languages, script, creators, exclusion_reasons, etc.). Picked to be visually
# obvious and to never appear in any current corpus value; the writer asserts
# that nothing it serialises contains this token so silent collisions cannot
# happen.
LIST_SEPARATOR = "; "


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


def _join_list(values: list[Any] | None, *, field: str, row_id: str) -> str | None:
    if not values:
        return None
    rendered: list[str] = []
    for item in values:
        if item is None:
            text = ""
        else:
            text = str(item)
        if LIST_SEPARATOR in text:
            raise SystemExit(
                f"{row_id}: {field}: value {text!r} contains the list separator "
                f"{LIST_SEPARATOR!r}; pick a different separator or sanitise the input"
            )
        rendered.append(text)
    return LIST_SEPARATOR.join(rendered)


# ---- Column definitions -----------------------------------------------------
#
# Each column is a (name, pyarrow_type, extractor) triple. The extractor takes
# the row dict and returns a Python scalar (str/int/bool/None). CSV and Parquet
# share the same flattening, so a downstream consumer can join across the two
# formats without surprises.


def _entry_columns() -> list[tuple[str, pa.DataType, Callable[[dict[str, Any]], Any]]]:
    def _first_file(entry: dict[str, Any]) -> dict[str, Any]:
        files = entry["files"]
        if len(files) != 1:
            raise SystemExit(
                f"{entry['entry_id']}: expected exactly one entry in files[], got "
                f"{len(files)}. Multi-file entries are not yet flattenable; extend "
                f"build_exports.py before ingesting one."
            )
        return files[0]

    return [
        ("entry_id", pa.string(), lambda e: e["entry_id"]),
        ("source_id", pa.string(), lambda e: e["source_id"]),
        ("source_record_id", pa.string(), lambda e: e.get("source_record_id")),
        ("sequence_index", pa.int64(), lambda e: e["sequence"]["index"]),
        ("sequence_label", pa.string(), lambda e: e["sequence"].get("label")),
        ("sequence_physical_unit_count", pa.int64(),
         lambda e: e["sequence"]["physical_unit_count"]),
        ("title", pa.string(), lambda e: e["title"]),
        ("creator_names", pa.string(), lambda e: _join_list(
            [c["name"] for c in e.get("creators", [])],
            field="creators[].name", row_id=e["entry_id"])),
        ("creator_roles", pa.string(), lambda e: _join_list(
            [c["role"] for c in e.get("creators", [])],
            field="creators[].role", row_id=e["entry_id"])),
        ("creator_death_years", pa.string(), lambda e: _join_list(
            [c.get("death_year") if c.get("death_year") is not None else ""
             for c in e.get("creators", [])],
            field="creators[].death_year", row_id=e["entry_id"])),
        ("date_created", pa.string(), lambda e: e["dates"].get("created")),
        ("date_created_precision", pa.string(),
         lambda e: e["dates"]["created_precision"]),
        ("accessed_at", pa.string(), lambda e: e["dates"].get("accessed_at")),
        ("languages", pa.string(), lambda e: _join_list(
            e.get("languages"), field="languages", row_id=e["entry_id"])),
        ("script", pa.string(), lambda e: _join_list(
            e.get("script"), field="script", row_id=e["entry_id"])),
        ("document_type", pa.string(), lambda e: e["document_type"]),
        ("handwriting_extent", pa.string(),
         lambda e: e["handwriting"]["extent"]),
        ("handwriting_hebrew_extent", pa.string(),
         lambda e: e["handwriting"]["hebrew_extent"]),
        ("handwriting_notes", pa.string(),
         lambda e: e["handwriting"].get("notes")),
        ("file_role", pa.string(), lambda e: _first_file(e)["role"]),
        ("file_local_path", pa.string(),
         lambda e: _first_file(e).get("local_path")),
        ("file_source_url", pa.string(),
         lambda e: _first_file(e).get("source_url")),
        ("file_provider_file_id", pa.string(),
         lambda e: _first_file(e).get("provider_file_id")),
        ("file_sha256", pa.string(), lambda e: _first_file(e).get("sha256")),
        ("file_mime_type", pa.string(),
         lambda e: _first_file(e).get("mime_type")),
        ("file_bytes", pa.int64(), lambda e: _first_file(e).get("bytes")),
        ("file_width_px", pa.int64(),
         lambda e: _first_file(e).get("width_px")),
        ("file_height_px", pa.int64(),
         lambda e: _first_file(e).get("height_px")),
        ("rights_basis", pa.string(), lambda e: e["rights"]["rights_basis"]),
        ("license_expression", pa.string(),
         lambda e: e["rights"].get("license_expression")),
        ("commercial_use_allowed", pa.bool_(),
         lambda e: e["rights"].get("commercial_use_allowed")),
        ("derivatives_allowed", pa.bool_(),
         lambda e: e["rights"].get("derivatives_allowed")),
        ("scan_redistribution_allowed", pa.bool_(),
         lambda e: e["rights"].get("scan_redistribution_allowed")),
        ("attribution_required", pa.bool_(),
         lambda e: e["rights"].get("attribution_required")),
        ("attribution_text", pa.string(),
         lambda e: e["rights"].get("attribution_text")),
        ("attribution_url", pa.string(),
         lambda e: e["rights"].get("attribution_url")),
        ("rights_verification_status", pa.string(),
         lambda e: e["rights"]["verification_status"]),
        ("rights_evidence_text", pa.string(),
         lambda e: e["rights"].get("evidence_text")),
        ("rights_verified_at", pa.string(),
         lambda e: e["rights"].get("verified_at")),
        ("provenance_acquired_at", pa.string(),
         lambda e: e["provenance"].get("acquired_at")),
        ("provenance_acquired_by", pa.string(),
         lambda e: e["provenance"].get("acquired_by")),
        ("provenance_source_landing_url", pa.string(),
         lambda e: e["provenance"].get("source_landing_url")),
        ("provenance_notes", pa.string(),
         lambda e: e["provenance"].get("notes")),
        ("holding_institution", pa.string(),
         lambda e: e.get("holding_institution")),
        ("holding_shelfmark", pa.string(),
         lambda e: e.get("holding_shelfmark")),
        ("quality_usable_for_htr", pa.bool_(),
         lambda e: e["quality"].get("usable_for_htr")),
        ("quality_legibility", pa.string(),
         lambda e: e["quality"]["legibility"]),
        ("quality_exclusion_reasons", pa.string(), lambda e: _join_list(
            e["quality"].get("exclusion_reasons"),
            field="quality.exclusion_reasons", row_id=e["entry_id"])),
        ("quality_notes", pa.string(), lambda e: e["quality"].get("notes")),
        ("transcription_status", pa.string(),
         lambda e: e["transcription"]["status"]),
        ("transcription_text_path", pa.string(),
         lambda e: e["transcription"].get("text_path")),
        ("transcription_alto_path", pa.string(),
         lambda e: e["transcription"].get("alto_path")),
        ("transcription_hocr_path", pa.string(),
         lambda e: e["transcription"].get("hocr_path")),
        ("transcription_source_url", pa.string(),
         lambda e: e["transcription"].get("source_url")),
        ("transcription_created_by", pa.string(),
         lambda e: e["transcription"]["created_by"]),
        ("transcription_rights_basis", pa.string(),
         lambda e: e["transcription"]["rights"]["rights_basis"]),
        ("transcription_license_expression", pa.string(),
         lambda e: e["transcription"]["rights"].get("license_expression")),
        ("transcription_commercial_use_allowed", pa.bool_(),
         lambda e: e["transcription"]["rights"].get("commercial_use_allowed")),
        ("transcription_derivatives_allowed", pa.bool_(),
         lambda e: e["transcription"]["rights"].get("derivatives_allowed")),
        ("transcription_redistribution_allowed", pa.bool_(),
         lambda e: e["transcription"]["rights"].get("redistribution_allowed")),
        ("transcription_attribution_required", pa.bool_(),
         lambda e: e["transcription"]["rights"].get("attribution_required")),
        ("transcription_rights_verification_status", pa.string(),
         lambda e: e["transcription"]["rights"]["verification_status"]),
        ("transcription_rights_evidence_text", pa.string(),
         lambda e: e["transcription"]["rights"].get("evidence_text")),
        ("transcription_rights_verified_at", pa.string(),
         lambda e: e["transcription"]["rights"].get("verified_at")),
    ]


def _source_columns() -> list[tuple[str, pa.DataType, Callable[[dict[str, Any]], Any]]]:
    return [
        ("source_id", pa.string(), lambda s: s["source_id"]),
        ("record_type", pa.string(), lambda s: s["record_type"]),
        ("status", pa.string(), lambda s: s["status"]),
        ("priority", pa.string(), lambda s: s["priority"]),
        ("provider", pa.string(), lambda s: s["provider"]),
        ("title", pa.string(), lambda s: s["title"]),
        ("description", pa.string(), lambda s: s.get("description")),
        ("urls_canonical", pa.string(), lambda s: s["urls"]["canonical"]),
        ("urls_landing", pa.string(), lambda s: s["urls"].get("landing")),
        ("urls_api", pa.string(), lambda s: s["urls"].get("api")),
        ("urls_download", pa.string(), lambda s: s["urls"].get("download")),
        ("urls_related", pa.string(), lambda s: _join_list(
            s["urls"].get("related"), field="urls.related",
            row_id=s["source_id"])),
        ("rights_basis", pa.string(), lambda s: s["rights"]["rights_basis"]),
        ("license_expression", pa.string(),
         lambda s: s["rights"].get("license_expression")),
        ("commercial_use_allowed", pa.bool_(),
         lambda s: s["rights"].get("commercial_use_allowed")),
        ("derivatives_allowed", pa.bool_(),
         lambda s: s["rights"].get("derivatives_allowed")),
        ("scan_redistribution_allowed", pa.bool_(),
         lambda s: s["rights"].get("scan_redistribution_allowed")),
        ("attribution_required", pa.bool_(),
         lambda s: s["rights"].get("attribution_required")),
        ("rights_evidence_text", pa.string(),
         lambda s: s["rights"].get("evidence_text")),
        ("rights_terms_url", pa.string(),
         lambda s: s["rights"].get("terms_url")),
        ("rights_verification_status", pa.string(),
         lambda s: s["rights"]["verification_status"]),
        ("rights_verified_at", pa.string(),
         lambda s: s["rights"].get("verified_at")),
        ("scope_date_range", pa.string(),
         lambda s: s["scope"].get("date_range")),
        ("scope_languages", pa.string(), lambda s: _join_list(
            s["scope"].get("languages"), field="scope.languages",
            row_id=s["source_id"])),
        ("scope_document_types", pa.string(), lambda s: _join_list(
            s["scope"].get("document_types"), field="scope.document_types",
            row_id=s["source_id"])),
        ("scope_creator_names", pa.string(), lambda s: _join_list(
            s["scope"].get("creator_names"), field="scope.creator_names",
            row_id=s["source_id"])),
        ("scope_expected_handwriting", pa.string(),
         lambda s: s["scope"]["expected_handwriting"]),
        ("scope_estimated_scan_count", pa.int64(),
         lambda s: s["scope"].get("estimated_scan_count")),
        ("ingest_method", pa.string(), lambda s: s["ingest"]["method"]),
        ("ingest_access_notes", pa.string(),
         lambda s: s["ingest"].get("access_notes")),
        ("ingest_agent_notes", pa.string(),
         lambda s: s["ingest"].get("agent_notes")),
        ("ingest_blocked_reason", pa.string(),
         lambda s: s["ingest"].get("blocked_reason")),
        ("evidence_count", pa.int64(), lambda s: len(s.get("evidence", []))),
    ]


def _project(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, pa.DataType, Callable[[dict[str, Any]], Any]]],
    sort_key: str,
) -> tuple[list[str], list[list[Any]]]:
    names = [name for name, _type, _extractor in columns]
    extractors = [extractor for _name, _type, extractor in columns]
    projected = [[extractor(row) for extractor in extractors] for row in rows]
    # Sort by the sort_key column so output ordering is independent of
    # whatever order the JSONL happens to be in.
    key_index = names.index(sort_key)
    projected.sort(key=lambda values: values[key_index])
    return names, projected


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _serialise_csv(
    names: list[str],
    rows: list[list[Any]],
) -> bytes:
    # Use a string buffer (not bytes) because csv.writer requires text mode;
    # encode at the end so we control encoding (UTF-8, no BOM) and the line
    # terminator (LF, not CRLF) explicitly. Default csv.writer dialect uses
    # CRLF which would diff differently on Windows checkouts.
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, dialect="unix", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(names)
    for row in rows:
        writer.writerow(_csv_cell(value) for value in row)
    return buffer.getvalue().encode("utf-8")


def _build_parquet_bytes(
    names: list[str],
    rows: list[list[Any]],
    column_types: list[pa.DataType],
) -> bytes:
    fields = []
    for name, dtype in zip(names, column_types):
        nullable = name not in {"entry_id", "source_id", "sequence_index"}
        fields.append(pa.field(name, dtype, nullable=nullable))
    schema = pa.schema(fields)

    arrays = []
    for column_index, (name, dtype) in enumerate(zip(names, column_types)):
        values = [row[column_index] for row in rows]
        arrays.append(pa.array(values, type=dtype))
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


def _render(
    sources_path: Path,
    entries_path: Path,
) -> dict[str, bytes]:
    sources = _load_jsonl(sources_path)
    entries = _load_jsonl(entries_path)

    entry_columns = _entry_columns()
    source_columns = _source_columns()

    entry_names, entry_rows = _project(entries, entry_columns, sort_key="entry_id")
    source_names, source_rows = _project(sources, source_columns, sort_key="source_id")

    return {
        "entries_csv": _serialise_csv(entry_names, entry_rows),
        "sources_csv": _serialise_csv(source_names, source_rows),
        "entries_parquet": _build_parquet_bytes(
            entry_names, entry_rows, [t for _n, t, _e in entry_columns]
        ),
    }


def generate(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    entries_csv_path: Path = ENTRIES_CSV_PATH,
    sources_csv_path: Path = SOURCES_CSV_PATH,
    entries_parquet_path: Path = ENTRIES_PARQUET_PATH,
) -> dict[str, Path]:
    rendered = _render(sources_path, entries_path)
    for path in (entries_csv_path, sources_csv_path, entries_parquet_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    entries_csv_path.write_bytes(rendered["entries_csv"])
    sources_csv_path.write_bytes(rendered["sources_csv"])
    entries_parquet_path.write_bytes(rendered["entries_parquet"])
    return {
        "entries_csv": entries_csv_path,
        "sources_csv": sources_csv_path,
        "entries_parquet": entries_parquet_path,
    }


def check(
    sources_path: Path = SOURCES_PATH,
    entries_path: Path = ENTRIES_PATH,
    entries_csv_path: Path = ENTRIES_CSV_PATH,
    sources_csv_path: Path = SOURCES_CSV_PATH,
) -> list[Path]:
    # Parquet lives under dist/ (a build artefact) and is not committed, so
    # --check intentionally only validates the CSV exports — those are what CI
    # protects against drift.
    rendered = _render(sources_path, entries_path)
    stale: list[Path] = []
    for kind, path in (
        ("entries_csv", entries_csv_path),
        ("sources_csv", sources_csv_path),
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
