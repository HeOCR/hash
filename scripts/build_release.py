#!/usr/bin/env python3
"""Assemble the v0.1.0-style release tarball under dist/.

The tarball is a single self-contained bundle that a downstream consumer can
fetch from one URL and have the full corpus, indexes, flat exports, license
and notice files, citation metadata, and a manifest listing every included
file with its size and sha256.

The bundle includes:

  data/scans/               binary scan files
  data/index/               canonical JSONL indexes
  exports/                  flat CSV exports
  LICENSE                   CC0-1.0 metadata licence text
  LICENSE.md                compound-licensing policy
  NOTICE.md                 attribution roll-up (generated)
  CITATION.cff              Citation File Format (generated)
  datapackage.json          Frictionless Data Package manifest (generated)
  README.md                 repo README
  MANIFEST.txt              generated: per-file path, bytes, sha256

The tarball name is `<package_name>-<version>.tar.gz`, drawn from
`datapackage.json`. Inside the archive every path is rooted at the same
`<package_name>-<version>/` directory so `tar xzf` produces a single
versioned folder.

Each TarInfo is normalised (uid/gid 0, mtime 0, mode 0o644 for files,
0o755 for dirs) so the tarball is reproducible: same inputs, byte-identical
archive within a single Python/tar build.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATAPACKAGE_PATH = REPO_ROOT / "datapackage.json"
DIST_DIR = REPO_ROOT / "dist"

# Top-level paths that go into every release tarball. Directories are walked
# recursively, files are included verbatim. Order does not matter (the writer
# sorts everything by archive path) but listing them here is the contract.
INCLUDED_DIRS: tuple[str, ...] = (
    "data/scans",
    "data/index",
    "exports",
)
INCLUDED_FILES: tuple[str, ...] = (
    "LICENSE",
    "LICENSE.md",
    "NOTICE.md",
    "CITATION.cff",
    "datapackage.json",
    "README.md",
)


def _load_version(datapackage_path: Path) -> tuple[str, str]:
    if not datapackage_path.exists():
        raise SystemExit(
            f"{datapackage_path}: file does not exist. "
            f"Run `python3 scripts/generate_release_artifacts.py` first."
        )
    descriptor = json.loads(datapackage_path.read_text(encoding="utf-8"))
    return descriptor["name"], descriptor["version"]


def _gather_paths(repo_root: Path) -> list[Path]:
    """Collect every file (no directories) that should land in the tarball."""
    collected: list[Path] = []
    for relative in INCLUDED_FILES:
        path = repo_root / relative
        if not path.is_file():
            raise SystemExit(f"{relative}: required release file is missing")
        collected.append(path)
    for relative in INCLUDED_DIRS:
        directory = repo_root / relative
        if not directory.is_dir():
            raise SystemExit(f"{relative}/: required release directory is missing")
        for entry in sorted(directory.rglob("*")):
            if entry.is_file():
                collected.append(entry)
    # Stable order — the manifest, the tarball, and the per-file iteration
    # below all depend on this single sorted ordering.
    return sorted(collected, key=lambda p: p.relative_to(repo_root).as_posix())


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _build_manifest(paths: list[Path], repo_root: Path) -> bytes:
    """Return MANIFEST.txt as bytes: `<sha256>  <bytes>  <relative_path>`.

    Includes MANIFEST.txt as the last line, with `-` placeholders for its own
    sha256 and bytes (since both are unknown until after this text is built).
    Consumers that need to verify MANIFEST.txt should verify the tarball's
    detached signature instead.
    """
    lines = []
    for path in paths:
        relative = path.relative_to(repo_root).as_posix()
        lines.append(f"{_sha256(path)}  {path.stat().st_size:>12}  {relative}")
    lines.append(f"{'-' * 64}  {'-' * 12}  MANIFEST.txt")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _archive_member(
    name: str, *, is_dir: bool = False, size: int = 0
) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if is_dir:
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
    else:
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        info.size = size
    return info


def build_tarball(
    output_path: Path,
    paths: list[Path],
    manifest_bytes: bytes,
    archive_root: str,
    repo_root: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the tar payload to an in-memory buffer first so we can wrap it in a
    # gzip stream with an explicit mtime=0 header. `tarfile.open(mode="w:gz")`
    # writes the current wall-clock time into the gzip header, which would make
    # the archive bytes drift across runs even though the inner tar is
    # reproducible.
    tar_buffer = io.BytesIO()
    with tarfile.open(
        fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT
    ) as tar:
        # Single top-level dir entry so `tar xzf` produces one versioned folder.
        tar.addfile(_archive_member(archive_root + "/", is_dir=True))

        for path in paths:
            relative = path.relative_to(repo_root).as_posix()
            data = path.read_bytes()
            info = _archive_member(f"{archive_root}/{relative}", size=len(data))
            tar.addfile(info, io.BytesIO(data))

        manifest_info = _archive_member(
            f"{archive_root}/MANIFEST.txt", size=len(manifest_bytes)
        )
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

    with open(output_path, "wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9
        ) as gz:
            gz.write(tar_buffer.getvalue())


def generate(
    repo_root: Path = REPO_ROOT,
    datapackage_path: Path = DATAPACKAGE_PATH,
    dist_dir: Path = DIST_DIR,
) -> Path:
    name, version = _load_version(datapackage_path)
    archive_root = f"{name}-{version}"
    output_path = dist_dir / f"{archive_root}.tar.gz"

    paths = _gather_paths(repo_root)
    manifest_bytes = _build_manifest(paths, repo_root)
    build_tarball(
        output_path=output_path,
        paths=paths,
        manifest_bytes=manifest_bytes,
        archive_root=archive_root,
        repo_root=repo_root,
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--datapackage", type=Path, default=DATAPACKAGE_PATH)
    parser.add_argument("--dist", type=Path, default=DIST_DIR)
    args = parser.parse_args()

    output_path = generate(
        repo_root=args.repo_root,
        datapackage_path=args.datapackage,
        dist_dir=args.dist,
    )
    try:
        display = output_path.relative_to(REPO_ROOT)
    except ValueError:
        display = output_path
    print(f"wrote release tarball: {display}", file=sys.stderr)
    print(display)


if __name__ == "__main__":
    main()
