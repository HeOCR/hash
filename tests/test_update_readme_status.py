from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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


def test_committed_readme_status_is_up_to_date() -> None:
    # Pytest mirror of the CI `--check` step: catches the local
    # "didn't regenerate before committing" mode.
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    expected_section = _upd.build_readme_section(datapackage)
    readme_text = README.read_text(encoding="utf-8")

    assert BEGIN_MARKER in readme_text, "README.md missing <!-- begin:status --> marker"
    assert END_MARKER in readme_text, "README.md missing <!-- end:status --> marker"

    actual_section = _extract_section(readme_text)
    assert actual_section == expected_section, (
        "README.md status section is stale; run `python3 scripts/update_readme_status.py`"
    )


def test_build_readme_section_includes_required_numbers() -> None:
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    section = _upd.build_readme_section(datapackage)
    stats = datapackage["stats"]

    assert str(stats["record_count"]) in section
    assert str(stats["entry_source_count"]) in section
    for license_id, count in stats["license_breakdown"].items():
        assert f"`{license_id}`" in section
        assert str(count) in section


def test_build_readme_section_is_deterministic() -> None:
    datapackage = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    assert _upd.build_readme_section(datapackage) == _upd.build_readme_section(datapackage)


def test_check_returns_empty_when_up_to_date() -> None:
    stale = _upd.check()
    assert stale == []


def test_check_returns_stale_for_corrupted_readme(tmp_path: Path) -> None:
    readme_copy = tmp_path / "README.md"
    original = README.read_text(encoding="utf-8")
    corrupted = original.replace(
        str(json.loads(DATAPACKAGE.read_text())["stats"]["record_count"]) + " ingested scans",
        "9999 ingested scans",
    )
    readme_copy.write_text(corrupted, encoding="utf-8")

    stale = _upd.check(readme_path=readme_copy)
    assert stale == [readme_copy]


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
    readme_copy = tmp_path / "README.md"
    original = README.read_text(encoding="utf-8")
    corrupted = original.replace(
        str(json.loads(DATAPACKAGE.read_text())["stats"]["record_count"]) + " ingested scans",
        "9999 ingested scans",
    )
    readme_copy.write_text(corrupted, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(UPDATER), "--check", "--readme", str(readme_copy)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "stale" in result.stderr
    assert "README.md" in result.stderr
