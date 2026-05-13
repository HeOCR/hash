from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPO_ROOT / "scripts" / "update_readme_status.py"

_spec = importlib.util.spec_from_file_location("update_readme_status", UPDATER)
_upd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_upd)

DATAPACKAGE = REPO_ROOT / "datapackage.json"
README = REPO_ROOT / "README.md"
BEGIN_MARKER = "<!-- begin:status -->"
END_MARKER = "<!-- end:status -->"


def _extract_section(text: str) -> str:
    """Return the text between the status markers (exclusive, no surrounding newlines)."""
    begin_pos = text.index(BEGIN_MARKER) + len(BEGIN_MARKER) + 1  # skip trailing \n
    end_pos = text.index(END_MARKER) - 1  # skip leading \n before marker
    return text[begin_pos:end_pos]


def _make_datapackage(
    *,
    record_count: int = 10,
    entry_source_count: int = 5,
    scan_byte_count: int = 10_485_760,  # exactly 10.00 MiB
    candidate: int = 2,
    rejected: int = 1,
    license_breakdown: dict[str, int] | None = None,
    licenses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if license_breakdown is None:
        license_breakdown = {"PDM-1.0": record_count}
    if licenses is None:
        licenses = [{"name": "PDM-1.0", "title": "Public Domain Mark 1.0", "scope": "scans"}]
    return {
        "licenses": licenses,
        "stats": {
            "record_count": record_count,
            "entry_source_count": entry_source_count,
            "scan_byte_count": scan_byte_count,
            "source_status_breakdown": {
                "candidate": candidate,
                "rejected": rejected,
                "verified": entry_source_count,
            },
            "license_breakdown": license_breakdown,
        },
    }


def _corrupted_readme(tmp_path: Path) -> Path:
    """Copy README.md to tmp_path with the ingested-scan count corrupted."""
    stats = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))["stats"]
    original = README.read_text(encoding="utf-8")
    corrupted = original.replace(
        f"{stats['record_count']} ingested scans",
        "9999 ingested scans",
    )
    readme_copy = tmp_path / "README.md"
    readme_copy.write_text(corrupted, encoding="utf-8")
    return readme_copy


def test_committed_readme_status_is_up_to_date() -> None:
    # Pytest mirror of the CI `--check` step.
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    expected_section = _upd.build_readme_section(datapackage)
    readme_text = README.read_text(encoding="utf-8")

    assert BEGIN_MARKER in readme_text, "README.md missing <!-- begin:status --> marker"
    assert END_MARKER in readme_text, "README.md missing <!-- end:status --> marker"

    actual_section = _extract_section(readme_text)
    assert actual_section == expected_section, (
        "README.md status section is stale; run `python3 scripts/update_readme_status.py`"
    )


def test_known_input_produces_expected_section() -> None:
    dp = _make_datapackage(
        record_count=5,
        entry_source_count=3,
        scan_byte_count=5_242_880,  # exactly 5.00 MiB
        candidate=2,
        rejected=1,
        license_breakdown={"PDM-1.0": 5},
    )
    section = _upd.build_readme_section(dp)
    assert "5 ingested scans" in section
    assert "3 verified sources" in section
    assert "~5.00 MiB" in section
    assert "2 candidate leads" in section
    assert "1 source records" in section
    assert "- 5 `PDM-1.0` (Public Domain Mark 1.0)" in section


def test_build_readme_section_includes_required_numbers() -> None:
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    section = _upd.build_readme_section(datapackage)
    stats = datapackage["stats"]

    assert str(stats["record_count"]) in section
    assert str(stats["entry_source_count"]) in section
    for license_id, count in stats["license_breakdown"].items():
        assert f"`{license_id}`" in section
        assert str(count) in section


def test_zero_candidates_renders_cleanly() -> None:
    section = _upd.build_readme_section(_make_datapackage(candidate=0))
    assert "0 candidate leads" in section


def test_zero_rejected_renders_cleanly() -> None:
    section = _upd.build_readme_section(_make_datapackage(rejected=0))
    assert "0 source records" in section


def test_unknown_license_omits_parenthetical() -> None:
    dp = _make_datapackage(
        license_breakdown={"UNKNOWN-1.0": 5},
        licenses=[],  # no title available for this license
    )
    section = _upd.build_readme_section(dp)
    assert "- 5 `UNKNOWN-1.0`" in section
    assert "- 5 `UNKNOWN-1.0` (" not in section


def test_check_returns_stale_for_corrupted_readme(tmp_path: Path) -> None:
    stale = _upd.check(readme_path=_corrupted_readme(tmp_path))
    assert len(stale) == 1


def test_check_mode_passes_when_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, str(UPDATER), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_check_mode_fails_when_stale(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(UPDATER), "--check", "--readme", str(_corrupted_readme(tmp_path))],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "stale" in result.stderr
