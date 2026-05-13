from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_release.py"

_spec = importlib.util.spec_from_file_location("build_release", BUILDER)
_br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_br)

DATAPACKAGE = REPO_ROOT / "datapackage.json"


def _expected_archive_name() -> tuple[str, str]:
    descriptor = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    name = descriptor["name"]
    version = descriptor["version"]
    return name, version


def _build(tmp_path: Path) -> Path:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--dist", str(tmp_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    name, version = _expected_archive_name()
    output = tmp_path / f"{name}-{version}.tar.gz"
    assert output.exists(), result.stdout + result.stderr
    return output


def test_tarball_round_trips_through_tar_tzf(tmp_path: Path) -> None:
    output = _build(tmp_path)
    listing = subprocess.run(
        ["tar", "tzf", str(output)],
        text=True, capture_output=True, check=True,
    )
    names = [line for line in listing.stdout.splitlines() if line]
    assert names, "tar tzf returned no entries"
    name, version = _expected_archive_name()
    root = f"{name}-{version}"
    assert any(n.startswith(root + "/") for n in names), (
        f"tarball entries should be rooted at {root}/; got {names[:3]}"
    )


def test_tarball_contains_every_required_member(tmp_path: Path) -> None:
    output = _build(tmp_path)
    name, version = _expected_archive_name()
    root = f"{name}-{version}"

    required_files = {
        f"{root}/LICENSE",
        f"{root}/LICENSE.md",
        f"{root}/NOTICE.md",
        f"{root}/CITATION.cff",
        f"{root}/datapackage.json",
        f"{root}/README.md",
        f"{root}/MANIFEST.txt",
        f"{root}/data/index/entries.jsonl",
        f"{root}/data/index/sources.jsonl",
        f"{root}/exports/entries.csv",
        f"{root}/exports/sources.csv",
    }

    with tarfile.open(output, mode="r:gz") as tar:
        members = {member.name for member in tar.getmembers() if member.isfile()}

    missing = required_files - members
    assert not missing, f"tarball missing required entries: {sorted(missing)}"

    # Every data/scans/ file referenced in entries.jsonl should also be present.
    entries = [
        json.loads(line)
        for line in (REPO_ROOT / "data" / "index" / "entries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    for entry in entries:
        for file_obj in entry["files"]:
            local_path = file_obj.get("local_path")
            if local_path is None:
                continue
            archive_name = f"{root}/{local_path}"
            assert archive_name in members, (
                f"tarball missing scan file referenced by {entry['entry_id']}: "
                f"{archive_name}"
            )


def test_tarball_does_not_include_dist_or_dotfiles(tmp_path: Path) -> None:
    output = _build(tmp_path)
    with tarfile.open(output, mode="r:gz") as tar:
        members = [member.name for member in tar.getmembers()]
    for name in members:
        assert "/dist/" not in name, f"tarball should not contain dist/: {name}"
        assert "/.git/" not in name, f"tarball should not contain .git/: {name}"
        assert "/.claude/" not in name, f"tarball should not contain .claude/: {name}"


def test_manifest_lists_every_archive_file(tmp_path: Path) -> None:
    output = _build(tmp_path)
    name, version = _expected_archive_name()
    root = f"{name}-{version}"

    with tarfile.open(output, mode="r:gz") as tar:
        manifest_member = tar.getmember(f"{root}/MANIFEST.txt")
        manifest_text = tar.extractfile(manifest_member).read().decode("utf-8")
        archived_files = {
            member.name for member in tar.getmembers() if member.isfile()
        }

    manifest_paths: list[str] = []
    for line in manifest_text.splitlines():
        if not line.strip():
            continue
        parts = line.rsplit("  ", 1)
        assert len(parts) == 2, f"malformed manifest line: {line!r}"
        manifest_paths.append(parts[1])

    expected_paths = sorted(
        member[len(root) + 1 :] for member in archived_files
    )
    # MANIFEST.txt lists every file in the archive, including itself.
    assert sorted(manifest_paths) == expected_paths


def test_manifest_sha256_lines_match_archive_contents(tmp_path: Path) -> None:
    output = _build(tmp_path)
    name, version = _expected_archive_name()
    root = f"{name}-{version}"

    with tarfile.open(output, mode="r:gz") as tar:
        manifest_member = tar.getmember(f"{root}/MANIFEST.txt")
        manifest_text = tar.extractfile(manifest_member).read().decode("utf-8")
        per_path_bytes: dict[str, bytes] = {}
        for member in tar.getmembers():
            if member.isfile() and member.name != f"{root}/MANIFEST.txt":
                per_path_bytes[member.name[len(root) + 1 :]] = (
                    tar.extractfile(member).read()
                )

    for line in manifest_text.splitlines():
        if not line.strip():
            continue
        sha, _bytes_field, relative_path = line.split(None, 2)
        if relative_path == "MANIFEST.txt":
            assert sha == "-" * 64
            continue
        expected = hashlib.sha256(per_path_bytes[relative_path]).hexdigest()
        assert sha == expected, f"manifest sha mismatch for {relative_path}"


def test_tarball_is_deterministic_across_runs(tmp_path: Path) -> None:
    first = _build(tmp_path / "run1")
    second = _build(tmp_path / "run2")
    assert first.read_bytes() == second.read_bytes(), (
        "release tarball is not reproducible — same inputs produced different bytes"
    )


def test_missing_datapackage_raises(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable, str(BUILDER),
            "--datapackage", str(tmp_path / "nonexistent.json"),
            "--dist", str(tmp_path),
        ],
        cwd=REPO_ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "nonexistent.json" in result.stderr
