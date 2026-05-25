#!/usr/bin/env python3
"""
Ingest Library of Congress Hebraic Manuscripts Collection into staging.

Writes entry records to data/review/loc_pending.jsonl.
Downloads images to data/scans/loc__<item_slug>/.

Usage:
    python3 scripts/ingest_loc.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_API = (
    "https://www.loc.gov/collections/hebraic-manuscripts/"
    "?fo=json&at=results,pagination&c=100&sp={page}"
)
ITEM_API = "https://www.loc.gov/item/{item_id}/?fo=json"

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANS_DIR = REPO_ROOT / "data" / "scans"
REVIEW_DIR = REPO_ROOT / "data" / "review"
OUTPUT_FILE = REVIEW_DIR / "loc_pending.jsonl"

USER_AGENT = "hash-ingest/1.0 (https://github.com/HeOCR/hash)"
SLEEP_BETWEEN_ITEMS = 0.5   # seconds
SLEEP_BETWEEN_PAGES = 1.0   # seconds between collection API pages
SLEEP_ON_429 = 90           # seconds on rate-limit

MAX_PAGES_PER_ITEM = 5

TODAY = "2026-05-25"
ACQUIRED_AT = "2026-05-25T00:00:00Z"

# Rights evidence text (from item.rights field, common to whole collection)
RIGHTS_EVIDENCE = (
    "The contents of Hebraic Manuscripts at the Library of Congress are in the "
    "public domain or have no known copyright restrictions and are free to use and "
    "reuse. Credit Line: Library of Congress, African and Middle East Division, "
    "Hebraic Section Manuscript Collection."
)

# ---------------------------------------------------------------------------
# Scope-filter keywords (lower-cased)
# ---------------------------------------------------------------------------

EXCLUDE_WORDS = {
    "printed", "incunabulum", "incunabula", "typeset", "lithograph",
    "lithographed", "woodcut", "engraving", "engraved", "print",
    "typographic", "typography",
}
# Words that signal 'book' in a clearly printed-book context — only when
# combined with other signals or as standalone original_format == 'book'
PRINTED_BOOK_FORMATS = {"book"}

LANGUAGE_MAP = {
    "hebrew": "he",
    "heb": "he",
    "yiddish": "yi",
    "yid": "yi",
    "aramaic": "arc",
    "judeo-arabic": None,          # Arabic script, out of scope
    "arabic": None,
    "ladino": "lad",               # Ladino in Hebrew script is in scope
    "english": None,               # These are catalog entries, not doc language
    "german": None,
    "french": None,
    "italian": None,
    "portuguese": None,
    "spanish": None,
    "russian": None,
    "polish": None,
    "greek": None,
    "persian": None,
    "turkish": None,
}

DOCTYPE_HINTS = {
    "letter": "letter",
    "letters": "letter",
    "correspondence": "letter",
    "diary": "diary",
    "diaries": "diary",
    "journal": "diary",
    "notebook": "notebook",
    "pinkas": "notebook",
    "pinkasim": "notebook",
    "draft": "draft",
    "speech": "speech",
    "sermon": "speech",
    "receipt": "receipt",
    "poem": "poem",
    "poetry": "poem",
    "piyyut": "poem",
    "piyyutim": "poem",
    "postcard": "postcard",
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_with_retry(url: str, max_retries: int = 4) -> bytes:
    """Fetch with exponential backoff on 429/5xx/IncompleteRead."""
    import http.client
    for attempt in range(max_retries):
        try:
            return http_get(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = SLEEP_ON_429 * (attempt + 1)
                print(f"  [429] Rate limited — sleeping {wait}s …", flush=True)
                time.sleep(wait)
            elif exc.code >= 500:
                wait = 10 * (attempt + 1)
                print(f"  [{exc.code}] Server error — sleeping {wait}s …", flush=True)
                time.sleep(wait)
            else:
                raise
        except (http.client.IncompleteRead, ConnectionResetError, TimeoutError) as exc:
            wait = 5 * (attempt + 1)
            print(f"  [network] {type(exc).__name__} — sleeping {wait}s …", flush=True)
            time.sleep(wait)
    # Final attempt
    return http_get(url)


# ---------------------------------------------------------------------------
# Collection listing
# ---------------------------------------------------------------------------


def fetch_all_results() -> list[dict]:
    """Paginate through the collection API and return all result objects."""
    all_results: list[dict] = []
    page = 1
    while True:
        url = COLLECTION_API.format(page=page)
        print(f"[collection] Fetching page {page}: {url}", flush=True)
        try:
            data = json.loads(fetch_with_retry(url))
        except Exception as exc:
            print(f"  [ERROR] Could not fetch collection page {page}: {exc}", flush=True)
            break

        results = data.get("results", [])
        all_results.extend(results)
        print(f"  Got {len(results)} items (total so far: {len(all_results)})", flush=True)

        pagination = data.get("pagination", {})
        if not pagination.get("next"):
            break
        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_results


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


def parse_date(date_raw: str) -> tuple[Optional[str], str]:
    """
    Parse a raw date string from LoC.
    Returns (date_str, precision) where precision is one of the enum values.

    Examples:
        "1791" → ("1791", "year")
        "13??" → ("1300", "circa")
        "1800-1900" → ("1800/1900", "range")
        "?" → (None, "unknown")
    """
    if not date_raw or date_raw in ("?", "unknown", ""):
        return None, "unknown"

    date_raw = date_raw.strip()

    # Already a clean 4-digit year
    if re.match(r"^\d{4}$", date_raw):
        return date_raw, "year"

    # Year with ? placeholders: "13??" or "19??"
    if re.match(r"^\d{2,4}\?+$", date_raw):
        year = re.sub(r"\?", "0", date_raw)
        return year, "circa"

    # Range: "1800-1900" or "1800/1900"
    m = re.match(r"^(\d{4})[/-](\d{4})$", date_raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}", "range"

    # Just extract first 4-digit number
    m = re.search(r"\d{4}", date_raw)
    if m:
        return m.group(0), "year"

    return date_raw, "unknown"


def extract_year_int(date_str: Optional[str]) -> Optional[int]:
    """Extract the first integer year from a date string."""
    if not date_str:
        return None
    m = re.search(r"\d{4}", date_str)
    return int(m.group(0)) if m else None


# ---------------------------------------------------------------------------
# Scope filter
# ---------------------------------------------------------------------------


def is_in_scope(result: dict) -> tuple[bool, str]:
    """
    Returns (in_scope, reason_if_excluded).
    When in doubt, include.
    """
    title = (result.get("title") or "").lower()
    description_list = result.get("description") or []
    if isinstance(description_list, str):
        description_list = [description_list]
    description = " ".join(description_list).lower()
    subjects = [s.lower() for s in (result.get("subject") or [])]
    original_formats = [f.lower() for f in (result.get("original_format") or [])]

    date_raw = result.get("date") or ""
    date_str, _ = parse_date(date_raw)
    year = extract_year_int(date_str)

    # --- Date filter: exclude if clearly pre-1700 ---
    if year is not None and year < 1700:
        return False, f"pre-1700 date: {date_raw!r}"

    # --- Printed/typeset filter ---
    # Check original_format for 'book' specifically
    if any(f in PRINTED_BOOK_FORMATS for f in original_formats):
        # 'book' format suggests printed — but check whether title/desc also
        # mentions manuscript / handwritten; if not, exclude
        ms_signals = {"manuscript", "handwritten", "handwriting", "cursive"}
        all_text = title + " " + description + " " + " ".join(subjects)
        if not any(sig in all_text for sig in ms_signals):
            return False, f"original_format='book' with no manuscript signals"

    # Check for explicit printed keywords in title/description/subjects
    all_text = title + " " + description + " " + " ".join(subjects)
    for word in EXCLUDE_WORDS:
        if word in all_text:
            # Extra check: if 'manuscript' also appears nearby, don't exclude
            # (LoC often says "not a printed book" in descriptions)
            if "manuscript" in all_text or "handwrit" in all_text:
                continue
            return False, f"printed keyword: {word!r}"

    # --- Language / script filter ---
    languages = [lang.lower() for lang in (result.get("language") or [])]
    # Check if ONLY Arabic-script languages
    if languages:
        mapped = [LANGUAGE_MAP.get(lang, lang) for lang in languages]
        all_none = all(v is None for v in mapped)
        if all_none and "hebrew" not in all_text and "yiddish" not in all_text:
            return False, f"non-Hebrew-script languages: {languages}"

    return True, ""


# ---------------------------------------------------------------------------
# Language mapping
# ---------------------------------------------------------------------------


def map_languages(result: dict, item_detail: dict) -> list[str]:
    """Return ISO 639 language codes for entry."""
    raw_langs: list[str] = []

    # Try item detail first (more precise)
    item = item_detail.get("item", {})
    item_langs = item.get("language") or []
    if item_langs:
        raw_langs = [lang.lower() for lang in item_langs]
    else:
        collection_langs = result.get("language") or []
        raw_langs = [lang.lower() for lang in collection_langs]

    codes = []
    for lang in raw_langs:
        mapped = LANGUAGE_MAP.get(lang)
        if mapped is not None and mapped not in codes:
            codes.append(mapped)
        elif mapped is None:
            # Skip unmapped or explicitly null (Arabic script)
            pass

    # Fallback: if we got nothing but it's a Hebrew manuscript collection, add "he"
    if not codes:
        codes = ["he"]

    return codes


# ---------------------------------------------------------------------------
# Document type inference
# ---------------------------------------------------------------------------


def infer_doc_type(result: dict) -> str:
    title = (result.get("title") or "").lower()
    subjects = [s.lower() for s in (result.get("subject") or [])]
    desc_list = result.get("description") or []
    if isinstance(desc_list, str):
        desc_list = [desc_list]
    description = " ".join(desc_list).lower()

    all_text = title + " " + " ".join(subjects) + " " + description

    for keyword, dtype in DOCTYPE_HINTS.items():
        if keyword in all_text:
            return dtype

    # Ketubah / tena'im / legal docs → "other"
    if any(word in all_text for word in ["ketubah", "ketubbah", "tena'im", "responsa"]):
        return "other"

    return "other"


# ---------------------------------------------------------------------------
# Item slugification
# ---------------------------------------------------------------------------


def item_id_to_slug(item_id: str) -> str:
    """
    Convert a LoC item ID to a slug.
    E.g. "http://www.loc.gov/item/2022397713/" → "2022397713"
    """
    # Strip URL wrapper
    item_id = item_id.strip("/")
    # Take the last path component
    slug = item_id.split("/")[-1]
    # Lower-case, replace non-alphanumeric runs with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    return slug


# ---------------------------------------------------------------------------
# Item detail fetching
# ---------------------------------------------------------------------------


def fetch_item_detail(item_id: str) -> Optional[dict]:
    """Fetch full item detail from LoC item API."""
    url = ITEM_API.format(item_id=item_id)
    try:
        data = fetch_with_retry(url)
        return json.loads(data)
    except Exception as exc:
        print(f"  [WARN] Could not fetch item detail for {item_id}: {exc}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Image selection
# ---------------------------------------------------------------------------


def select_images_for_page(variants: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """
    Given a list of image variant dicts for a single page, return:
      (web_variant, thumbnail_variant)

    We prefer JPEG at 50% or 100% scale for web, and 12.5% for thumbnail.
    """
    jpeg_variants = [
        v for v in variants
        if v.get("mimetype") == "image/jpeg" and v.get("url")
    ]
    if not jpeg_variants:
        return None, None

    # Sort by height descending (largest first)
    jpeg_variants_sorted = sorted(
        jpeg_variants,
        key=lambda v: (v.get("height") or 0),
        reverse=True,
    )

    thumbnail_variant = None
    web_variant = None

    # Choose web: prefer 50% scale (good balance), fallback to next best
    for v in jpeg_variants_sorted:
        h = v.get("height") or 0
        url = v.get("url", "")
        # pct:50 is a good web size
        if "pct:50" in url and not web_variant:
            web_variant = v
        # pct:25 is acceptable fallback
        elif "pct:25" in url and not web_variant:
            web_variant = v

    # If neither found, use the second-largest JPEG (not the massive 100%)
    if not web_variant and len(jpeg_variants_sorted) >= 2:
        web_variant = jpeg_variants_sorted[1]
    elif not web_variant and jpeg_variants_sorted:
        web_variant = jpeg_variants_sorted[0]

    # Choose thumbnail: smallest JPEG
    for v in reversed(jpeg_variants_sorted):
        h = v.get("height") or 0
        if h > 0 and h < 500:
            thumbnail_variant = v
            break
    if not thumbnail_variant and jpeg_variants_sorted:
        thumbnail_variant = jpeg_variants_sorted[-1]  # smallest available

    # Don't return same variant for both
    if thumbnail_variant and web_variant and thumbnail_variant["url"] == web_variant["url"]:
        thumbnail_variant = None

    return web_variant, thumbnail_variant


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_image(url: str, dest: Path) -> Optional[dict]:
    """Download image to dest. Returns {sha256, bytes} or None on failure."""
    if dest.exists() and dest.stat().st_size > 0:
        size = dest.stat().st_size
        sha = sha256_file(dest)
        return {"sha256": sha, "bytes": size}

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = fetch_with_retry(url)
        dest.write_bytes(data)
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
    except Exception as exc:
        print(f"  [ERROR] Download failed for {url}: {exc}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------


def strip_html(text: str) -> str:
    """Very simple HTML tag stripper."""
    return re.sub(r"<[^>]+>", "", text).strip()


def build_entry(
    *,
    result: dict,
    item_detail: dict,
    item_slug: str,
    page_idx: int,       # 0-based
    total_pages: int,
    page_label: Optional[str],
    web_variant: Optional[dict],
    thumb_variant: Optional[dict],
    web_file_info: Optional[dict],
    thumb_file_info: Optional[dict],
    web_local_path: Optional[str],
    thumb_local_path: Optional[str],
    languages: list[str],
) -> dict:
    item = item_detail.get("item", {})

    # entry_id & source_id
    source_id = f"loc__{item_slug}"
    nnnn = str(page_idx + 1).zfill(4)
    entry_id = f"{source_id}__p{nnnn}"

    # title
    title = (
        item.get("title")
        or result.get("title")
        or "Untitled"
    )
    if isinstance(title, list):
        title = title[0]
    title = title.strip()

    # creators
    creators = []
    contributor_names = item.get("contributor_names") or []
    for cn in contributor_names:
        # Skip institutional contributors
        if "library of congress" in cn.lower() or "hebrew manuscripts" in cn.lower():
            continue
        # Try to extract death year
        death_year = None
        m = re.search(r"-(\d{4})\b", cn)
        if m:
            death_year = int(m.group(1))
        # Clean name
        name = re.sub(r",?\s*\d{4}[-–]\d{4}.*$", "", cn).strip()
        name = re.sub(r",?\s*\d{4}[-–].*$", "", name).strip()
        name = re.sub(r",?\s*active.*$", "", name, flags=re.IGNORECASE).strip()
        if not name:
            continue
        creators.append({
            "name": name,
            "role": "author",
            "death_year": death_year,
            "authority_url": None,
        })
    if not creators:
        creators = [{"name": "unknown", "role": "unknown", "death_year": None, "authority_url": None}]

    # date
    date_raw = result.get("date") or item.get("date") or ""
    date_str, date_precision = parse_date(date_raw)

    # call number / shelfmark
    call_numbers = item.get("call_number") or []
    if isinstance(call_numbers, list):
        shelfmark = call_numbers[0] if call_numbers else None
    else:
        shelfmark = str(call_numbers)

    lccn_list = item.get("number_lccn") or []
    if isinstance(lccn_list, list):
        lccn = lccn_list[0] if lccn_list else item_slug
    else:
        lccn = str(lccn_list) if lccn_list else item_slug

    # source_record_id: use call number if available, else LCCN
    source_record_id = shelfmark or lccn or item_slug

    # document type
    doc_type = infer_doc_type(result)

    # handwriting notes
    created_published = item.get("created_published") or []
    if isinstance(created_published, list):
        created_pub_str = created_published[0] if created_published else ""
    else:
        created_pub_str = str(created_published)

    notes_list = item.get("notes") or []
    if isinstance(notes_list, list):
        notes_str = notes_list[0] if notes_list else ""
    else:
        notes_str = str(notes_list)

    hw_notes = f"LoC Hebraic Manuscript"
    if created_pub_str:
        hw_notes += f" — {created_pub_str[:120]}"

    # files
    files = []

    if web_variant and web_local_path:
        files.append({
            "role": "original",
            "local_path": web_local_path,
            "source_url": web_variant["url"],
            "sha256": web_file_info["sha256"] if web_file_info else None,
            "mime_type": web_variant.get("mimetype", "image/jpeg"),
            "bytes": web_file_info["bytes"] if web_file_info else None,
            "width_px": web_variant.get("width") or None,
            "height_px": web_variant.get("height") or None,
        })
    elif web_variant:
        files.append({
            "role": "original",
            "local_path": None,
            "source_url": web_variant["url"],
            "sha256": None,
            "mime_type": web_variant.get("mimetype", "image/jpeg"),
            "bytes": None,
            "width_px": web_variant.get("width") or None,
            "height_px": web_variant.get("height") or None,
        })

    if thumb_variant and thumb_local_path:
        files.append({
            "role": "thumbnail",
            "local_path": thumb_local_path,
            "source_url": thumb_variant["url"],
            "sha256": thumb_file_info["sha256"] if thumb_file_info else None,
            "mime_type": thumb_variant.get("mimetype", "image/jpeg"),
            "bytes": thumb_file_info["bytes"] if thumb_file_info else None,
            "width_px": thumb_variant.get("width") or None,
            "height_px": thumb_variant.get("height") or None,
        })

    # rights evidence — strip HTML from the raw rights string
    rights_list = item.get("rights") or []
    if isinstance(rights_list, list) and rights_list:
        evidence_text = strip_html(rights_list[0])
    elif isinstance(rights_list, str):
        evidence_text = strip_html(rights_list)
    else:
        evidence_text = RIGHTS_EVIDENCE

    entry = {
        "entry_id": entry_id,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "sequence": {
            "index": page_idx,
            "label": page_label or f"p{page_idx + 1}",
            "physical_unit_count": total_pages,
        },
        "title": title,
        "creators": creators,
        "dates": {
            "created": date_str,
            "created_precision": date_precision,
            "accessed_at": TODAY,
        },
        "languages": languages,
        "script": ["Hebr"],
        "document_type": doc_type,
        "handwriting": {
            "extent": "full_page",
            "hebrew_extent": "full_page",
            "notes": hw_notes,
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
            "verified_at": TODAY,
        },
        "provenance": {
            "acquired_at": ACQUIRED_AT,
            "acquired_by": "api_download",
            "source_landing_url": f"https://www.loc.gov/item/{lccn}/",
            "notes": "Downloaded via Library of Congress JSON API.",
        },
        "holding_institution": "Library of Congress",
        "holding_shelfmark": shelfmark,
        "quality": {
            "usable_for_htr": True,
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

    return entry


# ---------------------------------------------------------------------------
# Per-item processing
# ---------------------------------------------------------------------------


def process_item(
    result: dict,
    entries_out: list,
    failures: list,
    dry_run: bool = False,
) -> int:
    item_url = result.get("url") or result.get("id") or ""
    item_url = item_url.rstrip("/")
    item_id = item_url.split("/")[-1]
    item_slug = item_id_to_slug(item_url)

    print(f"\n  [{item_slug}] Fetching item detail …", flush=True)
    item_detail = fetch_item_detail(item_id)
    if not item_detail:
        failures.append({"item_slug": item_slug, "reason": "item detail fetch failed"})
        return 0

    # Get resources/files
    resources = item_detail.get("resources") or []
    if not resources:
        print(f"  [{item_slug}] No resources found — skipping", flush=True)
        failures.append({"item_slug": item_slug, "reason": "no resources"})
        return 0

    resource = resources[0]
    if resource.get("download_restricted"):
        print(f"  [{item_slug}] Download restricted — skipping", flush=True)
        failures.append({"item_slug": item_slug, "reason": "download_restricted"})
        return 0

    pages_list = resource.get("files") or []
    if not pages_list:
        print(f"  [{item_slug}] No files in resource — skipping", flush=True)
        failures.append({"item_slug": item_slug, "reason": "no files"})
        return 0

    total_pages = len(pages_list)
    pages_to_process = pages_list[:MAX_PAGES_PER_ITEM]

    # Languages
    languages = map_languages(result, item_detail)

    scan_dir = SCANS_DIR / f"loc__{item_slug}"
    if not dry_run:
        scan_dir.mkdir(parents=True, exist_ok=True)

    source_id = f"loc__{item_slug}"
    entries_created = 0

    for page_idx, page_variants in enumerate(pages_to_process):
        if not isinstance(page_variants, list):
            print(f"  [{item_slug}] page {page_idx}: unexpected format — skipping", flush=True)
            continue

        web_variant, thumb_variant = select_images_for_page(page_variants)
        if not web_variant:
            print(f"  [{item_slug}] page {page_idx}: no usable JPEG — skipping", flush=True)
            continue

        nnnn = str(page_idx + 1).zfill(4)
        web_local: Optional[Path] = scan_dir / f"web_p{nnnn}.jpg"
        thumb_local: Optional[Path] = (scan_dir / f"thumb_p{nnnn}.jpg") if thumb_variant else None

        web_file_info: Optional[dict] = None
        thumb_file_info: Optional[dict] = None
        web_local_str: Optional[str] = None
        thumb_local_str: Optional[str] = None

        if not dry_run:
            web_file_info = download_image(web_variant["url"], web_local)
            if web_file_info:
                web_local_str = str(web_local.relative_to(REPO_ROOT))
                print(
                    f"  [{item_slug}] p{nnnn}: web OK "
                    f"({web_file_info['bytes']:,} bytes, "
                    f"{web_variant.get('width')}x{web_variant.get('height')})",
                    flush=True,
                )
            else:
                web_local = None

            if thumb_variant and thumb_local:
                thumb_file_info = download_image(thumb_variant["url"], thumb_local)
                if thumb_file_info:
                    thumb_local_str = str(thumb_local.relative_to(REPO_ROOT))
                else:
                    thumb_local = None

            # Small pause between pages
            if page_idx > 0:
                time.sleep(0.2)
        else:
            print(f"  [dry-run] [{item_slug}] p{nnnn}: would download {web_variant['url']}")

        # page_label: LoC doesn't provide page labels in the files array,
        # so we generate them
        page_label = f"p{page_idx + 1}"

        entry = build_entry(
            result=result,
            item_detail=item_detail,
            item_slug=item_slug,
            page_idx=page_idx,
            total_pages=total_pages,
            page_label=page_label,
            web_variant=web_variant,
            thumb_variant=thumb_variant,
            web_file_info=web_file_info,
            thumb_file_info=thumb_file_info,
            web_local_path=web_local_str if not dry_run else None,
            thumb_local_path=thumb_local_str if not dry_run else None,
            languages=languages,
        )

        # Basic sanity check: must have at least one file entry
        if not entry["files"]:
            print(f"  [{item_slug}] p{nnnn}: no file entries — skipping entry", flush=True)
            continue

        entries_out.append(entry)
        entries_created += 1

    return entries_created


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_entries(entries: list[dict]) -> list[str]:
    """Validate entries against the JSON schema. Returns list of error messages."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        print("[WARN] jsonschema not installed — skipping validation", flush=True)
        return []

    schema_path = REPO_ROOT / "schemas" / "entry.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    errors = []
    for entry in entries:
        entry_id = entry.get("entry_id", "<unknown>")
        errs = sorted(validator.iter_errors(entry), key=lambda e: list(e.path))
        for err in errs:
            location = ".".join(str(p) for p in err.path) or "<root>"
            errors.append(f"{entry_id}: {location}: {err.message}")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest LoC Hebraic Manuscripts")
    parser.add_argument("--dry-run", action="store_true", help="Don't download or write files")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N items")
    args = parser.parse_args()

    print("=" * 60)
    print("LoC Hebraic Manuscripts Ingest")
    print("=" * 60)

    # Step 1: Fetch all results
    all_results = fetch_all_results()
    print(f"\nTotal results fetched: {len(all_results)}", flush=True)

    # Step 2: Filter in-scope items
    in_scope: list[dict] = []
    excluded: list[tuple[str, str]] = []
    for r in all_results:
        ok, reason = is_in_scope(r)
        if ok:
            in_scope.append(r)
        else:
            item_id = (r.get("url") or r.get("id") or "?").rstrip("/").split("/")[-1]
            excluded.append((item_id, reason))
            print(f"  [SKIP] {item_id}: {reason}", flush=True)

    print(f"\nIn scope: {len(in_scope)} / {len(all_results)}")
    print(f"Excluded: {len(excluded)}")

    if args.limit:
        in_scope = in_scope[: args.limit]
        print(f"(--limit {args.limit} applied)", flush=True)

    # Step 3: Process each item
    entries_all: list[dict] = []
    failures: list[dict] = []
    total_entries = 0

    for i, result in enumerate(in_scope, 1):
        item_id = (result.get("url") or result.get("id") or "?").rstrip("/").split("/")[-1]
        print(f"\n[{i}/{len(in_scope)}] {item_id} — {result.get('title', '?')[:60]}", flush=True)

        try:
            n = process_item(result, entries_all, failures, dry_run=args.dry_run)
            total_entries += n
        except Exception as exc:
            print(f"  [ERROR] Unhandled exception for {item_id}: {exc}", flush=True)
            failures.append({"item_slug": item_id, "reason": str(exc)})

        time.sleep(SLEEP_BETWEEN_ITEMS)

    # Step 4: Validate
    print(f"\nValidating {len(entries_all)} entries …", flush=True)
    errors = validate_entries(entries_all)
    if errors:
        print(f"VALIDATION ERRORS ({len(errors)}):")
        for err in errors[:20]:
            print(f"  {err}")
        if len(errors) > 20:
            print(f"  … and {len(errors) - 20} more")
    else:
        print("All entries valid.")

    # Step 5: Write output
    if not args.dry_run:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fout:
            for entry in entries_all:
                fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"\nWrote {len(entries_all)} entries to {OUTPUT_FILE}", flush=True)
    else:
        print(f"\n[dry-run] Would write {len(entries_all)} entries to {OUTPUT_FILE}", flush=True)

    # Summary
    web_ok = sum(
        1
        for e in entries_all
        for f in e.get("files", [])
        if f["role"] == "original" and f.get("sha256") is not None
    )
    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  Total results from API:  {len(all_results)}")
    print(f"  Excluded (out of scope): {len(excluded)}")
    print(f"  Items processed:         {len(in_scope) - len(failures)}")
    print(f"  Failures:                {len(failures)}")
    print(f"  Entries written:         {len(entries_all)}")
    print(f"  Web images downloaded:   {web_ok}")
    if errors:
        print(f"  Validation errors:       {len(errors)}")
    print(f"  Output:                  {OUTPUT_FILE}")
    if failures:
        print("\nFailures:")
        for f in failures[:20]:
            print(f"  - {f.get('item_slug')}: {f.get('reason')}")
        if len(failures) > 20:
            print(f"  … and {len(failures) - 20} more")
    print("=" * 60)


if __name__ == "__main__":
    main()
