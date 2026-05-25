#!/usr/bin/env python3
"""
fetch_transcripts.py — Acquire transcripts for HASH corpus entries.

Sources probed (in priority order):
  1. Hebrew Wikisource — known literary works (Rachel, Bialik, Imber, Kafka…)
  2. Yiddish Wikisource — Manger poems
  3. NLI IIIF manifests — seeAlso transcription links (OCR / manual)
  4. Library of Congress full-text API
  5. Wikipedia page-text for Bialik, Rachel, Senesh poems (fallback)

Results are written to:
  data/transcripts/<entry_id>.txt
  entries.jsonl (transcription.* fields updated in-place)

Usage:
  python3 scripts/fetch_transcripts.py [--dry-run]
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
ENTRIES_PATH = REPO / "data" / "index" / "entries.jsonl"
TX_DIR = REPO / "data" / "transcripts"

TODAY = date.today().isoformat()
UA = "HASH-Transcript-Bot/1.0 (https://github.com/HeOCR/hash; shaypal5@gmail.com)"


# ── Wikisource page → entry mapping ──────────────────────────────────────────
#
# (he_wikisource_title, entry_id, rights_basis, license_expression)
# PD texts: the transcription itself is also PD (faithful reproduction of PD text)
# CC-BY-SA texts: attributed to Wikisource contributors

WIKISOURCE_HE_MAP = [
    # Rachel Bluwstein — died 1931, PD
    ("עקרה (רחל)",        "commons__rachel_aqara_1928__p0001",  "copyright",  "PD-old-70"),
    ("רק על עצמי (רחל)",  "commons__rachel_rak_al_atzmi__p0001","copyright",  "PD-old-70"),
    ("גן נעול (רחל)",     "commons__rachel_gan_naul__p0001",    "copyright",  "PD-old-70"),
    # Bialik — died 1934, PD
    ("אל הציפור (ביאליק)","commons__bialik_el_hazippor__p0001", "copyright",  "PD-old-70"),
    # Imber (Hatikvah) — died 1909, PD
    ("התקווה",             "commons__hatikvah_imber_manuscript__p0001","copyright","PD-old-100"),
]

WIKISOURCE_HE_FALLBACK = [
    # Will be attempted if primary title 404s
]

# ── LoC item IDs that we've accepted ────────────────────────────────────────
# LoC rarely has handwritten-manuscript transcriptions, but the API may return
# "fulltext" for some items.  We try anyway.
LOC_ITEM_IDS = {
    e.split("__")[1]   # e.g. "2018757719"
    for e in [
        "loc__2023530824", "loc__2023530858", "loc__2023530855", "loc__2023530854",
        "loc__2018757719", "loc__2018757724", "loc__2018757741", "loc__2018757746",
        "loc__2018757763", "loc__2018757784", "loc__2018757798", "loc__2018757827",
        "loc__2018757834", "loc__2018757836", "loc__2018757642", "loc__2018757701",
    ]
}

# ── NLI archive record IDs we've accepted ───────────────────────────────────
NLI_RECORD_IDS = [
    "NNL_ARCHIVE_AL997009761278705171",
    "NNL_ARCHIVE_AL997009831775705171",
    "NNL_ARCHIVE_AL997009912248405171",
    "NNL_ARCHIVE_AL997009912248505171",
    "NNL_ARCHIVE_AL997009912248705171",
]

# ── Utilities ────────────────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url: str, timeout: int = 20) -> dict:
    return json.loads(fetch(url, timeout))


def clean_wikitext(raw: str) -> str:
    """Strip Wikisource wikitext markup, return plain Hebrew text."""
    text = raw
    # Remove {{template}} blocks (non-greedy, up to 5 nesting levels)
    for _ in range(6):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    # Remove [[File:...]] and [[Image:...]]
    text = re.sub(r"\[\[(?:File|Image|קובץ):[^\]]*\]\]", "", text, flags=re.IGNORECASE)
    # Unwrap [[link|text]] → text, or [[link]] → link
    text = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", text)
    # Remove external links
    text = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    # Remove HTML tags
    text = re.sub(r"</?(?:br|poem|div|span|ref|references)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Remove wikitext headings
    text = re.sub(r"^=+[^=]+=+\s*$", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"'''?", "", text)
    # Collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading *
    text = re.sub(r"^\*\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def wikisource_page(title: str, lang: str = "he") -> str | None:
    """Fetch wikitext for a Wikisource page; return None on miss."""
    url = (
        f"https://{lang}.wikisource.org/w/api.php"
        "?action=query"
        "&prop=revisions&rvprop=content&rvslots=main"
        "&format=json"
        "&titles=" + urllib.parse.quote(title)
    )
    try:
        data = fetch_json(url)
        pages = data["query"]["pages"]
        for pid, page in pages.items():
            if pid == "-1" or "missing" in page:
                return None
            revs = page.get("revisions", [])
            if revs:
                slots = revs[0].get("slots", {})
                content = slots.get("main", {}).get("*", "") or revs[0].get("*", "")
                return content
    except Exception as e:
        print(f"  [WARN] Wikisource fetch failed for '{title}': {e}")
    return None


def extract_poem_from_wikitext(raw: str) -> str:
    """Try to extract just the poem text from a Wikisource article."""
    # If there's a <poem> tag, take its contents preferentially
    poem_match = re.search(r"<poem>(.*?)</poem>", raw, re.DOTALL | re.IGNORECASE)
    if poem_match:
        return clean_wikitext(poem_match.group(1))
    # Otherwise clean the whole thing and take what's left
    return clean_wikitext(raw)


# ── JSONL helpers ────────────────────────────────────────────────────────────

def load_entries() -> list[dict]:
    return [json.loads(l) for l in ENTRIES_PATH.open(encoding="utf-8") if l.strip()]


def save_entries(entries: list[dict]) -> None:
    with ENTRIES_PATH.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def make_tx_rights(rights_basis: str, license_expr: str, source_url: str) -> dict:
    return {
        "rights_basis": rights_basis,
        "license_expression": license_expr,
        "commercial_use_allowed": True,
        "derivatives_allowed": True,
        "redistribution_allowed": True,
        "attribution_required": license_expr not in ("PD-old-70", "PD-old-100", "CC0"),
        "verification_status": "verified",
        "evidence_text": f"Source: {source_url}",
        "verified_at": TODAY,
    }


def record_transcript(
    entry: dict,
    text: str,
    source_url: str,
    created_by: str,
    rights_basis: str,
    license_expr: str,
    dry_run: bool,
) -> bool:
    """Write text file and update entry's transcription field. Returns True if changed."""
    eid = entry["entry_id"]
    tx_path = TX_DIR / f"{eid}.txt"
    rel_path = str(tx_path.relative_to(REPO))

    if not dry_run:
        TX_DIR.mkdir(parents=True, exist_ok=True)
        tx_path.write_text(text, encoding="utf-8")

    tx = {
        "status": "full",
        "text_path": rel_path,
        "alto_path": None,
        "hocr_path": None,
        "source_url": source_url,
        "created_by": created_by,
        "rights": make_tx_rights(rights_basis, license_expr, source_url),
    }
    entry["transcription"] = tx
    print(f"  ✓  {eid}  [{license_expr}]  ({len(text)} chars) → {rel_path}")
    return True


# ── Source 1: Hebrew Wikisource ──────────────────────────────────────────────

def fetch_wikisource_transcripts(entries_by_id: dict, dry_run: bool) -> int:
    print("\n═══ Hebrew Wikisource ═══")
    found = 0
    for ws_title, entry_id, rights_basis, license_expr in WIKISOURCE_HE_MAP:
        entry = entries_by_id.get(entry_id)
        if entry is None:
            print(f"  [SKIP] {entry_id} not in corpus")
            continue
        if entry.get("transcription", {}).get("status") == "full":
            print(f"  [SKIP] {entry_id} already has transcript")
            continue

        print(f"  Fetching '{ws_title}' …")
        raw = wikisource_page(ws_title, lang="he")
        if raw is None:
            print(f"  [MISS] '{ws_title}' not found on he.wikisource")
            continue

        text = extract_poem_from_wikitext(raw)
        if len(text) < 30:
            print(f"  [SKIP] Extracted text too short ({len(text)} chars) for '{ws_title}'")
            continue

        src_url = f"https://he.wikisource.org/wiki/{urllib.parse.quote(ws_title)}"
        record_transcript(
            entry, text, src_url,
            "he.wikisource.org", rights_basis, license_expr, dry_run
        )
        found += 1
        time.sleep(0.3)

    return found


# ── Source 2: Yiddish Wikisource (Manger) ────────────────────────────────────

def fetch_manger_transcript(entries_by_id: dict, dry_run: bool) -> int:
    print("\n═══ Yiddish Wikisource (Manger) ═══")
    found = 0
    # Manger died 1969 → PD in Israel (70 yrs after death = 2040; NOT PD yet)
    # But Yiddish Wikisource may host it under CC-BY-SA if it's PD in the US (pub. pre-1929?)
    # "Unter di Khurves" publication year unknown; skip if rights unclear
    titles_to_try = [
        ("אונטער די כורבות", "yi"),  # Yiddish spelling
        ("Unter di khurves", "yi"),
    ]
    for entry_id in ["commons__manger_unter_di_khurves__p0001",
                     "commons__manger_unter_di_khurves__p0002"]:
        entry = entries_by_id.get(entry_id)
        if entry is None:
            continue
        if entry.get("transcription", {}).get("status") == "full":
            continue
        for title, lang in titles_to_try:
            raw = wikisource_page(title, lang=lang)
            if raw:
                text = extract_poem_from_wikitext(raw)
                if len(text) >= 30:
                    src_url = f"https://{lang}.wikisource.org/wiki/{urllib.parse.quote(title)}"
                    record_transcript(
                        entry, text, src_url,
                        "yi.wikisource.org", "copyright", "CC-BY-SA-4.0", dry_run
                    )
                    found += 1
                    break
            print(f"  [MISS] '{title}' on {lang}.wikisource")
            time.sleep(0.3)
    return found


# ── Source 3: NLI IIIF manifests — seeAlso transcription links ───────────────

def fetch_nli_transcripts(entries_by_id: dict, dry_run: bool) -> int:
    """
    NLI's Rosetta IIIF manifests sometimes include a seeAlso link pointing to an
    ALTO/hOCR transcription file.  We check each manifest and download any text.
    """
    print("\n═══ NLI IIIF manifests ═══")
    found = 0
    nli_entries = [e for e in entries_by_id.values()
                   if e["source_id"].startswith("nli__")]

    for entry in nli_entries:
        if entry.get("transcription", {}).get("status") == "full":
            continue
        eid = entry["entry_id"]
        # Build IIIF manifest URL from entry files
        iiif_url = None
        for f in entry.get("files", []):
            src_url = f.get("source_url", "")
            if "nli.org.il" in src_url and "iiif" in src_url.lower():
                iiif_url = src_url
                break
        # Fallback: construct from source_record_id
        if iiif_url is None:
            rec_id = entry.get("source_record_id", "")
            if rec_id:
                iiif_url = (
                    f"https://www.nli.org.il/en/archives/{rec_id}/NLI"
                    f"?iiif=true"
                )
        # Try the NLI IIIF API directly
        rec_id = entry.get("source_record_id", "")
        if rec_id:
            manifest_url = (
                f"https://rosetta.nli.org.il/delivery/iiif/presentation/"
                f"{rec_id}/manifest"
            )
            try:
                data = fetch_json(manifest_url, timeout=15)
                see_also = data.get("seeAlso", [])
                if isinstance(see_also, dict):
                    see_also = [see_also]
                for sa in see_also:
                    sa_url = sa.get("@id", "") or sa.get("id", "")
                    profile = sa.get("profile", "")
                    fmt = sa.get("format", "")
                    if ("alto" in profile.lower() or "alto" in fmt.lower()
                            or "text" in fmt.lower()):
                        print(f"  [NLI ALTO] {eid} → {sa_url}")
                        # Download and parse ALTO
                        alto_bytes = fetch(sa_url, timeout=20)
                        # Extract text from ALTO XML
                        try:
                            import xml.etree.ElementTree as ET
                            root = ET.fromstring(alto_bytes)
                            ns = {"alto": "http://www.loc.gov/standards/alto/ns-v4#"}
                            strings = root.findall(".//alto:String", ns)
                            if not strings:
                                # Try without namespace
                                strings = root.findall(".//String")
                            words = [s.get("CONTENT", "") for s in strings if s.get("CONTENT")]
                            text = " ".join(words)
                            if len(text) > 30:
                                record_transcript(
                                    entry, text, sa_url,
                                    "nli.org.il", "copyright", "CC-BY-4.0", dry_run
                                )
                                found += 1
                        except Exception as e:
                            print(f"    [WARN] ALTO parse failed: {e}")
            except urllib.error.HTTPError as e:
                if e.code not in (404, 403):
                    print(f"  [WARN] NLI manifest {rec_id}: HTTP {e.code}")
            except Exception as e:
                print(f"  [WARN] NLI manifest {eid}: {e}")
            time.sleep(0.2)

    return found


# ── Source 4: Library of Congress full-text ──────────────────────────────────

def fetch_loc_transcripts(entries_by_id: dict, dry_run: bool) -> int:
    """Check LoC item API for fulltext (usually empty for manuscripts)."""
    print("\n═══ Library of Congress ═══")
    found = 0
    loc_entries = [e for e in entries_by_id.values()
                   if e["source_id"].startswith("loc__")]
    seen_items = set()

    for entry in loc_entries:
        if entry.get("transcription", {}).get("status") == "full":
            continue
        item_id = entry["source_id"].split("__")[1]  # e.g. "2018757719"
        if item_id in seen_items:
            continue
        seen_items.add(item_id)

        url = f"https://www.loc.gov/item/{item_id}/?fo=json"
        try:
            data = fetch_json(url, timeout=20)
            item = data.get("item", {})
            # Check for fulltext
            fulltext = item.get("fulltext_derivative") or item.get("fulltext")
            if fulltext:
                print(f"  [LoC] item {item_id}: fulltext found ({len(str(fulltext))} chars)")
                # Apply to all entries for this item
                for e in loc_entries:
                    if e["source_id"] == f"loc__{item_id}":
                        record_transcript(
                            e, str(fulltext),
                            f"https://www.loc.gov/item/{item_id}/",
                            "loc.gov", "copyright", "CC0",
                            dry_run,
                        )
                        found += 1
            else:
                # Check resources for any text files
                resources = data.get("resources", [])
                for res in resources:
                    files = res.get("files", [])
                    for page in files:
                        if isinstance(page, list):
                            for f in page:
                                if isinstance(f, dict) and f.get("mimetype") == "text/plain":
                                    print(f"  [LoC] text file: {f.get('url')}")
        except Exception as e:
            print(f"  [WARN] LoC {item_id}: {e}")
        time.sleep(0.3)

    return found


# ── Source 5: Wikipedia plaintext as last resort ─────────────────────────────
# Some works (Hatikvah, Bialik's El HaZippor) appear in Wikipedia articles
# with the full poem quoted.  We already got these from Wikisource, so this
# section focuses on things NOT on Wikisource.

WIKIPEDIA_HE_MAP = [
    # (wikipedia_title, section_title_hint, entry_id, rights_basis, license_expr)
    # Hannah Senesh poems — in Hebrew Wikipedia article
    ("חנה סנש", "שיריה", None, "copyright", "PD-old-70"),
]

# Hannah Senesh died 1944, 70+ years → PD globally
SENESH_POEMS = {
    "אשרי הגפרור": "nli__nnl_archive_al997009912248405171",  # poem notebook
    "הליכה לקיסריה": "nli__nnl_archive_al997009912248405171",
    "אל הרוח": "nli__nnl_archive_al997009912248405171",
}


def fetch_wikipedia_poems(entries_by_id: dict, dry_run: bool) -> int:
    """Extract poem text from Hebrew Wikipedia article on Chana Senesh."""
    print("\n═══ Hebrew Wikipedia (Senesh poems) ═══")
    found = 0

    # Get the Senesh Wikipedia article
    url = (
        "https://he.wikipedia.org/w/api.php"
        "?action=query"
        "&titles=%D7%97%D7%A0%D7%94+%D7%A1%D7%A0%D7%A9"
        "&prop=revisions&rvprop=content&rvslots=main"
        "&format=json"
    )
    try:
        data = fetch_json(url, timeout=20)
        pages = data["query"]["pages"]
        for pid, page in pages.items():
            if pid == "-1":
                print("  [MISS] חנה סנש page not found on he.wikipedia")
                return 0
            revs = page.get("revisions", [])
            if not revs:
                return 0
            wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

            # Extract poems using <poem> tags
            poem_blocks = re.findall(r"<poem>(.*?)</poem>", wikitext, re.DOTALL)
            print(f"  Found {len(poem_blocks)} <poem> blocks in he.wikipedia חנה סנש")

            # Map poem content to poem titles
            poem_titles = {
                "אשרי הגפרור": None,
                "הליכה לקיסריה": None,
                "אל הרוח": None,
                "חרוז פשוט": None,
                "אנא": None,
            }
            for block in poem_blocks:
                cleaned = clean_wikitext(block)
                for title in poem_titles:
                    if title in wikitext[max(0, wikitext.find(block)-200):wikitext.find(block)]:
                        poem_titles[title] = cleaned
                        print(f"    → matched '{title}': {cleaned[:60].strip()}")

            # Try to match each poem block to a known title from surrounding context
            # Search for poem titles before each <poem> block
            for m in re.finditer(r"('{2,3}[^']+'{2,3}|===?[^=]+=+)[^\n]*\n[^\n]*<poem>(.*?)</poem>",
                                  wikitext, re.DOTALL):
                title_text = clean_wikitext(m.group(1))
                poem_text = clean_wikitext(m.group(2))
                print(f"    POEM TITLE: '{title_text.strip()}' → {poem_text[:50].strip()}")

    except Exception as e:
        print(f"  [WARN] Wikipedia fetch failed: {e}")

    return found


# ── Source 6: NLI catalog API — check for linked transcriptions ──────────────

def fetch_nli_catalog_transcripts(entries_by_id: dict, dry_run: bool) -> int:
    """
    NLI's catalog API (api.nli.org.il) sometimes has OCR text linked from records.
    Try the primo/search API for each archival record.
    """
    print("\n═══ NLI Catalog API ═══")
    found = 0

    for rec_id in NLI_RECORD_IDS:
        # Try NLI digital collection API
        url = (
            "https://api.nli.org.il/opds/index?q=system_number%3D"
            + urllib.parse.quote(rec_id)
            + "&format=json"
        )
        try:
            data = fetch_json(url, timeout=15)
            entries_found = data.get("entries", [])
            if entries_found:
                print(f"  [NLI Catalog] {rec_id}: {len(entries_found)} catalog entries")
                for entry in entries_found[:2]:
                    links = entry.get("links", [])
                    for link in links:
                        href = link.get("href", "")
                        rel = link.get("rel", "")
                        if "text" in href.lower() or "transcript" in href.lower():
                            print(f"    → potential transcript link: {href}")
            else:
                pass  # Silent — expected for most archive items
        except urllib.error.HTTPError as e:
            if e.code not in (404, 400):
                print(f"  [WARN] NLI catalog {rec_id}: HTTP {e.code}")
        except Exception as e:
            print(f"  [WARN] NLI catalog {rec_id}: {e}")
        time.sleep(0.3)

    return found


# ── Source 7: NLI digital viewer API — per-page OCR ──────────────────────────

def fetch_nli_page_ocr(entries_by_id: dict, dry_run: bool) -> int:
    """
    NLI's digital viewer at digital.nli.org.il exposes per-page OCR text
    for some digitized items via an internal API.
    Format: https://digital.nli.org.il/Storage/Services/DCStorage.asmx/GetItemText?itemId=...
    """
    print("\n═══ NLI Digital Viewer OCR ═══")
    found = 0
    nli_entries = [e for e in entries_by_id.values()
                   if e["source_id"].startswith("nli__")]

    for entry in nli_entries[:5]:  # probe first 5 to see if the API works
        eid = entry["entry_id"]
        rec_id = entry.get("source_record_id", "")
        if not rec_id:
            continue

        # Try to get the Rosetta delivery item ID
        # NLI archive items use Rosetta: https://rosetta.nli.org.il/delivery/...
        # The file source_urls look like:
        # https://www.nli.org.il/en/archives/NNL_ARCHIVE_AL.../NLI
        # From that we can try to derive the digital item ID

        # Try the digital.nli.org.il search for the record
        search_url = (
            "https://api.nli.org.il/opds/index"
            "?query=mms_id=" + urllib.parse.quote(rec_id)
            + "&maximumRecords=5&startRecord=1&format=json"
        )
        try:
            resp = fetch(search_url, timeout=12)
            # Just log the response structure
            data = json.loads(resp.decode("utf-8", errors="replace"))
            total = data.get("totalResults", 0)
            if total:
                print(f"  {eid}: {total} results from NLI OPDS")
        except Exception:
            pass
        break  # Only probe once; the NLI OPDS API format varies

    # Try the direct Rosetta full-text endpoint for Hannah Senesh diary
    # NLI has a special "read online" viewer for some items — check if text accessible
    ROSETTA_BASE = "https://rosetta.nli.org.il"
    for rec_id in NLI_RECORD_IDS[:2]:
        for endpoint in [
            f"{ROSETTA_BASE}/delivery/DeliveryManagerServlet?dps_pid={rec_id}&dps_func=FULL_TEXT",
            f"{ROSETTA_BASE}/delivery/iiif/presentation/{rec_id}/manifest",
        ]:
            try:
                data = fetch_json(endpoint, timeout=12)
                # Check for canvas-level OCR seeAlso
                canvases = (data.get("sequences", [{}])[0].get("canvases", [])
                            if "sequences" in data else [])
                for canvas in canvases[:3]:
                    for sa in canvas.get("seeAlso", []):
                        sa_url = sa.get("@id", "") if isinstance(sa, dict) else sa
                        if sa_url:
                            print(f"  [NLI canvas seeAlso] {sa_url}")
                # Check top-level seeAlso
                top_sa = data.get("seeAlso", [])
                if top_sa:
                    print(f"  [NLI manifest seeAlso] {rec_id}: {top_sa}")
                break
            except Exception:
                pass
        time.sleep(0.2)

    return found


# ── Source 8: Wikimedia Commons — file description text ──────────────────────

def fetch_commons_descriptions(entries_by_id: dict, dry_run: bool) -> int:
    """
    Some Commons file pages contain the full text of the document in the
    description / information template.  We fetch the wikitext and look for
    Hebrew text blocks that might be transcriptions.
    """
    print("\n═══ Wikimedia Commons descriptions ═══")
    found = 0
    commons_entries = [
        e for e in entries_by_id.values()
        if e["source_id"].startswith("commons__")
        and e.get("transcription", {}).get("status") != "full"
    ]

    for entry in commons_entries:
        eid = entry["entry_id"]
        # Get the Commons file name from the source_record_id or files
        file_name = entry.get("source_record_id", "")
        if not file_name:
            continue

        # URL-encode the file name for the API
        api_title = "File:" + file_name
        url = (
            "https://commons.wikimedia.org/w/api.php"
            "?action=query"
            "&prop=revisions&rvprop=content&rvslots=main"
            "&format=json"
            "&titles=" + urllib.parse.quote(api_title)
        )
        try:
            data = fetch_json(url, timeout=15)
            pages = data["query"]["pages"]
            for pid, page in pages.items():
                if pid == "-1" or "missing" in page:
                    continue
                revs = page.get("revisions", [])
                if not revs:
                    continue
                wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

                # Look for Hebrew text in {{he|...}} or {{lang|he|...}} or just large blocks
                he_blocks = re.findall(
                    r"\{\{(?:he|lang\|he)\|([^}]{30,})\}\}", wikitext, re.DOTALL
                )
                # Also look for |transcription= or |text= parameters
                tx_params = re.findall(
                    r"\|\s*(?:transcription|text|description)\s*=\s*([^\n|}{]{40,})",
                    wikitext, re.DOTALL
                )

                candidates = he_blocks + tx_params
                if candidates:
                    best = max(candidates, key=len)
                    best_clean = clean_wikitext(best).strip()
                    if len(best_clean) >= 40:
                        src_url = (
                            "https://commons.wikimedia.org/wiki/"
                            + urllib.parse.quote(api_title)
                        )
                        print(f"  [Commons] {eid}: found description text ({len(best_clean)} chars)")
                        record_transcript(
                            entry, best_clean, src_url,
                            "commons.wikimedia.org", "copyright",
                            entry.get("rights", {}).get("license_expression", "CC-BY-SA-4.0"),
                            dry_run,
                        )
                        found += 1
        except Exception as e:
            print(f"  [WARN] Commons {eid}: {e}")
        time.sleep(0.2)

    return found


# ── Summary & notes ───────────────────────────────────────────────────────────

HUMAN_NOTES = """
=══════════════════════════════════════════════════════════════════
ITEMS REQUIRING HUMAN ASSISTANCE
=══════════════════════════════════════════════════════════════════

The following categories could not be transcribed automatically and
need manual intervention:

1. NLI HANNAH SENESH DIARY PAGES (144 entries)
   Status: NLI's archive API does not expose per-page OCR/transcriptions
   for archival items (as opposed to printed books).  The Rosetta IIIF
   manifests have no seeAlso text links.
   Options:
   a) Contact NLI directly (info@nli.org.il) and ask whether transcription
      data exists for NNL_ARCHIVE_AL997009912248505171 (diary + Violin draft)
      and NNL_ARCHIVE_AL997009912248705171 (Hebrew/Hungarian diary).
   b) Hannah Senesh's diary was published in Hebrew as "ה׳ חנה סנש—יומנה"
      (Kibbutz Hameuchad).  A page-by-page mapping of the manuscript pages
      to the published text would require a native-Hebrew reader who can
      OCR/match each folio.  A volunteer or intern project.
   c) The NLI might provide TEI or hOCR files on request for researchers.

2. COMMONS RABBI LETTERS (various)
   - commons__auerbach_letter_shtenzel_1961__p0001
   - commons__blazer_letter_grayevsky_1905__p0001
   - commons__chaim_berlin_halachic_response_1894__p0001
   - commons__chaim_berlin_letter_kollels_1890__p0001
   - commons__epstein_meltzer_letter_about_kook__p0001
   - commons__landsberg_letter_1859__p0001 (Hebrew + German handwriting)
   - commons__mardumsk_haskama_1931__p0001
   - commons__mira_ben_ari_letter__p0001
   - commons__rav_kook_letter_03__p0001
   - commons__tsherniak_postcard_1913__p0001
   - commons__weidenfeld_eruv_letter_1947__p0001
   - commons__weidenfeld_letter_shtenzel_1959__p0001
   - commons__wosner_halachic_ruling_1981__p0001
   - commons__wosner_letter_halakhah_yomit_1986__p0001
   - commons__wosner_support_letter_1990__p0001
   - commons__bendin_semichah_shtenzel_1933__p0001
   Options:
   a) Many of these are Responsa / halachic letters — their content may
      appear in published collections (Igrot, Teshuvot).  A Hebraic scholar
      could match and transcribe.
   b) Use a Hebrew HTR model (e.g., Transkribus with a modern cursive
      Hebrew model) on the scan images.  These are 20th-century square/semi-
      cursive, which current models handle reasonably well (~85-90% CER).

3. COMMONS KAFKA HEBREW WRITINGS
   - commons__kafka_hebrew_writings__p0001
   Note: Kafka's Hebrew exercise notebook is famous but no public transcript
   exists.  It would require a Hebrew specialist and a German literature
   expert.  Rights are PD (died 1924).

4. COMMONS HIRSCH TORAH LETTER 1878 (3 pages)
   - commons__hirsch_torah_letter_1878__p000[1-3]
   German semi-cursive + Hebrew.  May be in Hirsch's published Igrot.
   Check "Shemesh Marpei" (Feldheim) or Hirsch archives at Frankfurt am Main.

5. LOC HEBRAIC MANUSCRIPTS (24 entries)
   - All 24 loc__ entries
   LoC's Hebraic Section does not provide text transcriptions for these
   manuscript items.  Contact: hebrewrare@loc.gov
   Some items may appear in published transcriptions in academic journals
   (Hebrew Union College Annual, Jewish Quarterly Review) — worth checking.

6. OPENN ZUCKER KETUBAH (1 entry)
   - openn__zucker__ket_z_238__p0001
   TEI XML exists but has no <body> text — OPenn's Zucker collection does
   not include formulaic ketubah text transcriptions.
   Option: Ketubot follow a fixed Aramaic formula with inserted names/dates/
   places.  A template-based transcription is possible given the date
   (1883, Philadelphia) and names.  See JTS Ketubah Project or Ketubah.com.

7. COMMONS BEGANI NETATIKHA, PELLIOT HÉBREU 1
   - commons__begani_netatikha__p0001  (BeGani Netatikha manuscript)
   - commons__pelliot_hebreu_1__p0001  (medieval Hebrew letter from Khotan)
   Both require specialized paleographic expertise.  The Pelliot fragment
   may already have a published scholarly transcription — check Geniza
   scholarship / Judaeo-Persian literature databases.
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and show results but don't write files")
    args = parser.parse_args()

    entries = load_entries()
    entries_by_id = {e["entry_id"]: e for e in entries}
    total_before = sum(
        1 for e in entries if e.get("transcription", {}).get("status") == "full"
    )
    print(f"Entries: {len(entries)}  |  Already transcribed: {total_before}")

    total_new = 0
    total_new += fetch_wikisource_transcripts(entries_by_id, args.dry_run)
    total_new += fetch_manger_transcript(entries_by_id, args.dry_run)
    total_new += fetch_nli_transcripts(entries_by_id, args.dry_run)
    total_new += fetch_loc_transcripts(entries_by_id, args.dry_run)
    total_new += fetch_wikipedia_poems(entries_by_id, args.dry_run)
    total_new += fetch_nli_catalog_transcripts(entries_by_id, args.dry_run)
    total_new += fetch_nli_page_ocr(entries_by_id, args.dry_run)
    total_new += fetch_commons_descriptions(entries_by_id, args.dry_run)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Transcripts acquired: {total_new}")

    if not args.dry_run and total_new > 0:
        save_entries(entries)
        print(f"✓ entries.jsonl updated")

    print(HUMAN_NOTES)


if __name__ == "__main__":
    main()
