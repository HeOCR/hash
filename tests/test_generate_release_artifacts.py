from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_release_artifacts.py"
RECIPE = REPO_ROOT / "scripts" / "release_recipe.json"
SOURCES = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES = REPO_ROOT / "data" / "index" / "entries.jsonl"
NOTICE = REPO_ROOT / "NOTICE.md"
CITATION = REPO_ROOT / "CITATION.cff"
DATAPACKAGE = REPO_ROOT / "datapackage.json"


def _load_entries() -> list[dict]:
    return [
        json.loads(line)
        for line in ENTRIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_sources() -> list[dict]:
    return [
        json.loads(line)
        for line in SOURCES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _run_generator(
    workdir: Path,
    *,
    notice: Path,
    citation: Path,
    datapackage: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--sources", str(SOURCES),
            "--entries", str(ENTRIES),
            "--recipe", str(RECIPE),
            "--notice", str(notice),
            "--citation", str(citation),
            "--datapackage", str(datapackage),
        ],
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )


def test_committed_artifacts_are_up_to_date(tmp_path: Path) -> None:
    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"

    result = _run_generator(tmp_path, notice=notice, citation=citation, datapackage=datapackage)
    assert result.returncode == 0, result.stderr

    assert notice.read_bytes() == NOTICE.read_bytes(), (
        "NOTICE.md is stale; run `python3 scripts/generate_release_artifacts.py`"
    )
    assert citation.read_bytes() == CITATION.read_bytes(), (
        "CITATION.cff is stale; run `python3 scripts/generate_release_artifacts.py`"
    )
    assert datapackage.read_bytes() == DATAPACKAGE.read_bytes(), (
        "datapackage.json is stale; run `python3 scripts/generate_release_artifacts.py`"
    )


def test_generator_is_idempotent(tmp_path: Path) -> None:
    paths = {
        "notice": tmp_path / "NOTICE.md",
        "citation": tmp_path / "CITATION.cff",
        "datapackage": tmp_path / "datapackage.json",
    }

    first = _run_generator(tmp_path, **paths)
    assert first.returncode == 0, first.stderr
    snapshot = {name: path.read_bytes() for name, path in paths.items()}

    second = _run_generator(tmp_path, **paths)
    assert second.returncode == 0, second.stderr
    for name, path in paths.items():
        assert path.read_bytes() == snapshot[name], f"{name} differed between runs"


def test_datapackage_counts_match_index() -> None:
    entries = _load_entries()
    sources = _load_sources()
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))

    assert package["stats"]["record_count"] == len(entries)
    assert package["stats"]["source_record_count"] == len(sources)
    assert package["stats"]["source_count"] == len({e["source_id"] for e in entries})

    breakdown = package["stats"]["license_breakdown"]
    assert sum(breakdown.values()) == len(entries)

    expected_counts: dict[str, int] = {}
    for entry in entries:
        license_id = entry["rights"]["license_expression"]
        expected_counts[license_id] = expected_counts.get(license_id, 0) + 1
    assert breakdown == expected_counts


def test_datapackage_keys_are_sorted() -> None:
    # sort_keys=True is the determinism contract; assert it from the bytes.
    raw = DATAPACKAGE.read_text(encoding="utf-8")
    package = json.loads(raw)
    assert list(package.keys()) == sorted(package.keys())
    assert list(package["stats"]["license_breakdown"].keys()) == sorted(
        package["stats"]["license_breakdown"].keys()
    )


def test_datapackage_resource_record_counts_match() -> None:
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    by_name = {resource["name"]: resource for resource in package["resources"]}

    assert by_name["entries"]["record_count"] == len(_load_entries())
    assert by_name["sources"]["record_count"] == len(_load_sources())


def test_institution_breakdown_uses_verbatim_strings() -> None:
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    breakdown = package["stats"]["institution_breakdown"]

    entries = _load_entries()
    expected: dict[str, int] = {}
    for entry in entries:
        institution = entry.get("holding_institution")
        if institution:
            expected[institution] = expected.get(institution, 0) + 1
    assert breakdown == expected


def test_notice_has_stanza_per_attribution_required_entry() -> None:
    text = NOTICE.read_text(encoding="utf-8")
    entries = _load_entries()
    required = [e for e in entries if e["rights"].get("attribution_required") is True]
    assert required, "expected at least one attribution-required entry in the corpus"

    for entry in required:
        assert entry["entry_id"] in text, (
            f"NOTICE.md missing entry_id for {entry['entry_id']}"
        )
        assert entry["title"] in text, (
            f"NOTICE.md missing title for {entry['entry_id']}"
        )
        assert entry["rights"]["attribution_text"] in text, (
            f"NOTICE.md missing attribution_text for {entry['entry_id']}"
        )
        assert entry["rights"]["attribution_url"] in text, (
            f"NOTICE.md missing attribution_url for {entry['entry_id']}"
        )


def test_notice_lists_no_non_attribution_entries() -> None:
    # Only the two CC-BY-SA entries should have ### stanzas. Other entry IDs must
    # not appear in NOTICE.md — that would over-credit public-domain works.
    text = NOTICE.read_text(encoding="utf-8")
    entries = _load_entries()
    for entry in entries:
        if not entry["rights"].get("attribution_required"):
            assert entry["entry_id"] not in text, (
                f"NOTICE.md unexpectedly lists non-attribution entry {entry['entry_id']}"
            )


def test_citation_is_cff_1_2_0() -> None:
    text = CITATION.read_text(encoding="utf-8")
    assert "cff-version: 1.2.0" in text
    assert "type: dataset" in text
    assert 'license: "CC0-1.0"' in text
    assert 'version: "0.1.0-rc"' in text


def test_citation_date_released_matches_max_acquired_at() -> None:
    entries = _load_entries()
    max_acquired = max(
        e["provenance"]["acquired_at"]
        for e in entries
        if e["provenance"].get("acquired_at")
    )
    text = CITATION.read_text(encoding="utf-8")
    assert f'date-released: "{max_acquired[:10]}"' in text


def test_released_at_matches_max_acquired_at() -> None:
    entries = _load_entries()
    max_acquired = max(
        e["provenance"]["acquired_at"]
        for e in entries
        if e["provenance"].get("acquired_at")
    )
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    assert package["released_at"] == max_acquired


def test_generator_survives_relocated_indexes(tmp_path: Path) -> None:
    # Confirm the script is parameterised end-to-end: pass non-default paths and
    # check the outputs land where requested. Guards against accidental REPO_ROOT
    # hardcoding inside the build_* helpers.
    sources_copy = tmp_path / "sources.jsonl"
    entries_copy = tmp_path / "entries.jsonl"
    shutil.copyfile(SOURCES, sources_copy)
    shutil.copyfile(ENTRIES, entries_copy)

    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"

    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--sources", str(sources_copy),
            "--entries", str(entries_copy),
            "--recipe", str(RECIPE),
            "--notice", str(notice),
            "--citation", str(citation),
            "--datapackage", str(datapackage),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert notice.exists()
    assert citation.exists()
    assert datapackage.exists()
