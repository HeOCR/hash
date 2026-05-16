#!/usr/bin/env python3
"""
Ingest manually-downloaded Hannah Senesh NLI scan files into the dataset.

Usage:
    python3 scripts/ingest_senesh_downloads.py

The script expects files matching ~/Downloads/nli_senesh_*.{jpg,jpeg,png,pdf}
Filename conventions:
  nli_senesh_diary_violin_p001.jpg   -> nli__nnl_archive_al997009912248505171
  nli_senesh_speech_p001.jpg         -> nli__nnl_archive_al997009831775705171
  nli_senesh_poems_p001.jpg          -> nli__nnl_archive_al997009912248405171
  nli_senesh_diary_hehe_p001.jpg     -> nli__nnl_archive_al997009912248705171
  nli_senesh_pocket_p001.jpg         -> nli__nnl_archive_al997009761278705171
"""

from __future__ import annotations

import glob
import hashlib
import json
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = REPO_ROOT / "data" / "index" / "sources.jsonl"
ENTRIES_PATH = REPO_ROOT / "data" / "index" / "entries.jsonl"
SCANS_DIR = REPO_ROOT / "data" / "scans"
DOWNLOADS_DIR = Path.home() / "Downloads"

# Map filename prefix -> (source_id, title_template, languages, document_type)
PREFIX_MAP = {
    "nli_senesh_diary_violin": (
        "nli__nnl_archive_al997009912248505171",
        "Handwritten Diary/Violin draft, Hannah Szenes, page {seq}",
        ["he"],
        "diary",
    ),
    "nli_senesh_speech": (
        "nli__nnl_archive_al997009831775705171",
        "Handwritten Speech Draft, Hannah Szenes, page {seq}",
        ["he"],
        "draft",
    ),
    "nli_senesh_poems": (
        "nli__nnl_archive_al997009912248405171",
        "Hebrew Poem Notebook, Hannah Szenes, page {seq}",
        ["he"],
        "poem",
    ),
    "nli_senesh_diary_hehe": (
        "nli__nnl_archive_al997009912248705171",
        "Hebrew/Hungarian Diary, Hannah Szenes, page {seq}",
        ["he", "hu"],
        "diary",
    ),
    "nli_senesh_pocket": (
        "nli__nnl_archive_al997009761278705171",
        "Pocket Diary 1939, Hannah Szenes, page {seq}",
        ["he"],
        "diary",
    ),
}

CREATOR = {
    "name": "Hannah Senesh",
    "role": "author",
    "death_year": 1944,
    "authority_url": "https://www.wikidata.org/wiki/Q231364",
}

RIGHTS = {
    "rights_basis": "public_domain",
    "license_expression": "LicenseRef-Public-Domain-Israel",
    "commercial_use_allowed": True,
    "derivatives_allowed": True,
    "scan_redistribution_allowed": True,
    "attribution_required": True,
    "attribution_text": "Hannah Senesh; National Library of Israel",
    "attribution_url": "https://www.nli.org.il/en/archives/NNL_ARCHIVE_AL997009165988705171/NLI",
    "verification_status": "primary_page_checked",
    "evidence_text": (
        "NLI item page 'Any Use Permitted': 'You may copy and use the item for any purpose. "
        "There is no need to contact the National Library for permission to use the item. "
        "This item is part of the Public Domain and is not subject to copyright restrictions "
        "in the State of Israel. Any use of this item must include the creator's name and "
        "indicate its source in the National Library of Israel's collections.'"
    ),
    "terms_url": None,
    "verified_at": "2026-05-16",
}

DATE_SOURCES = {
    "nli__nnl_archive_al997009912248505171": ("1941/1944", "range"),
    "nli__nnl_archive_al997009831775705171": ("1941", "year"),
    "nli__nnl_archive_al997009912248405171": ("1944", "year"),
    "nli__nnl_archive_al997009912248705171": ("1938/1941", "range"),
    "nli__nnl_archive_al997009761278705171": ("1939", "year"),
}

SOURCE_RECORD_IDS = {
    "nli__nnl_archive_al997009912248505171": "NNL_ARCHIVE_AL997009912248505171",
    "nli__nnl_archive_al997009831775705171": "NNL_ARCHIVE_AL997009831775705171",
    "nli__nnl_archive_al997009912248405171": "NNL_ARCHIVE_AL997009912248405171",
    "nli__nnl_archive_al997009912248705171": "NNL_ARCHIVE_AL997009912248705171",
    "nli__nnl_archive_al997009761278705171": "NNL_ARCHIVE_AL997009761278705171",
}


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def get_image_dims(path: Path) -> tuple[int | None, int | None]:
    if Image is None:
        return None, None
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None, None


def find_prefix(filename: str) -> tuple[str, tuple] | None:
    for prefix, info in PREFIX_MAP.items():
        if filename.lower().startswith(prefix):
            return prefix, info
    return None


def parse_sequence(filename: str, prefix: str) -> int:
    stem = Path(filename).stem  # e.g. nli_senesh_diary_violin_p001
    after = stem[len(prefix):]  # e.g. _p001
    after = after.lstrip("_")   # e.g. p001
    digits = "".join(c for c in after if c.isdigit())
    return int(digits) if digits else 0


def load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def save_jsonl(path: Path, rows: list[dict]) -> None:
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def existing_entry_ids(entries: list[dict]) -> set[str]:
    return {e["entry_id"] for e in entries}


def next_sequence(entries: list[dict], source_id: str) -> int:
    seqs = [
        e["sequence"]["index"]
        for e in entries
        if e["source_id"] == source_id
    ]
    return max(seqs, default=0) + 1


def ingest_file(dl_path: Path, dry_run: bool = False) -> dict | None:
    fname = dl_path.name
    result = find_prefix(fname)
    if result is None:
        print(f"  [skip] {fname}: no matching prefix")
        return None

    prefix, (source_id, title_tmpl, languages, doc_type) = result
    seq = parse_sequence(fname, prefix)
    if seq == 0:
        print(f"  [skip] {fname}: cannot parse sequence number")
        return None

    entry_id = f"{source_id}__p{seq:04d}"
    dest_dir = SCANS_DIR / source_id
    ext = dl_path.suffix.lower()
    dest_fname = f"{entry_id}{ext}"
    dest_path = dest_dir / dest_fname
    local_path = f"data/scans/{source_id}/{dest_fname}"

    if dry_run:
        print(f"  [dry-run] would copy {fname} -> {local_path}")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dl_path, dest_path)

    sha256 = sha256_file(dest_path)
    size = dest_path.stat().st_size
    w, h = get_image_dims(dest_path)

    date_val, date_prec = DATE_SOURCES[source_id]
    source_record_id = SOURCE_RECORD_IDS[source_id]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"

    entry = {
        "entry_id": entry_id,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "sequence": {"index": seq, "label": str(seq), "physical_unit_count": 1},
        "title": title_tmpl.format(seq=seq),
        "creators": [CREATOR],
        "dates": {
            "created": date_val,
            "created_precision": date_prec,
            "accessed_at": "2026-05-16",
        },
        "languages": languages,
        "script": ["Hebr"],
        "document_type": doc_type,
        "handwriting": {
            "extent": "full_page",
            "hebrew_extent": "full_page" if "hu" not in languages else "partial_page",
            "notes": f"Handwritten page from NLI item {source_record_id}.",
        },
        "files": [
            {
                "role": "original",
                "local_path": local_path,
                "source_url": f"https://www.nli.org.il/en/archives/{source_record_id}/NLI",
                "provider_file_id": source_record_id,
                "sha256": sha256,
                "mime_type": mime,
                "bytes": size,
                "width_px": w,
                "height_px": h,
            }
        ],
        "rights": RIGHTS,
        "provenance": {
            "acquired_at": now_iso,
            "acquired_by": "human_browser_download",
            "source_landing_url": f"https://www.nli.org.il/en/archives/{source_record_id}/NLI",
            "notes": "Downloaded manually via browser after NLI blocked automated access (Cloudflare).",
        },
        "holding_institution": "National Library of Israel",
        "holding_shelfmark": source_record_id,
        "quality": {
            "usable_for_htr": True,
            "legibility": "unknown",
            "exclusion_reasons": [],
            "notes": "Quality to be assessed after visual inspection.",
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
    return entry


def promote_sources(sources: list[dict], ingested_source_ids: set[str]) -> None:
    """Mark ingested sources as verified and promote collection record."""
    collection_id = "nli__hannah_senesh_archive"
    for src in sources:
        if src["source_id"] in ingested_source_ids:
            src["status"] = "verified"
        if src["source_id"] == collection_id and ingested_source_ids:
            src["status"] = "verified"


def expand_zips(zip_path: Path) -> list[Path]:
    """Extract a nli_senesh_*.zip into a temp dir, returning sorted image paths.

    The zip stem determines the filename prefix used for the extracted pages,
    so nli_senesh_diary_violin.zip -> nli_senesh_diary_violin_p0001.jpg etc.
    Files are extracted to a sibling temp directory and the paths returned for
    normal per-file ingestion.
    """
    stem = zip_path.stem  # e.g. nli_senesh_diary_violin
    result = find_prefix(zip_path.name)
    if result is None:
        print(f"  [skip] {zip_path.name}: no matching prefix in zip filename")
        return []

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"nli_senesh_{stem}_"))
    with zipfile.ZipFile(zip_path) as zf:
        image_names = sorted(
            n for n in zf.namelist()
            if Path(n).suffix.lower() in (".jpg", ".jpeg", ".png")
            and not Path(n).name.startswith(".")
            and "__MACOSX" not in n
        )
        if not image_names:
            print(f"  [skip] {zip_path.name}: no image files inside zip")
            return []
        zf.extractall(tmp_dir, members=image_names)

    extracted: list[Path] = []
    for seq, name in enumerate(image_names, start=1):
        src = tmp_dir / name
        ext = Path(name).suffix.lower()
        dest_name = f"{stem}_p{seq:03d}{ext}"
        dest = tmp_dir / dest_name
        src.rename(dest)
        extracted.append(dest)

    print(f"  [zip] {zip_path.name}: extracted {len(extracted)} page(s)")
    return extracted


def main(watch_minutes: int = 30) -> None:
    print(f"Watching {DOWNLOADS_DIR} for nli_senesh_*.{{jpg,jpeg,png,pdf,zip}} ...")
    print(f"Will watch for up to {watch_minutes} minutes.")

    deadline = time.time() + watch_minutes * 60
    processed: set[str] = set()

    while True:
        patterns = [
            str(DOWNLOADS_DIR / "nli_senesh_*.jpg"),
            str(DOWNLOADS_DIR / "nli_senesh_*.jpeg"),
            str(DOWNLOADS_DIR / "nli_senesh_*.png"),
            str(DOWNLOADS_DIR / "nli_senesh_*.pdf"),
            str(DOWNLOADS_DIR / "nli_senesh_*.zip"),
        ]
        found_files = []
        for pat in patterns:
            found_files.extend(glob.glob(pat))

        new_files = [f for f in found_files if f not in processed]
        if new_files:
            print(f"\nFound {len(new_files)} new file(s):")
            sources = load_jsonl(SOURCES_PATH)
            entries = load_jsonl(ENTRIES_PATH)
            existing_ids = existing_entry_ids(entries)
            ingested_source_ids: set[str] = set()
            new_entries: list[dict] = []

            # Expand any zips into individual image paths first
            image_files: list[Path] = []
            for fpath in sorted(new_files):
                dl_path = Path(fpath)
                if dl_path.suffix.lower() == ".zip":
                    image_files.extend(expand_zips(dl_path))
                    processed.add(fpath)
                else:
                    image_files.append(dl_path)

            for dl_path in image_files:
                print(f"  Processing: {dl_path.name}")
                entry = ingest_file(dl_path)
                if entry is None:
                    processed.add(str(dl_path))
                    continue

                entry_id = entry["entry_id"]
                if entry_id in existing_ids:
                    print(f"    [skip] {entry_id} already in entries.jsonl")
                    processed.add(str(dl_path))
                    continue

                new_entries.append(entry)
                ingested_source_ids.add(entry["source_id"])
                existing_ids.add(entry_id)
                processed.add(str(dl_path))
                print(f"    -> {entry_id} ({entry['files'][0]['local_path']})")

            if new_entries:
                entries.extend(new_entries)
                entries.sort(key=lambda e: e["entry_id"])
                save_jsonl(ENTRIES_PATH, entries)
                promote_sources(sources, ingested_source_ids)
                save_jsonl(SOURCES_PATH, sources)
                print(f"\nIngested {len(new_entries)} new entries.")
                print("Sources promoted:", sorted(ingested_source_ids))

        if time.time() > deadline:
            if processed:
                print(f"\nDone watching. Total files processed: {len(processed)}")
            else:
                print(f"\nTimed out after {watch_minutes} minutes with no files found.")
            break

        time.sleep(15)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-minutes", type=int, default=30)
    args = parser.parse_args()
    main(watch_minutes=args.watch_minutes)
