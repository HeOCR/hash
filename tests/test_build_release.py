from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_release.py"

_spec = importlib.util.spec_from_file_location("build_release", BUILDER)
_br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_br)

DATAPACKAGE = REPO_ROOT / "datapackage.json"


def _expected_release_metadata() -> tuple[str, str, int]:
    descriptor = json.loads(DATAPACKAGE.read_text(encoding="utf-8"))
    released_at = descriptor["released_at"]
    if released_at.endswith("Z"):
        released_at = released_at[:-1] + "+00:00"
    epoch = int(
        dt.datetime.fromisoformat(released_at)
        .astimezone(dt.timezone.utc).timestamp()
    )
    return descriptor["name"], descriptor["version"], epoch


def _build(tmp_path: Path) -> Path:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--dist", str(tmp_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    name, version, _epoch = _expected_release_metadata()
    output = tmp_path / f"{name}-{version}.tar.gz"
    assert output.exists(), result.stdout + result.stderr
    return output


@pytest.fixture(scope="session")
def release_tarball(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the release tarball once per test session.

    Each build packs ~45 MiB of scan files through gzip; doing this once
    and sharing the result across the inspection tests keeps the suite
    cheap. The byte-determinism test still builds twice on purpose.
    """
    tmp_path = tmp_path_factory.mktemp("release")
    return _build(tmp_path)


def _members(tarball: Path) -> list[tarfile.TarInfo]:
    with tarfile.open(tarball, mode="r:gz") as tar:
        return tar.getmembers()


def test_tarball_round_trips_through_tar_tzf(release_tarball: Path) -> None:
    # Acceptance criterion #11 names `tar tzf` explicitly, so verify the
    # bundle round-trips through the system tar binary. The other tests
    # use the in-process tarfile module to avoid the shell-out cost.
    listing = subprocess.run(
        ["tar", "tzf", str(release_tarball)],
        text=True, capture_output=True, check=True,
    )
    names = [line for line in listing.stdout.splitlines() if line]
    assert names, "tar tzf returned no entries"
    name, version, _epoch = _expected_release_metadata()
    root = f"{name}-{version}"
    assert any(n.startswith(root + "/") for n in names), (
        f"tarball entries should be rooted at {root}/; got {names[:3]}"
    )


def test_tarball_contains_every_required_member(release_tarball: Path) -> None:
    name, version, _epoch = _expected_release_metadata()
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
        f"{root}/exports/creators.csv",
    }

    members = {m.name for m in _members(release_tarball) if m.isfile()}
    missing = required_files - members
    assert not missing, f"tarball missing required entries: {sorted(missing)}"

    # Every data/scans/ file referenced in entries.jsonl should be present.
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


def test_tarball_does_not_include_dist_or_dotfiles(release_tarball: Path) -> None:
    for member in _members(release_tarball):
        name = member.name
        assert "/dist/" not in name, f"tarball should not contain dist/: {name}"
        assert "/.git/" not in name, f"tarball should not contain .git/: {name}"
        assert "/.claude/" not in name, f"tarball should not contain .claude/: {name}"


def test_tarball_mtime_matches_released_at(release_tarball: Path) -> None:
    # Member mtimes carry the released_at timestamp from datapackage.json,
    # not 1970-01-01 — extracted files should look like a normal release,
    # not a clock bug.
    _name, _version, expected_epoch = _expected_release_metadata()
    members = _members(release_tarball)
    assert members, "empty tarball"
    for member in members:
        assert member.mtime == expected_epoch, (
            f"{member.name}: mtime {member.mtime} != released_at {expected_epoch}"
        )


def test_manifest_lists_every_archive_file_except_itself(
    release_tarball: Path,
) -> None:
    name, version, _epoch = _expected_release_metadata()
    root = f"{name}-{version}"

    with tarfile.open(release_tarball, mode="r:gz") as tar:
        manifest_member = tar.getmember(f"{root}/MANIFEST.txt")
        manifest_text = tar.extractfile(manifest_member).read().decode("utf-8")
        archived_files = {m.name for m in tar.getmembers() if m.isfile()}

    manifest_paths = []
    for line in manifest_text.splitlines():
        if not line.strip():
            continue
        # Three whitespace-separated columns: sha256, bytes, relative_path.
        _sha, _bytes_field, relative_path = line.split(None, 2)
        manifest_paths.append(relative_path)

    expected_paths = sorted(
        member[len(root) + 1:]
        for member in archived_files
        if member != f"{root}/MANIFEST.txt"
    )
    assert sorted(manifest_paths) == expected_paths
    assert "MANIFEST.txt" not in manifest_paths, (
        "MANIFEST.txt must not list itself; it cannot self-reference its own hash"
    )


def test_manifest_sha256_lines_match_archive_contents(
    release_tarball: Path,
) -> None:
    name, version, _epoch = _expected_release_metadata()
    root = f"{name}-{version}"

    with tarfile.open(release_tarball, mode="r:gz") as tar:
        manifest_text = (
            tar.extractfile(tar.getmember(f"{root}/MANIFEST.txt"))
            .read().decode("utf-8")
        )
        per_path_bytes: dict[str, bytes] = {}
        for member in tar.getmembers():
            if member.isfile() and member.name != f"{root}/MANIFEST.txt":
                per_path_bytes[member.name[len(root) + 1:]] = (
                    tar.extractfile(member).read()
                )

    for line in manifest_text.splitlines():
        if not line.strip():
            continue
        sha, _bytes_field, relative_path = line.split(None, 2)
        expected = hashlib.sha256(per_path_bytes[relative_path]).hexdigest()
        assert sha == expected, f"manifest sha mismatch for {relative_path}"


def test_tarball_is_deterministic_across_runs(tmp_path: Path) -> None:
    # Two fresh builds — compare via sha256 of the bytes rather than direct
    # byte equality so a failure prints a 64-char digest instead of dumping
    # 45 MiB of binary diff into the pytest output.
    first = _build(tmp_path / "run1")
    second = _build(tmp_path / "run2")
    first_digest = hashlib.sha256(first.read_bytes()).hexdigest()
    second_digest = hashlib.sha256(second.read_bytes()).hexdigest()
    assert first_digest == second_digest, (
        "release tarball is not reproducible — same inputs produced different bytes "
        f"(run1 sha256={first_digest}, run2 sha256={second_digest})"
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
