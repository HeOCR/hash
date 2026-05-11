from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate_indexes.py"
SOURCES = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES = REPO_ROOT / "data" / "index" / "entries.jsonl"


def run_validator(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *(str(arg) for arg in args)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _first_entry_with_real_file() -> dict:
    for line in ENTRIES.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["files"] and entry["files"][0]["local_path"] is not None:
            return entry
    raise RuntimeError("no entry has a non-null files[0].local_path")


def test_current_indexes_validate() -> None:
    result = run_validator()

    assert result.returncode == 0, result.stderr
    assert "ok:" in result.stdout


def test_schema_errors_are_rejected(tmp_path: Path) -> None:
    row = json.loads(SOURCES.read_text(encoding="utf-8").splitlines()[0])
    row["status"] = "garbage"
    row["urls"]["canonical"] = "not a url"
    row["rights"]["commercial_use_allowed"] = "yes"

    bad_sources = tmp_path / "sources.jsonl"
    bad_sources.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", bad_sources, "--entries", ENTRIES)

    assert result.returncode != 0
    assert "is not one of" in result.stderr or "is not of type" in result.stderr


def test_unverified_entry_cannot_claim_positive_permissions(tmp_path: Path) -> None:
    entry = _first_entry_with_real_file()
    entry["rights"]["verification_status"] = "source_note_only"
    entry["rights"]["commercial_use_allowed"] = True

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "should not be valid" in result.stderr


def test_unverified_transcription_cannot_claim_positive_permissions(tmp_path: Path) -> None:
    source_id = json.loads(SOURCES.read_text(encoding="utf-8").splitlines()[0])[
        "source_id"
    ]
    entry = json.loads(ENTRIES.read_text(encoding="utf-8").splitlines()[0])
    entry["entry_id"] = f"{source_id}__p0001"
    entry["source_id"] = source_id
    entry["transcription"] = {
        "status": "raw",
        "text_path": "data/transcriptions/example/plain.txt",
        "alto_path": None,
        "hocr_path": None,
        "source_url": "https://example.org/transcript.txt",
        "created_by": "provider",
        "rights": {
            "rights_basis": "public_domain",
            "license_expression": "PDM-1.0",
            "commercial_use_allowed": True,
            "derivatives_allowed": None,
            "redistribution_allowed": None,
            "attribution_required": None,
            "verification_status": "source_note_only",
            "evidence_text": None,
            "verified_at": None,
        },
    }

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "should not be valid" in result.stderr


def test_missing_index_file_is_rejected(tmp_path: Path) -> None:
    result = run_validator("--sources", tmp_path / "missing.jsonl", "--entries", ENTRIES)

    assert result.returncode != 0
    assert "file does not exist" in result.stderr


def test_missing_local_path_is_rejected(tmp_path: Path) -> None:
    entry = _first_entry_with_real_file()
    entry["files"][0]["local_path"] = "data/scans/does_not_exist/missing__p0001.jpg"

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "file does not exist" in result.stderr
    assert entry["entry_id"] in result.stderr


def test_byte_size_mismatch_is_rejected(tmp_path: Path) -> None:
    entry = _first_entry_with_real_file()
    real_bytes = entry["files"][0]["bytes"]
    corrupted_bytes = real_bytes + 1
    entry["files"][0]["bytes"] = corrupted_bytes

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "byte size mismatch" in result.stderr
    assert entry["entry_id"] in result.stderr
    assert f"expected {corrupted_bytes}" in result.stderr
    assert f"got {real_bytes}" in result.stderr


def test_sha256_mismatch_is_rejected(tmp_path: Path) -> None:
    entry = _first_entry_with_real_file()
    real_sha = entry["files"][0]["sha256"]
    corrupted_sha = "0" * 64
    entry["files"][0]["sha256"] = corrupted_sha

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr
    assert entry["entry_id"] in result.stderr
    assert f"expected {corrupted_sha}" in result.stderr
    assert f"got {real_sha}" in result.stderr


def test_absolute_local_path_is_rejected(tmp_path: Path) -> None:
    entry = _first_entry_with_real_file()
    entry["files"][0]["local_path"] = "/etc/hosts"

    bad_entries = tmp_path / "entries.jsonl"
    bad_entries.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = run_validator("--sources", SOURCES, "--entries", bad_entries)

    assert result.returncode != 0
    assert "must be repo-relative" in result.stderr
    assert entry["entry_id"] in result.stderr


def _cc_by_sa_source_and_entry() -> tuple[dict, dict]:
    source = json.loads(SOURCES.read_text(encoding="utf-8").splitlines()[-1])
    source["source_id"] = "example__cc_by_sa_attribution"
    source["status"] = "verified"
    source["rights"] = {
        "rights_basis": "cc_by_sa",
        "license_expression": "CC-BY-SA-4.0",
        "commercial_use_allowed": True,
        "derivatives_allowed": True,
        "scan_redistribution_allowed": True,
        "attribution_required": True,
        "evidence_text": "File page declares CC BY-SA 4.0.",
        "terms_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "verification_status": "primary_page_checked",
        "verified_at": "2026-05-09",
    }

    entry = json.loads(ENTRIES.read_text(encoding="utf-8").splitlines()[0])
    entry["entry_id"] = f"{source['source_id']}__p0001"
    entry["source_id"] = source["source_id"]
    entry["rights"] = {
        "rights_basis": "cc_by_sa",
        "license_expression": "CC-BY-SA-4.0",
        "commercial_use_allowed": True,
        "derivatives_allowed": True,
        "scan_redistribution_allowed": True,
        "attribution_required": True,
        "attribution_text": "User:Example via Wikimedia Commons, CC BY-SA 4.0",
        "attribution_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "verification_status": "primary_page_checked",
        "evidence_text": "File page declares CC BY-SA 4.0.",
        "verified_at": "2026-05-09",
    }
    return source, entry


def _write_and_run(tmp_path: Path, source: dict, entry: dict) -> subprocess.CompletedProcess[str]:
    sources_path = tmp_path / "sources.jsonl"
    sources_path.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    entries_path = tmp_path / "entries.jsonl"
    entries_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    return run_validator("--sources", sources_path, "--entries", entries_path)


def test_attribution_required_with_text_is_accepted(tmp_path: Path) -> None:
    source, entry = _cc_by_sa_source_and_entry()

    result = _write_and_run(tmp_path, source, entry)

    assert result.returncode == 0, result.stderr
    assert "ok: 1 sources, 1 entries" in result.stdout


def test_attribution_required_without_text_is_rejected(tmp_path: Path) -> None:
    source, entry = _cc_by_sa_source_and_entry()
    entry["rights"]["attribution_text"] = None

    result = _write_and_run(tmp_path, source, entry)

    assert result.returncode != 0
    assert "attribution_text" in result.stderr


def test_attribution_required_with_blank_text_is_rejected(tmp_path: Path) -> None:
    # A single space passes the schema's `minLength: 1` and `type: string`
    # but is rejected by the validator-level check — proving the second
    # enforcement layer catches what the schema does not.
    source, entry = _cc_by_sa_source_and_entry()
    entry["rights"]["attribution_text"] = "   "

    result = _write_and_run(tmp_path, source, entry)

    assert result.returncode != 0
    assert entry["entry_id"] in result.stderr
    assert "attribution_text is null, blank, or whitespace-only" in result.stderr


def test_attribution_required_without_url_is_rejected(tmp_path: Path) -> None:
    source, entry = _cc_by_sa_source_and_entry()
    entry["rights"]["attribution_url"] = None

    result = _write_and_run(tmp_path, source, entry)

    assert result.returncode != 0
    assert "attribution_url" in result.stderr


def test_attribution_required_entries_round_trip_to_notice() -> None:
    entries = [
        json.loads(line)
        for line in ENTRIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    required = [e for e in entries if e["rights"].get("attribution_required") is True]

    assert required, "expected at least one attribution-required entry in the corpus"
    for entry in required:
        text = entry["rights"]["attribution_text"]
        url = entry["rights"]["attribution_url"]
        assert isinstance(text, str) and text.strip(), (
            f"{entry['entry_id']}: attribution_text must be a non-blank string"
        )
        assert isinstance(url, str) and url.startswith("https://"), (
            f"{entry['entry_id']}: attribution_url must be an https URI"
        )
        notice = f"Includes work by {text} <{url}>"
        assert text in notice and url in notice
