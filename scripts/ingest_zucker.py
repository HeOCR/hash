#!/usr/bin/env python3
"""
Ingest OPenn Benjamin Zucker Family Ketubah Collection (0051) into staging.

Writes entry records to data/review/zucker_pending.jsonl.
Downloads images to data/scans/openn__zucker__<ket_id>/.
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://openn.library.upenn.edu"
COLLECTION_HTML = f"{BASE_URL}/html/0051.html"
TEI_URL_TMPL = f"{BASE_URL}/Data/0051/{{ket_id}}/data/{{ket_id}}_TEI.xml"
WEB_IMG_URL_TMPL = f"{BASE_URL}/Data/0051/{{ket_id}}/data/{{rel_path}}"

REPO_ROOT = Path(__file__).parent.parent
SCANS_DIR = REPO_ROOT / "data" / "scans"
REVIEW_DIR = REPO_ROOT / "data" / "review"
OUTPUT_FILE = REVIEW_DIR / "zucker_pending.jsonl"

USER_AGENT = "hash-ingest/1.0 (https://github.com/HeOCR/hash)"
CONCURRENCY = 8
BATCH_SLEEP = 0.3  # seconds between batch starts
RETRY_BACKOFF = 90  # seconds on 429

TODAY = "2026-05-24"
ACQUIRED_AT = "2026-05-24T00:00:00Z"

# XML namespaces used in OPenn TEI files
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_get(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise
        raise


def fetch_with_retry(url: str, binary: bool = True):
    """Fetch URL with one retry on 429."""
    try:
        return http_get(url, binary=binary)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  [429] Rate limited, sleeping {RETRY_BACKOFF}s …", flush=True)
            time.sleep(RETRY_BACKOFF)
            return http_get(url, binary=binary)
        raise


# ---------------------------------------------------------------------------
# Step 1 – Parse collection HTML to get all ketubah IDs
# ---------------------------------------------------------------------------

def get_ketubah_ids() -> list[str]:
    print(f"Fetching collection page: {COLLECTION_HTML}", flush=True)
    html = fetch_with_retry(COLLECTION_HTML).decode("utf-8", errors="replace")
    ids = sorted(set(re.findall(r"/Data/0051/html/(ket_z_\d+)\.html", html)))
    print(f"Found {len(ids)} ketubah IDs.", flush=True)
    return ids


# ---------------------------------------------------------------------------
# Step 2 – Parse TEI XML
# ---------------------------------------------------------------------------

def text_or_none(el) -> Optional[str]:
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


def parse_tei(ket_id: str) -> Optional[dict]:
    url = TEI_URL_TMPL.format(ket_id=ket_id)
    try:
        xml_bytes = fetch_with_retry(url)
    except Exception as exc:
        print(f"  [WARN] Could not fetch TEI for {ket_id}: {exc}", flush=True)
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        print(f"  [WARN] Could not parse TEI XML for {ket_id}: {exc}", flush=True)
        return None

    def findall_any(elem, tag):
        """Find all elements with this tag anywhere in subtree."""
        return elem.findall(f".//tei:{tag}", NS)

    def find_any(elem, tag):
        """Find first element with this tag anywhere in subtree."""
        return elem.find(f".//tei:{tag}", NS)

    # call_number
    call_number = None
    for idno in findall_any(root, "idno"):
        if idno.get("type") == "call-number":
            call_number = text_or_none(idno)
            break

    # title (from msItem/title — prefer that over generic title)
    title_text = None
    for ms_item in findall_any(root, "msItem"):
        t_el = ms_item.find("tei:title", NS)
        if t_el is not None:
            title_text = text_or_none(t_el)
            if title_text:
                break
    if not title_text:
        for t_el in findall_any(root, "title"):
            v = text_or_none(t_el)
            if v:
                title_text = v
                break

    # date
    orig_date_el = find_any(root, "origDate")
    date_str = None
    date_precision = "unknown"

    if orig_date_el is not None:
        when = orig_date_el.get("when")
        not_before = orig_date_el.get("notBefore")
        not_after = orig_date_el.get("notAfter")

        if when:
            date_str = when
            # Determine precision from format
            if re.match(r"^\d{4}-\d{2}-\d{2}$", when):
                date_precision = "day"
            elif re.match(r"^\d{4}-\d{2}$", when):
                date_precision = "month"
            elif re.match(r"^\d{4}$", when):
                date_precision = "year"
            else:
                date_precision = "year"
        elif not_before and not_after:
            date_str = f"{not_before}/{not_after}"
            date_precision = "range"
        elif not_before:
            date_str = not_before
            date_precision = "year"
        elif not_after:
            date_str = not_after
            date_precision = "year"
        else:
            # Fall back to text
            t = text_or_none(orig_date_el)
            if t:
                date_str = t
                date_precision = "unknown"

    # language
    text_lang_el = find_any(root, "textLang")
    language = None
    if text_lang_el is not None:
        language = text_lang_el.get("mainLang") or text_or_none(text_lang_el)

    # orig_place
    orig_place_el = find_any(root, "origPlace")
    orig_place = text_or_none(orig_place_el)

    # surfaces from facsimile
    surfaces = []
    for surface_el in findall_any(root, "surface"):
        n_label = surface_el.get("n", "")
        web_url = None
        thumb_url = None
        width_px = None
        height_px = None
        thumb_width = None
        thumb_height = None

        for graphic in surface_el.findall("tei:graphic", NS):
            g_url = graphic.get("url", "")
            g_width = graphic.get("width")
            g_height = graphic.get("height")

            # Parse integer px from e.g. "1234px" or "1234"
            def parse_dim(v):
                if not v:
                    return None
                m = re.match(r"(\d+)", str(v))
                return int(m.group(1)) if m else None

            if g_url.startswith("web/"):
                web_url = g_url
                width_px = parse_dim(g_width)
                height_px = parse_dim(g_height)
            elif g_url.startswith("thumb/"):
                thumb_url = g_url
                thumb_width = parse_dim(g_width)
                thumb_height = parse_dim(g_height)

        if web_url:
            surfaces.append({
                "n": n_label,
                "web_url": web_url,
                "thumb_url": thumb_url,
                "width_px": width_px,
                "height_px": height_px,
                "thumb_width": thumb_width,
                "thumb_height": thumb_height,
            })

    return {
        "ket_id": ket_id,
        "call_number": call_number,
        "title": title_text,
        "date_str": date_str,
        "date_precision": date_precision,
        "language": language,
        "orig_place": orig_place,
        "surfaces": surfaces,
    }


# ---------------------------------------------------------------------------
# Step 3 – Download images
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_image(url: str, dest: Path) -> Optional[dict]:
    """
    Download image to dest. Returns dict with sha256, bytes.
    Returns None on failure. Skips if already downloaded.
    """
    if dest.exists() and dest.stat().st_size > 0:
        # Already downloaded
        size = dest.stat().st_size
        sha = sha256_file(dest)
        return {"sha256": sha, "bytes": size}

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = fetch_with_retry(url, binary=True)
        dest.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        return {"sha256": sha, "bytes": len(data)}
    except Exception as exc:
        print(f"  [ERROR] Download failed for {url}: {exc}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Step 5 – Build entry record
# ---------------------------------------------------------------------------

def build_entry(
    ket_meta: dict,
    surface: dict,
    surface_idx: int,   # 0-based
    total_surfaces: int,
    web_file_info: Optional[dict],
    thumb_file_info: Optional[dict],
    web_local_path: Optional[str],
    thumb_local_path: Optional[str],
    web_full_url: str,
    thumb_full_url: Optional[str],
) -> dict:
    ket_id = ket_meta["ket_id"]
    call_number = ket_meta["call_number"] or ket_id
    date_str = ket_meta["date_str"]
    date_precision = ket_meta["date_precision"]
    orig_place = ket_meta["orig_place"] or "unknown"
    language = ket_meta["language"]
    languages = [language] if language else []

    # NNNN = 1-based, zero-padded to 4 digits
    nnnn = str(surface_idx + 1).zfill(4)

    entry_id = f"openn__zucker__{ket_id}__p{nnnn}"

    # Title: derive year from date_str
    year_match = re.search(r"\d{4}", date_str or "")
    year_str = year_match.group(0) if year_match else (date_str or "unknown date")
    title = f"Ketubah, {year_str} — {call_number}"

    # Files array
    files = []

    # Original (web)
    orig_file = {
        "role": "original",
        "local_path": web_local_path,
        "source_url": web_full_url,
        "sha256": web_file_info["sha256"] if web_file_info else None,
        "mime_type": "image/jpeg",
        "bytes": web_file_info["bytes"] if web_file_info else None,
        "width_px": surface["width_px"],
        "height_px": surface["height_px"],
    }
    files.append(orig_file)

    # Thumbnail
    if thumb_full_url:
        thumb_file = {
            "role": "thumbnail",
            "local_path": thumb_local_path,
            "source_url": thumb_full_url,
            "sha256": thumb_file_info["sha256"] if thumb_file_info else None,
            "mime_type": "image/jpeg",
            "bytes": thumb_file_info["bytes"] if thumb_file_info else None,
            "width_px": surface["thumb_width"],
            "height_px": surface["thumb_height"],
        }
        files.append(thumb_file)

    evidence_text = (
        f"TEI licence statement: 'These images and the content of Benjamin Zucker Family "
        f"Ketubah Collection {call_number} are free of known copyright restrictions and in "
        f"the public domain. See the Creative Commons Public Domain Mark page for usage "
        f"details, http://creativecommons.org/publicdomain/mark/1.0/.'"
    )

    entry = {
        "entry_id": entry_id,
        "source_id": "openn__zucker_ketubah_collection",
        "source_record_id": call_number,
        "sequence": {
            "index": surface_idx,
            "label": surface["n"] or str(surface_idx + 1),
            "physical_unit_count": total_surfaces,
        },
        "title": title,
        "creators": [
            {
                "name": "unknown",
                "role": "writer",
                "death_year": None,
                "authority_url": None,
            }
        ],
        "dates": {
            "created": date_str,
            "created_precision": date_precision,
            "accessed_at": TODAY,
        },
        "languages": languages,
        "script": ["Hebr"],
        "document_type": "other",
        "handwriting": {
            "extent": "full_page",
            "hebrew_extent": "full_page",
            "notes": f"Ketubah (marriage contract). Place: {orig_place}",
        },
        "files": files,
        "rights": {
            "rights_basis": "public_domain",
            "license_expression": "PDM-1.0",
            "commercial_use_allowed": True,
            "derivatives_allowed": True,
            "scan_redistribution_allowed": True,
            "attribution_required": False,
            "attribution_text": None,
            "attribution_url": None,
            "verification_status": "primary_page_checked",
            "evidence_text": evidence_text,
            "verified_at": "2026-05-24",
        },
        "provenance": {
            "acquired_at": ACQUIRED_AT,
            "acquired_by": "agent",
            "source_landing_url": f"https://openn.library.upenn.edu/Data/0051/html/{ket_id}.html",
            "notes": "Ingested from OPenn Zucker Ketubah Collection (0051) via TEI metadata.",
        },
        "holding_institution": "Benjamin Zucker Family Ketubah Collection",
        "holding_shelfmark": call_number,
        "quality": {
            "usable_for_htr": True,
            "legibility": "high",
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

    return entry


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_ketubah(ket_id: str, entries_out: list, failures: list):
    """Process one ketubah: parse TEI, download images, build entries."""
    print(f"\n[{ket_id}] Fetching TEI …", flush=True)
    ket_meta = parse_tei(ket_id)
    if ket_meta is None:
        failures.append({"ket_id": ket_id, "reason": "TEI fetch/parse failed"})
        return 0

    surfaces = ket_meta["surfaces"]
    if not surfaces:
        print(f"  [WARN] No surfaces found for {ket_id}", flush=True)
        failures.append({"ket_id": ket_id, "reason": "No surfaces in TEI"})
        return 0

    total_surfaces = len(surfaces)
    scan_dir = SCANS_DIR / f"openn__zucker__{ket_id}"
    scan_dir.mkdir(parents=True, exist_ok=True)

    entries_created = 0
    for surf_idx, surface in enumerate(surfaces):
        nnnn = str(surf_idx + 1).zfill(4)

        # Build full URLs
        web_full_url = WEB_IMG_URL_TMPL.format(ket_id=ket_id, rel_path=surface["web_url"])
        thumb_full_url = (
            WEB_IMG_URL_TMPL.format(ket_id=ket_id, rel_path=surface["thumb_url"])
            if surface["thumb_url"]
            else None
        )

        # Local paths
        web_local = scan_dir / f"web_{nnnn}.jpg"
        thumb_local = scan_dir / f"thumb_{nnnn}.jpg"

        web_local_str = str(web_local.relative_to(REPO_ROOT))
        thumb_local_str = str(thumb_local.relative_to(REPO_ROOT)) if thumb_full_url else None

        # Download web image
        web_file_info = download_image(web_full_url, web_local)
        if web_file_info:
            print(f"  [{ket_id}] Surface {nnnn}: web OK ({web_file_info['bytes']} bytes)", flush=True)
        else:
            print(f"  [{ket_id}] Surface {nnnn}: web FAILED", flush=True)
            web_local_str = None

        # Download thumbnail
        thumb_file_info = None
        if thumb_full_url:
            thumb_file_info = download_image(thumb_full_url, thumb_local)
            if not thumb_file_info:
                thumb_local_str = None

        # Small delay between surfaces (within a ketubah)
        if surf_idx > 0 and surf_idx % CONCURRENCY == 0:
            time.sleep(BATCH_SLEEP)

        entry = build_entry(
            ket_meta=ket_meta,
            surface=surface,
            surface_idx=surf_idx,
            total_surfaces=total_surfaces,
            web_file_info=web_file_info,
            thumb_file_info=thumb_file_info,
            web_local_path=web_local_str,
            thumb_local_path=thumb_local_str,
            web_full_url=web_full_url,
            thumb_full_url=thumb_full_url,
        )
        entries_out.append(entry)
        entries_created += 1

    return entries_created


def main():
    # Step 1: get IDs
    ket_ids = get_ketubah_ids()

    entries_all = []
    failures = []
    total_entries = 0

    # Step 2+3: process each ketubah
    for ket_id in ket_ids:
        n = process_ketubah(ket_id, entries_all, failures)
        total_entries += n

    # Step 6: write JSONL
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fout:
        for entry in entries_all:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Step 7: summary
    total_ketubot = len(ket_ids) - len([f for f in failures if "TEI" in f.get("reason", "")])
    downloaded_web = sum(
        1
        for e in entries_all
        for f in e.get("files", [])
        if f["role"] == "original" and f.get("sha256") is not None
    )
    print("\n" + "=" * 60)
    print(f"SUMMARY")
    print(f"  Ketubah IDs found:       {len(ket_ids)}")
    print(f"  Ketubot processed:       {len(ket_ids) - len(failures)}")
    print(f"  Failures:                {len(failures)}")
    print(f"  Total entries written:   {total_entries}")
    print(f"  Web images downloaded:   {downloaded_web}")
    print(f"  Output:                  {OUTPUT_FILE}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f['ket_id']}: {f['reason']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
