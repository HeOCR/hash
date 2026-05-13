from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest


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
CREATORS_CSV = REPO_ROOT / "exports" / "creators.csv"


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
    creators_csv: Path,
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
            "--creators-csv", str(creators_csv),
            "--entries-parquet", str(entries_parquet),
            *extra_args,
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="session")
def fresh_build(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Generate a full set of exports once per test session.

    Lots of tests inspect the byte-output of a fresh build (against tmp paths,
    not the committed copies); doing this once and sharing the result keeps
    the test suite ~5× faster than re-running the subprocess per test.
    """
    tmp_path = tmp_path_factory.mktemp("build_exports")
    paths = {
        "entries_csv": tmp_path / "entries.csv",
        "sources_csv": tmp_path / "sources.csv",
        "creators_csv": tmp_path / "creators.csv",
        "entries_parquet": tmp_path / "entries.parquet",
    }
    result = _run_builder(cwd=tmp_path, **paths)
    assert result.returncode == 0, result.stderr
    return paths


def test_committed_csvs_are_up_to_date(fresh_build: dict[str, Path]) -> None:
    # Pytest mirror of the CI `--check` step: catches "didn't regenerate
    # before committing". The CI workflow itself catches "regenerated locally
    # but didn't stage". Intentionally redundant.
    assert fresh_build["entries_csv"].read_bytes() == ENTRIES_CSV.read_bytes(), (
        "exports/entries.csv is stale; run `python3 scripts/build_exports.py`"
    )
    assert fresh_build["sources_csv"].read_bytes() == SOURCES_CSV.read_bytes(), (
        "exports/sources.csv is stale; run `python3 scripts/build_exports.py`"
    )
    assert fresh_build["creators_csv"].read_bytes() == CREATORS_CSV.read_bytes(), (
        "exports/creators.csv is stale; run `python3 scripts/build_exports.py`"
    )


def test_builder_is_idempotent(tmp_path: Path) -> None:
    paths = {
        "entries_csv": tmp_path / "entries.csv",
        "sources_csv": tmp_path / "sources.csv",
        "creators_csv": tmp_path / "creators.csv",
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


def test_creators_csv_row_count_matches_total_creators() -> None:
    _fieldnames, rows = _read_csv(CREATORS_CSV)
    expected = sum(len(entry.get("creators", [])) for entry in _load_jsonl(ENTRIES))
    assert len(rows) == expected


def test_entries_csv_column_set_is_authoritative() -> None:
    # The column list in build_exports.py is the contract; the on-disk CSV
    # must match it exactly. Adding a column without staging the CSV (or
    # vice versa) should fail this test.
    fieldnames, _rows = _read_csv(ENTRIES_CSV)
    expected = [name for name, _t in _bx.ENTRY_COLUMNS]
    assert fieldnames == expected


def test_sources_csv_column_set_is_authoritative() -> None:
    fieldnames, _rows = _read_csv(SOURCES_CSV)
    expected = [name for name, _t in _bx.SOURCE_COLUMNS]
    assert fieldnames == expected


def test_creators_csv_column_set_is_authoritative() -> None:
    fieldnames, _rows = _read_csv(CREATORS_CSV)
    expected = [name for name, _t in _bx.CREATOR_COLUMNS]
    assert fieldnames == expected


def test_entries_csv_dropped_parallel_creator_columns() -> None:
    # Earlier iterations of the exporter emitted `creator_names`,
    # `creator_roles`, `creator_death_years` as "; "-joined parallel arrays.
    # That was lossy (null middle entries lost positional alignment) and
    # has been replaced by exports/creators.csv. Make sure nobody
    # accidentally re-introduces those columns.
    fieldnames, _rows = _read_csv(ENTRIES_CSV)
    assert "creator_names" not in fieldnames
    assert "creator_roles" not in fieldnames
    assert "creator_death_years" not in fieldnames
    assert "creator_count" in fieldnames


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


def test_creators_csv_preserves_every_creator() -> None:
    _fieldnames, rows = _read_csv(CREATORS_CSV)
    by_entry: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_entry.setdefault(row["entry_id"], []).append(row)

    for entry in _load_jsonl(ENTRIES):
        actual = by_entry.get(entry["entry_id"], [])
        expected = entry.get("creators", [])
        assert len(actual) == len(expected), (
            f"creator-count mismatch for {entry['entry_id']}: "
            f"{len(actual)} vs {len(expected)}"
        )
        # Position ordering must match the JSONL.
        for position, creator in enumerate(expected):
            row = actual[position]
            assert int(row["position"]) == position
            assert row["name"] == creator["name"]
            assert row["role"] == creator["role"]
            if creator.get("death_year") is None:
                assert row["death_year"] == ""
            else:
                assert int(row["death_year"]) == creator["death_year"]


def test_parquet_opens_and_matches_csv_shape(fresh_build: dict[str, Path]) -> None:
    table = pq.read_table(fresh_build["entries_parquet"])
    csv_fieldnames, csv_rows = _read_csv(fresh_build["entries_csv"])

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


def test_parquet_attribution_flag_matches_jsonl(
    fresh_build: dict[str, Path],
) -> None:
    table = pq.read_table(fresh_build["entries_parquet"])
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
    creators_csv = tmp_path / "creators.csv"
    entries_parquet = tmp_path / "entries.parquet"
    shutil.copyfile(ENTRIES_CSV, entries_csv)
    shutil.copyfile(SOURCES_CSV, sources_csv)
    shutil.copyfile(CREATORS_CSV, creators_csv)
    entries_csv.write_text("entry_id\nbogus\n", encoding="utf-8")

    result = _run_builder(
        cwd=tmp_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        creators_csv=creators_csv,
        entries_parquet=entries_parquet,
        extra_args=("--check",),
    )
    assert result.returncode == 1
    assert "stale" in result.stderr
    assert "entries.csv" in result.stderr


def test_csv_unicode_round_trips_through_synthetic_fixture(tmp_path: Path) -> None:
    # Decouple unicode coverage from corpus contents: synthesise an entry
    # with non-ASCII glyphs across Latin, Hebrew, and CJK ranges, run the
    # exporter, and verify the bytes survive both CSV and Parquet writes.
    base_entry = _load_jsonl(ENTRIES)[0]
    spiked = json.loads(json.dumps(base_entry))  # deep-copy
    spiked["entry_id"] = "synthetic__unicode__p0001"
    spiked["source_id"] = "synthetic__unicode"
    spiked["title"] = "Café Österreich שלום 中文"
    spiked["holding_institution"] = "Bibliothèque — אוניברסיטה — 大学"
    spiked["provenance"]["notes"] = "naïve façade — שלום עולם — 你好世界"

    base_source = _load_jsonl(SOURCES)[0]
    paired_source = json.loads(json.dumps(base_source))
    paired_source["source_id"] = "synthetic__unicode"

    entries_path = tmp_path / "entries.jsonl"
    sources_path = tmp_path / "sources.jsonl"
    entries_path.write_text(
        json.dumps(spiked, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    sources_path.write_text(
        json.dumps(paired_source, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    creators_csv = tmp_path / "creators.csv"
    entries_parquet = tmp_path / "entries.parquet"
    result = _run_builder(
        cwd=tmp_path,
        sources=sources_path,
        entries=entries_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        creators_csv=creators_csv,
        entries_parquet=entries_parquet,
    )
    assert result.returncode == 0, result.stderr

    csv_text = entries_csv.read_text(encoding="utf-8")
    for needle in ("Café Österreich שלום 中文", "Bibliothèque — אוניברסיטה — 大学"):
        assert needle in csv_text, f"missing {needle!r} from entries.csv"

    table = pq.read_table(entries_parquet)
    titles = table.column("title").to_pylist()
    assert "Café Österreich שלום 中文" in titles


def test_join_list_rejects_separator_collision() -> None:
    with pytest.raises(ValueError, match="list separator"):
        _bx._join_list(["safe", "has; injection"], field="languages")


def test_builder_picks_original_among_multiple_roles(tmp_path: Path) -> None:
    # The schema permits multiple `files[]` per entry, discriminated by
    # `role`. The flat CSV picks the canonical `original`. Synthesise an
    # entry with an extra `thumbnail` and confirm the export picks the
    # original (not the first file) and reports the total count.
    entries = _load_jsonl(ENTRIES)
    target = json.loads(json.dumps(entries[0]))
    target["entry_id"] = "synthetic__multi_role__p0001"
    target["source_id"] = "synthetic__multi_role"
    original = json.loads(json.dumps(target["files"][0]))
    thumbnail = json.loads(json.dumps(original))
    thumbnail["role"] = "thumbnail"
    thumbnail["local_path"] = None
    thumbnail["sha256"] = None
    thumbnail["bytes"] = None
    thumbnail["width_px"] = 64
    thumbnail["height_px"] = 64
    # Put the thumbnail first to confirm we don't naively flatten files[0].
    target["files"] = [thumbnail, original]

    paired_source = json.loads(json.dumps(_load_jsonl(SOURCES)[0]))
    paired_source["source_id"] = "synthetic__multi_role"

    entries_path = tmp_path / "entries.jsonl"
    sources_path = tmp_path / "sources.jsonl"
    entries_path.write_text(
        json.dumps(target, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    sources_path.write_text(
        json.dumps(paired_source, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    entries_csv = tmp_path / "entries.csv"
    sources_csv = tmp_path / "sources.csv"
    creators_csv = tmp_path / "creators.csv"
    entries_parquet = tmp_path / "entries.parquet"
    result = _run_builder(
        cwd=tmp_path,
        sources=sources_path,
        entries=entries_path,
        entries_csv=entries_csv,
        sources_csv=sources_csv,
        creators_csv=creators_csv,
        entries_parquet=entries_parquet,
    )
    assert result.returncode == 0, result.stderr

    _fieldnames, rows = _read_csv(entries_csv)
    assert len(rows) == 1
    row = rows[0]
    assert row["file_role"] == "original"
    assert row["file_count"] == "2"
    assert row["file_sha256"] == original["sha256"]


def test_builder_rejects_entry_without_original(tmp_path: Path) -> None:
    # Inverse of the multi-role case: zero `original` files should abort,
    # not silently pick a non-original.
    entries = _load_jsonl(ENTRIES)
    target = json.loads(json.dumps(entries[0]))
    target["entry_id"] = "synthetic__no_original__p0001"
    target["source_id"] = "synthetic__no_original"
    target["files"] = [{**target["files"][0], "role": "thumbnail"}]

    paired_source = json.loads(json.dumps(_load_jsonl(SOURCES)[0]))
    paired_source["source_id"] = "synthetic__no_original"

    entries_path = tmp_path / "entries.jsonl"
    sources_path = tmp_path / "sources.jsonl"
    entries_path.write_text(
        json.dumps(target, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    sources_path.write_text(
        json.dumps(paired_source, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = _run_builder(
        cwd=tmp_path,
        sources=sources_path,
        entries=entries_path,
        entries_csv=tmp_path / "entries.csv",
        sources_csv=tmp_path / "sources.csv",
        creators_csv=tmp_path / "creators.csv",
        entries_parquet=tmp_path / "entries.parquet",
    )
    assert result.returncode != 0
    assert "original" in result.stderr


def test_entries_csv_uses_lf_line_endings() -> None:
    # Default csv.writer dialects use CRLF, which would diff differently on
    # Windows checkouts and break determinism. We explicitly pick the unix
    # dialect — verify the on-disk bytes confirm that.
    blob = ENTRIES_CSV.read_bytes()
    assert b"\r\n" not in blob, "entries.csv must use LF line endings, not CRLF"
    assert blob.endswith(b"\n")
