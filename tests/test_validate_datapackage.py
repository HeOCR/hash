from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate_datapackage.py"
DATAPACKAGE = REPO_ROOT / "datapackage.json"


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *(str(arg) for arg in args)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_live_datapackage_validates() -> None:
    result = _run()

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ok: datapackage.json metadata valid"), result.stdout
    assert "public-domain-hand-written-hebrew-scans" in result.stdout
    assert "v0.1.0-rc" in result.stdout


def test_tampered_datapackage_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "datapackage.json"
    shutil.copyfile(DATAPACKAGE, bad)
    descriptor = json.loads(bad.read_text(encoding="utf-8"))
    del descriptor["resources"]
    bad.write_text(json.dumps(descriptor), encoding="utf-8")

    result = _run("--datapackage", bad)

    assert result.returncode == 1
    assert "'resources' is a required property" in result.stderr
    assert result.stdout == ""


def test_completely_empty_descriptor_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "datapackage.json"
    bad.write_text("{}\n", encoding="utf-8")

    result = _run("--datapackage", bad)

    assert result.returncode == 1
    assert "ERROR:" in result.stderr
