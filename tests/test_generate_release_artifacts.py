from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from frictionless import Package


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
    *,
    cwd: Path,
    sources: Path = SOURCES,
    entries: Path = ENTRIES,
    notice: Path,
    citation: Path,
    datapackage: Path,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--sources", str(sources),
            "--entries", str(entries),
            "--recipe", str(RECIPE),
            "--notice", str(notice),
            "--citation", str(citation),
            "--datapackage", str(datapackage),
            *extra_args,
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_committed_artifacts_are_up_to_date(tmp_path: Path) -> None:
    # Pytest mirror of the CI `--check` step: catches the local "didn't
    # regenerate before committing" mode while the CI workflow catches
    # "regenerated locally but didn't stage". Intentionally redundant.
    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"

    result = _run_generator(cwd=tmp_path, notice=notice, citation=citation, datapackage=datapackage)
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

    first = _run_generator(cwd=tmp_path, **paths)
    assert first.returncode == 0, first.stderr
    snapshot = {name: path.read_bytes() for name, path in paths.items()}

    second = _run_generator(cwd=tmp_path, **paths)
    assert second.returncode == 0, second.stderr
    for name, path in paths.items():
        assert path.read_bytes() == snapshot[name], f"{name} differed between runs"


def test_datapackage_counts_match_index() -> None:
    entries = _load_entries()
    sources = _load_sources()
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))

    assert package["stats"]["record_count"] == len(entries)
    assert package["stats"]["source_record_count"] == len(sources)
    assert package["stats"]["entry_source_count"] == len({e["source_id"] for e in entries})

    breakdown = package["stats"]["license_breakdown"]
    assert sum(breakdown.values()) == len(entries)

    expected_counts: dict[str, int] = {}
    for entry in entries:
        license_id = entry["rights"]["license_expression"]
        expected_counts[license_id] = expected_counts.get(license_id, 0) + 1
    assert breakdown == expected_counts


def test_datapackage_keys_are_sorted() -> None:
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
    text = NOTICE.read_text(encoding="utf-8")
    entries = _load_entries()
    for entry in entries:
        if not entry["rights"].get("attribution_required"):
            assert entry["entry_id"] not in text, (
                f"NOTICE.md unexpectedly lists non-attribution entry {entry['entry_id']}"
            )


def test_citation_parses_and_has_required_cff_keys() -> None:
    # Round-trip through a real YAML parser — the whole point of CITATION.cff is
    # that downstream tools (Zenodo, GitHub) can read it. Hand-rolled YAML would
    # not survive this assertion.
    document = yaml.safe_load(CITATION.read_text(encoding="utf-8"))
    assert isinstance(document, dict)

    for required in ("cff-version", "type", "title", "authors", "version", "date-released"):
        assert required in document, f"CITATION.cff missing required key: {required}"

    assert document["cff-version"] == "1.2.0"
    assert document["type"] == "dataset"
    assert document["license"] == "CC0-1.0"
    assert document["version"] == "0.1.0-rc"
    assert isinstance(document["authors"], list) and document["authors"]
    for author in document["authors"]:
        assert "name" in author


def test_datapackage_validates_against_frictionless_spec() -> None:
    # Round-trip the committed manifest through the Frictionless library and
    # assert it loads cleanly with no metadata errors. Symmetric to the CFF
    # round-trip test: the whole point of using a published spec is that
    # downstream tooling can parse it.
    package = Package(str(DATAPACKAGE))
    assert package.name == "public-domain-hand-written-hebrew-scans"
    assert package.version == "0.1.0-rc"

    errors = list(Package.metadata_validate(package.to_descriptor()))
    assert errors == [], [getattr(e, "message", str(e)) for e in errors]


def test_citation_date_released_matches_max_acquired_at() -> None:
    entries = _load_entries()
    max_acquired = max(
        e["provenance"]["acquired_at"]
        for e in entries
        if e["provenance"].get("acquired_at")
    )
    document = yaml.safe_load(CITATION.read_text(encoding="utf-8"))
    assert str(document["date-released"]) == max_acquired[:10]


def test_released_at_matches_max_acquired_at() -> None:
    entries = _load_entries()
    max_acquired = max(
        e["provenance"]["acquired_at"]
        for e in entries
        if e["provenance"].get("acquired_at")
    )
    package = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    assert package["released_at"] == max_acquired


def test_generator_uses_cli_entries_for_resource_stats(tmp_path: Path) -> None:
    # Drop one entry, run the generator against the trimmed file, and verify
    # the manifest reflects the modified input — not the committed repo file.
    # This is the test that R2/R3 were missing.
    original_lines = ENTRIES.read_text(encoding="utf-8").splitlines()
    trimmed = [line for line in original_lines if line.strip()][:-1]
    entries_copy = tmp_path / "entries.jsonl"
    entries_copy.write_text("\n".join(trimmed) + "\n", encoding="utf-8")

    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"

    result = _run_generator(
        cwd=tmp_path,
        entries=entries_copy,
        notice=notice,
        citation=citation,
        datapackage=datapackage,
    )
    assert result.returncode == 0, result.stderr

    package = json.loads(datapackage.read_text(encoding="utf-8"))
    expected_record_count = len(trimmed)

    assert package["stats"]["record_count"] == expected_record_count
    assert sum(package["stats"]["license_breakdown"].values()) == expected_record_count

    by_name = {resource["name"]: resource for resource in package["resources"]}
    assert by_name["entries"]["record_count"] == expected_record_count
    assert by_name["entries"]["bytes"] == entries_copy.stat().st_size


def test_attribution_gate_is_license_driven(tmp_path: Path) -> None:
    # If we drove inclusion off the `attribution_required` flag alone, an
    # entry with a CC-BY-SA license but `attribution_required: false` would
    # silently disappear from NOTICE.md. Verify that the generator rejects
    # that configuration instead of producing a broken NOTICE.
    entries = _load_entries()
    target = next(
        e for e in entries
        if e["rights"]["license_expression"] == "CC-BY-SA-4.0"
    )
    target = json.loads(json.dumps(target))  # deep-copy
    target["rights"]["attribution_required"] = False

    rest = [
        e for e in entries
        if e["entry_id"] != target["entry_id"]
        and e["rights"]["license_expression"] != "CC-BY-SA-4.0"
    ]
    entries_copy = tmp_path / "entries.jsonl"
    entries_copy.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in rest + [target]) + "\n",
        encoding="utf-8",
    )

    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"

    result = _run_generator(
        cwd=tmp_path,
        entries=entries_copy,
        notice=notice,
        citation=citation,
        datapackage=datapackage,
    )
    assert result.returncode != 0
    assert "CC-BY-SA-4.0" in result.stderr
    assert "attribution_required" in result.stderr
    assert not notice.exists()


def test_check_mode_passes_when_up_to_date(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_check_mode_fails_when_stale(tmp_path: Path) -> None:
    # Copy current artefacts to tmp and corrupt one, then assert --check
    # exits non-zero and identifies it.
    notice = tmp_path / "NOTICE.md"
    citation = tmp_path / "CITATION.cff"
    datapackage = tmp_path / "datapackage.json"
    shutil.copyfile(NOTICE, notice)
    shutil.copyfile(CITATION, citation)
    shutil.copyfile(DATAPACKAGE, datapackage)
    datapackage.write_text("{}\n", encoding="utf-8")

    result = _run_generator(
        cwd=tmp_path,
        notice=notice,
        citation=citation,
        datapackage=datapackage,
        extra_args=("--check",),
    )
    assert result.returncode == 1
    assert "stale" in result.stderr
    assert "datapackage.json" in result.stderr


def test_recipe_required_fields_must_be_present(tmp_path: Path) -> None:
    # Tampered recipes with required fields removed should fail loudly,
    # not silently default. This guards R7 — no `.get(..., default)` on
    # required recipe keys.
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    del recipe["authors"]
    bad_recipe = tmp_path / "bad_recipe.json"
    bad_recipe.write_text(json.dumps(recipe), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, str(GENERATOR),
            "--recipe", str(bad_recipe),
            "--notice", str(tmp_path / "NOTICE.md"),
            "--citation", str(tmp_path / "CITATION.cff"),
            "--datapackage", str(tmp_path / "datapackage.json"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "authors" in result.stderr or "KeyError" in result.stderr
