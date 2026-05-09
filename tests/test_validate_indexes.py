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
    source_id = json.loads(SOURCES.read_text(encoding="utf-8").splitlines()[0])[
        "source_id"
    ]
    entry = {
        "entry_id": f"{source_id}__p0001",
        "source_id": source_id,
        "source_record_id": None,
        "sequence": {
            "index": 1,
            "label": "1",
            "physical_unit_count": 1,
        },
        "title": "Example page",
        "creators": [],
        "dates": {
            "created": None,
            "created_precision": "unknown",
            "accessed_at": None,
        },
        "languages": ["he"],
        "script": ["Hebr"],
        "document_type": "diary",
        "handwriting": {
            "extent": "unknown",
            "hebrew_extent": "unknown",
            "notes": None,
        },
        "files": [
            {
                "role": "original",
                "local_path": None,
                "source_url": None,
                "provider_file_id": None,
                "sha256": None,
                "mime_type": None,
                "bytes": None,
                "width_px": None,
                "height_px": None,
            }
        ],
        "rights": {
            "rights_basis": "public_domain",
            "license_expression": "LicenseRef-Public-Domain-Israel",
            "commercial_use_allowed": True,
            "derivatives_allowed": None,
            "scan_redistribution_allowed": None,
            "attribution_required": None,
            "verification_status": "source_note_only",
            "evidence_text": None,
            "verified_at": None,
        },
        "provenance": {
            "acquired_at": None,
            "acquired_by": None,
            "source_landing_url": None,
            "notes": None,
        },
        "quality": {
            "usable_for_htr": None,
            "legibility": "unknown",
            "exclusion_reasons": [],
            "notes": None,
        },
        "transcription": {
            "status": "none",
            "text_path": None,
            "alto_path": None,
            "hocr_path": None,
            "source_url": None,
            "created_by": "unknown",
            "rights": {
                "rights_basis": "unknown",
                "license_expression": None,
                "commercial_use_allowed": None,
                "derivatives_allowed": None,
                "redistribution_allowed": None,
                "attribution_required": None,
                "verification_status": "unverified",
                "evidence_text": None,
                "verified_at": None,
            },
        },
    }
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
