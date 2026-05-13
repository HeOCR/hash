from __future__ import annotations

import csv
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_exports.py"

_spec = importlib.util.spec_from_file_location("build_exports", BUILDER)
_bx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bx)

SOURCES = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES = REPO_ROOT / "data" / "index" / "entries.jsonl"
DATAPACKAGE = REPO_ROOT / "datapackage.json"
ENTRIES_CSV = REPO_ROOT / "exports" / "entries.csv"
SOURCES_CSV = REPO_ROOT / "exports" / "sources.csv"


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def _run_builder(
    *,
    cwd: Path,
    sources: Path = SOURCES,
    entries: Path = ENTRIES,
    entries_csv: Path,
    sources_csv: Path,
    entries_parquet: Path,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--sources", str(sources),
            "--entries", str(entries),
            "--entries-csv", str(entries_csv),
            "--sources-csv", str(sources_csv),
            "--entries-parquet", str(entries_parquet),
            *extra_args,
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_committed_csvs_are_up_to_date(tmp_path: Path) -> None:
    # Pytest mirror of the CI `--check` step: catches "didn't regenerate
    # before committing". The CI workflow itself catches "regenerated locally
    # but didn't stage". Intentionally redundant.
    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    entries_parquet = tmp_path / "entries.parquet"

    result = _run_builder(
        cwd=tmp_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        entries_parquet=entries_parquet,
    )
    assert result.returncode == 0, result.stderr

    assert entries_csv.read_bytes() == ENTRIES_CSV.read_bytes(), (
        "exports/entries.csv is stale; run `python3 scripts/build_exports.py`"
    )
    assert sources_csv.read_bytes() == SOURCES_CSV.read_bytes(), (
        "exports/sources.csv is stale; run `python3 scripts/build_exports.py`"
    )


def test_builder_is_idempotent(tmp_path: Path) -> None:
    paths = {
        "entries_csv": tmp_path / "entries.csv",
        "sources_csv": tmp_path / "sources.csv",
        "entries_parquet": tmp_path / "entries.parquet",
    }

    first = _run_builder(cwd=tmp_path, **paths)
    assert first.returncode == 0, first.stderr
    snapshot = {name: path.read_bytes() for name, path in paths.items()}

    second = _run_builder(cwd=tmp_path, **paths)
    assert second.returncode == 0, second.stderr
    for name, path in paths.items():
        assert path.read_bytes() == snapshot[name], f"{name} differed between runs"


def test_entries_csv_row_count_matches_jsonl_and_datapackage() -> None:
    _fieldnames, rows = _read_csv(ENTRIES_CSV)
    jsonl_count = len(_load_jsonl(ENTRIES))
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))

    assert len(rows) == jsonl_count
    assert len(rows) == datapackage["stats"]["record_count"]


def test_sources_csv_row_count_matches_jsonl_and_datapackage() -> None:
    _fieldnames, rows = _read_csv(SOURCES_CSV)
    jsonl_count = len(_load_jsonl(SOURCES))
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))

    assert len(rows) == jsonl_count
    assert len(rows) == datapackage["stats"]["source_record_count"]


REQUIRED_ENTRY_COLUMNS = {
    "entry_id",
    "source_id",
    "title",
    "document_type",
    "languages",
    "script",
    "file_local_path",
    "file_sha256",
    "file_bytes",
    "rights_basis",
    "license_expression",
    "commercial_use_allowed",
    "derivatives_allowed",
    "scan_redistribution_allowed",
    "attribution_required",
    "attribution_text",
    "attribution_url",
    "rights_verification_status",
    "rights_evidence_text",
    "rights_verified_at",
    "provenance_acquired_at",
    "holding_institution",
    "holding_shelfmark",
    "transcription_status",
    "transcription_rights_basis",
    "transcription_rights_verification_status",
}

REQUIRED_SOURCE_COLUMNS = {
    "source_id",
    "record_type",
    "status",
    "priority",
    "provider",
    "title",
    "urls_canonical",
    "rights_basis",
    "license_expression",
    "rights_verification_status",
    "scope_expected_handwriting",
    "ingest_method",
    "evidence_count",
}


def test_entries_csv_has_required_columns() -> None:
    fieldnames, _rows = _read_csv(ENTRIES_CSV)
    missing = REQUIRED_ENTRY_COLUMNS - set(fieldnames)
    assert not missing, f"entries.csv missing columns: {sorted(missing)}"


def test_sources_csv_has_required_columns() -> None:
    fieldnames, _rows = _read_csv(SOURCES_CSV)
    missing = REQUIRED_SOURCE_COLUMNS - set(fieldnames)
    assert not missing, f"sources.csv missing columns: {sorted(missing)}"


def test_entries_csv_preserves_entry_ids_and_rights() -> None:
    _fieldnames, rows = _read_csv(ENTRIES_CSV)
    by_id = {row["entry_id"]: row for row in rows}

    for entry in _load_jsonl(ENTRIES):
        row = by_id[entry["entry_id"]]
        assert row["source_id"] == entry["source_id"]
        assert row["title"] == entry["title"]
        assert row["license_expression"] == (
            entry["rights"]["license_expression"] or ""
        )
        # attribution_required serialises as "true"/"false"/"" depending on
        # whether the underlying JSON has a boolean or null. Match that.
        expected = entry["rights"]["attribution_required"]
        if expected is None:
            assert row["attribution_required"] == ""
        else:
            assert row["attribution_required"] == ("true" if expected else "false")


def test_parquet_opens_and_matches_csv_shape(tmp_path: Path) -> None:
    # Smoke test: write parquet to tmp_path, read it back with pyarrow, and
    # assert the schema and row count line up with the CSV. The parquet file
    # is a build artefact (lives under dist/, not committed) so we exercise
    # it through a fresh generation rather than reading a committed copy.
    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    entries_parquet = tmp_path / "entries.parquet"
    result = _run_builder(
        cwd=tmp_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        entries_parquet=entries_parquet,
    )
    assert result.returncode == 0, result.stderr

    table = pq.read_table(entries_parquet)
    csv_fieldnames, csv_rows = _read_csv(entries_csv)

    assert table.num_rows == len(csv_rows)
    assert table.column_names == csv_fieldnames

    schema = table.schema
    assert not schema.field("entry_id").nullable
    assert not schema.field("source_id").nullable
    # Booleans round-trip as proper Arrow booleans, not strings — that is the
    # core reason for shipping Parquet alongside CSV in the first place.
    import pyarrow as pa
    assert schema.field("attribution_required").type == pa.bool_()
    assert schema.field("file_bytes").type == pa.int64()


def test_parquet_attribution_flag_matches_jsonl(tmp_path: Path) -> None:
    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    entries_parquet = tmp_path / "entries.parquet"
    result = _run_builder(
        cwd=tmp_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        entries_parquet=entries_parquet,
    )
    assert result.returncode == 0, result.stderr

    table = pq.read_table(entries_parquet)
    parquet_flag_by_id = dict(
        zip(table.column("entry_id").to_pylist(),
            table.column("attribution_required").to_pylist())
    )
    for entry in _load_jsonl(ENTRIES):
        assert parquet_flag_by_id[entry["entry_id"]] == entry["rights"][
            "attribution_required"
        ]


def test_check_mode_passes_when_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_check_mode_fails_when_csv_stale(tmp_path: Path) -> None:
    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    entries_parquet = tmp_path / "entries.parquet"
    shutil.copyfile(ENTRIES_CSV, entries_csv)
    shutil.copyfile(SOURCES_CSV, sources_csv)
    entries_csv.write_text("entry_id\nbogus\n", encoding="utf-8")

    result = _run_builder(
        cwd=tmp_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        entries_parquet=entries_parquet,
        extra_args=("--check",),
    )
    assert result.returncode == 1
    assert "stale" in result.stderr
    assert "entries.csv" in result.stderr


def test_csv_handles_unicode_holding_institution() -> None:
    # Several entries carry institutions with non-ASCII characters (Hebrew
    # acronyms, French accents). Make sure the round-trip preserves them.
    _fieldnames, rows = _read_csv(ENTRIES_CSV)
    institutions = {row["holding_institution"] for row in rows if row["holding_institution"]}
    assert "Bibliothèque nationale de France" in institutions
    assert "Österreichische Nationalbibliothek" in institutions


def test_join_list_rejects_separator_collision() -> None:
    try:
        _bx._join_list(["safe", "has; injection"], field="languages", row_id="row")
    except SystemExit as exc:
        assert "list separator" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit on separator collision")


def test_builder_rejects_multi_file_entry(tmp_path: Path) -> None:
    # If we ever start ingesting entries with multiple files, the flat-CSV
    # assumption breaks. The builder should fail loudly rather than silently
    # dropping rows or dropping columns. Synthesise a multi-file entry by
    # duplicating the files[] member of one entry and confirm the error path.
    entries = _load_jsonl(ENTRIES)
    target = json.loads(json.dumps(entries[0]))  # deep-copy
    target["files"].append(target["files"][0])
    rest = entries[1:]

    entries_copy = tmp_path / "entries.jsonl"
    entries_copy.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in [target] + rest) + "\n",
        encoding="utf-8",
    )

    result = _run_builder(
        cwd=tmp_path,
        entries=entries_copy,
        entries_csv=tmp_path / "entries.csv",
        sources_csv=tmp_path / "sources.csv",
        entries_parquet=tmp_path / "entries.parquet",
    )
    assert result.returncode != 0
    assert "Multi-file" in result.stderr or "files" in result.stderr


def test_entries_csv_uses_lf_line_endings() -> None:
    # Default csv.writer dialects use CRLF, which would diff differently on
    # Windows checkouts and break determinism. We explicitly pick the unix
    # dialect — verify the on-disk bytes confirm that.
    blob = ENTRIES_CSV.read_bytes()
    assert b"\r\n" not in blob, "entries.csv must use LF line endings, not CRLF"
    assert blob.endswith(b"\n")
