#!/usr/bin/env python3
"""Ingest free-use NLI manuscripts (Ktiv) into HASH, one source per manuscript (heocr-lead, 2026-11-18).

Rules (lead's conditions):
- Only items whose IIIF manifest licence slug is ``public-domain-free-use`` are taken. Non-commercial and copyright
  slugs are rejected; so is any record that mentions Google digitization.
- Each scan records the slug, the MARC rights fields (903/939) and the NLI attribution.
- Flagged to heocr-lead, not ingested: created after 1948; a named person who died less than 70 years ago or has no
  death year after a 20th-century birth; 20th-century record books, accounts and lists (private names).
- Also flagged: a 20th-century item with any named person lacking a death year; a 20th-century diary; a Ktiv copy
  of a manuscript owned by another institution (MARC 710 "current owner"), whose own terms are not checked here.
- Hands: MARC 100 counts as the writer only for personal correspondence that is not a copy; otherwise it is the
  author of the work (role ``author``) and the scribe is unknown. 700 entries with a scribe/copyist relator are writers.

Two steps:
    python3 scripts/ingest_nli_manuscripts.py pick DISCOVERY.json --n 40 --seed 20261118 --out data/review/nli_ms_batch1.json
    python3 scripts/ingest_nli_manuscripts.py ingest data/review/nli_ms_batch1.json

``pick`` reads search results (NLI Search API JSON keyed by record id), fetches each candidate's manifest and MARC
(metadata only), applies the rules, and writes the batch plan with every decision. ``ingest`` downloads up to
--pages canvases per unit (IIIF, long side at most 2500 px), drops blank pages by ink ratio (no one views them), and
appends sources and entries to data/index. At most one request per --delay seconds; generic client name.
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / "data" / "index"
SCANS = ROOT / "data" / "scans"
UA = "HeOCR-research/0.1 (+https://github.com/HeOCR)"
DC = "http://purl.org/dc/elements/1.1/"
MARC = "{http://www.loc.gov/MARC21/slim}"
FREE = "public-domain-free-use"
YEAR_NOW = 2026
HEB_NUM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10, "כ": 20}
SCRIBE_RELATORS = ("סופר", "מעתיק", "scribe", "copyist", "כותב")
COPY_MARKS = ("העתק", "copy", "העתיק")
PRIVATE_LIST_TITLES = ("פנקס", "חשבונות", "רשימת", "רשימות", "קבלות", "פנקסי")
INSTITUTION_WORDS = r"communit|קהיל|institut|librar|universit|seminary|monaster|cathedral|museum|centre|center|collection|archive|bibliot|state|civic|ספרי|אוניברסיט|מוזאו"
GENRE_DOC_TYPE = [("Personal correspondence", "letter"), ("Letters", "letter"), ("אגרת", "letter"), ("מכתב", "letter"),
                  ("Diaries", "diary"), ("יומן", "diary"), ("Notebooks", "notebook"), ("מחברת", "notebook"),
                  ("Poetry", "poem"), ("שירים", "poem"), ("Drafts", "draft")]
ISO = {"heb": "he", "yid": "yi", "ara": "ar", "ger": "de", "per": "fa", "eng": "en", "ita": "it", "spa": "es",
       "fre": "fr", "lat": "la"}
_last = [0.0]


def lang_codes(raw):
    """MARC/DC language codes -> HASH codes (ISO 639-1 where one exists, else the 639-2/3 code), he first."""
    out = []
    for r in raw:
        for c in re.split(r"[;,\s]+", r or ""):
            c = ISO.get(c.strip().lower(), c.strip().lower())
            if c and c not in out:
                out.append(c)
    return sorted(out, key=lambda c: (c != "he", out.index(c)))


def fetch(url, delay):
    wait = delay - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503):
                return e.code, b""
        except Exception:
            pass
        time.sleep(10 * (attempt + 1))
    return 0, b""


def dc(x, f):
    return [t.get("@value") or t.get("@id") for t in x.get(DC + f, []) if isinstance(t, dict)]


def marc_fields(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = defaultdict(list)
    for d in root.iter(MARC + "datafield"):
        out[d.get("tag")].append({s.get("code"): (s.text or "").strip() for s in d})
    return out


def years_in(text):
    return [int(y) for y in re.findall(r"(?<!\d)(1[3-9]\d\d|20[0-2]\d)(?!\d)", text or "")]


GEM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10, "כ": 20, "ך": 20, "ל": 30,
       "מ": 40, "ם": 40, "נ": 50, "ן": 50, "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90, "ץ": 90, "ק": 100, "ר": 200,
       "ש": 300, "ת": 400}


def hebrew_years(text):
    """Hebrew-calendar years written as letters (e.g. תרס"ב -> 1902), assuming the omitted thousands are 5000."""
    out = []
    for w in re.findall(r'ת[א-ת]*["״׳\'][א-ת]', text or ""):
        v = sum(GEM.get(c, 0) for c in w)
        if 400 <= v <= 799:
            out.append(5000 + v - 3760)
    return out


def century_year(text):
    m = re.search(r'מאה\s*([א-ת"״׳\']+)', text or "")
    if not m:
        return None
    n = sum(HEB_NUM.get(c, 0) for c in m.group(1))
    return (n - 1) * 100 + 50 if 10 <= n <= 21 else None


def person(f):
    life = f.get("d", "")
    ys = years_in(life)
    born = ys[0] if ys else None
    died = ys[1] if len(ys) > 1 else (None if life.strip().endswith("-") or not ys else None)
    if re.search(r"נפטר\s*(\d{4})", life):
        died = int(re.search(r"נפטר\s*(\d{4})", life).group(1))
    if len(ys) == 1 and not life.strip().endswith("-") and "נפטר" in life:
        died = ys[0]; born = None
    return {"name": re.sub(r"[,.\s]+$", "", f.get("a", "")).strip(), "born": born, "death_year": died,
            "relator": f.get("e", "")}


def assess(rec_id, search_rec, delay):
    """Metadata-only decision for one candidate."""
    title = (dc(search_rec, "title") or [""])[0]
    d = {"record_id": rec_id, "title": title, "decision": None, "reasons": []}
    man_url = next((u for u in dc(search_rec, "relation") if u.endswith("/manifest")), None)
    if not man_url:
        d.update(decision="rejected", reasons=["no IIIF manifest"]); return d
    st, body = fetch(man_url, delay)
    if st != 200:
        d.update(decision="rejected", reasons=[f"manifest HTTP {st}"]); return d
    man = json.loads(body)
    lic = man.get("license")
    lic = " ".join(l if isinstance(l, str) else l.get("@id", "") for l in (lic if isinstance(lic, list) else [lic or ""]))
    slug = lic.rstrip("/").rsplit("/", 1)[-1] if lic else None
    canvases = (man.get("sequences") or [{}])[0].get("canvases", [])
    d.update(manifest_url=man_url, license_url=lic, license_slug=slug, canvas_count=len(canvases),
             item_url=search_rec.get("@id"), attribution=man.get("attribution"))
    if slug != FREE:
        d.update(decision="rejected", reasons=[f"licence slug {slug}"]); return d
    st, mx = fetch(f"https://iiif.nli.org.il/IIIFv21/marc/bib/{rec_id}", delay)
    if st != 200:
        d.update(decision="rejected", reasons=[f"MARC HTTP {st}"]); return d
    m = marc_fields(mx)
    flat = json.dumps(m, ensure_ascii=False)
    d["marc"] = {k: m[k] for k in ("090", "100", "245", "260", "264", "300", "500", "597", "655", "700", "710", "903",
                                   "939", "041") if k in m}
    reasons = []
    if "google" in flat.lower():
        d.update(decision="rejected", reasons=["MARC mentions Google"]); return d
    if not any("public domain free use" in f.get("a", "").lower() for f in m.get("939", [])):
        reasons.append("MARC 939 is not 'public domain free use'")
    langs = [f.get("a", "") for f in m.get("041", [])] + dc(search_rec, "language")
    d["languages"] = lang_codes(langs)
    if not any("heb" in l for l in langs):
        d.update(decision="rejected", reasons=[f"languages {langs} without heb"]); return d
    date_text = " ".join(f.get("c", "") for t in ("260", "264") for f in m.get(t, [])) + " " + \
        " ".join(dc(search_rec, "non_standard_date") + dc(search_rec, "date"))
    ys = [y for y in years_in(date_text) + hebrew_years(date_text) if 1000 < y <= YEAR_NOW]
    year = max(ys) if ys else century_year(date_text)
    d["created"] = (str(max(ys)) if ys else (date_text.strip() or None))
    d["created_year_est"] = year
    d["created_precision"] = "year" if ys else ("circa" if year else "unknown")
    genres = " ".join(f.get("a", "") for f in m.get("655", [])) + " " + title
    doc_type = next((dt for k, dt in GENRE_DOC_TYPE if k in genres), "other")
    owners = [f.get("a", "") for f in m.get("710", []) if "owner" in f.get("e", "")]
    foreign = [o for o in owners if o != "The National Library of Israel" and re.search(INSTITUTION_WORDS, o, re.I)]
    if foreign:
        reasons.append(f"owned by {', '.join(foreign)}; NLI Ktiv copy, owner's terms not checked")
    people = [dict(person(f), field="100") for f in m.get("100", [])] + [dict(person(f), field="700") for f in m.get("700", [])]
    for p in people:
        if p["death_year"] and p["death_year"] > YEAR_NOW - 70:
            reasons.append(f"{p['name']} died {p['death_year']}, less than 70 years ago")
        if not p["death_year"] and p["born"] and p["born"] >= 1880:
            reasons.append(f"{p['name']} born {p['born']}, no death year")
    if year and year > 1948:
        reasons.append(f"created {year}, after 1948")
    if (year or 0) >= 1900:
        for p in people:
            if not p["death_year"]:
                reasons.append(f"{p['name']}: no death year on a 20th-century item")
    if (year or 0) >= 1900 and doc_type in ("diary",):
        reasons.append("20th-century diary (mainly about private persons?)")
    if (year or 0) >= 1900 and any(t in title for t in PRIVATE_LIST_TITLES):
        reasons.append("20th-century record book, accounts or list (private names)")
    is_copy = any(c in (title + flat) for c in COPY_MARKS)
    creators = []
    for p in people:
        scribe = any(r in p["relator"] for r in SCRIBE_RELATORS)
        role = "writer" if scribe or (p["field"] == "100" and doc_type == "letter" and not is_copy) else "author"
        if p["field"] == "700" and not scribe:
            role = "recipient" if "נמען" in p["relator"] or "recipient" in p["relator"] else "author"
        creators.append({"name": p["name"], "role": role, "death_year": p["death_year"], "authority_url": None})
    d.update(creators=creators, document_type=doc_type, is_copy=is_copy,
             owner=[f.get("a") for f in m.get("710", []) if "owner" in f.get("e", "")],
             shelfmark=(m.get("090") or [{}])[0].get("a"),
             rights_903=" ".join(" ".join(f.values()) for f in m.get("903", [])),
             rights_939=" ".join(f.get("a", "") for f in m.get("939", [])))
    d["decision"] = "flagged" if reasons else "accepted"
    d["reasons"] = reasons
    return d


def existing_units():
    return {json.loads(l)["source_id"] for l in (IDX / "sources.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}


def cmd_pick(a):
    recs = json.loads(Path(a.discovery).read_text(encoding="utf-8"))
    have = existing_units()
    decided = {d["record_id"] for plan in (a.exclude_plans or [])
               for d in json.loads(Path(plan).read_text(encoding="utf-8"))["decisions"]}
    pool = [(rid, r) for rid, r in sorted(recs.items())
            if f"nli__ms_{rid}" not in have and rid not in decided and "National Library of Israel" in " ".join(dc(r, "source"))]
    rng = random.Random(a.seed)
    by_term = defaultdict(list)
    for rid, r in pool:
        by_term[r.get("_term", "")].append((rid, r))
    for t in by_term:
        rng.shuffle(by_term[t])
    order = sorted(by_term)
    decisions, accepted = [], 0
    while accepted < a.n and any(by_term.values()):
        for t in order:
            if accepted >= a.n or not by_term[t]:
                continue
            rid, r = by_term[t].pop(0)
            d = assess(rid, r, a.delay)
            d["term"] = t
            decisions.append(d)
            accepted += d["decision"] == "accepted"
            print(f"{d['decision']:9} {rid} {t} {d['title'][:40]} {d['reasons'][:1]}", flush=True)
    out = {"seed": a.seed, "n": a.n, "discovery": a.discovery, "exclude_plans": a.exclude_plans or [], "picked_at": datetime.now(timezone.utc).isoformat(),
           "counts": dict(Counter(d["decision"] for d in decisions)), "decisions": decisions,
           "signed": "data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource"}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["counts"]))


def ink_ratio(img):
    g = img.convert("L")
    g.thumbnail((800, 800))
    hist = g.histogram()
    total = sum(hist)
    mean = sum(i * h for i, h in enumerate(hist)) / total
    dark = sum(hist[: max(1, int(mean * 0.6))])
    return dark / total


def cmd_ingest(a):
    from PIL import Image
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    have = existing_units()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    new_sources, new_entries, report = [], [], []
    for d in plan["decisions"]:
        if d["decision"] != "accepted":
            continue
        sid = f"nli__ms_{d['record_id']}"
        if sid in have:
            continue
        st, body = fetch(d["manifest_url"], a.delay)
        man = json.loads(body)
        canvases = (man.get("sequences") or [{}])[0].get("canvases", [])
        order = list(range(len(canvases)))
        if len(canvases) >= 4:
            order = order[1:] + order[:1]  # a leading canvas is often a cover or binding
        got, tried = [], 0
        for ci in order:
            if len(got) >= a.pages or tried >= a.pages + 3:
                break
            tried += 1
            c = canvases[ci]
            svc = c["images"][0]["resource"].get("service", {}).get("@id") or c["images"][0]["resource"]["@id"].split("/full/")[0]
            url = f"{svc}/full/!2500,2500/0/default.jpg"
            st, img_bytes = fetch(url, a.delay)
            if st != 200 or not img_bytes:
                report.append({"source_id": sid, "canvas": ci, "skip": f"image HTTP {st}"}); continue
            img = Image.open(io.BytesIO(img_bytes))
            ratio = ink_ratio(img)
            if ratio < a.min_ink:
                report.append({"source_id": sid, "canvas": ci, "skip": f"ink ratio {ratio:.4f} below {a.min_ink}"}); continue
            got.append((ci, c, url, img_bytes, img.size, ratio))
        if not got:
            report.append({"source_id": sid, "skip": "no usable canvas"}); continue
        attribution = "; ".join(x for x in [", ".join(c["name"] for c in d["creators"] if c["role"] == "writer"),
                                             "National Library of Israel"] if x)
        evidence = (f"IIIF manifest licence {d['license_url']} (slug {FREE}); MARC 939: {d['rights_939']}; "
                    f"MARC 903: {d['rights_903']}")
        if d.get("owner"):
            evidence += f"; current owner (MARC 710): {', '.join(d['owner'])}, digitized by NLI Ktiv"
        item_url = d.get("item_url") or f"https://www.nli.org.il/he/manuscripts/{d['record_id']}/NLI"
        rights = {"rights_basis": "public_domain", "license_expression": "LicenseRef-NLI-Public-Domain-Free-Use",
                  "commercial_use_allowed": True, "derivatives_allowed": True, "scan_redistribution_allowed": True,
                  "attribution_required": True}
        new_sources.append({
            "source_id": sid, "record_type": "item", "status": "verified", "priority": "high",
            "provider": "National Library of Israel", "title": d["title"],
            "description": f"NLI digitized manuscript (Ktiv), {d.get('created') or 'undated'}, {d['canvas_count']} canvases.",
            "urls": {"canonical": item_url, "landing": None, "api": d["manifest_url"], "download": None, "related": []},
            "rights": {**rights, "evidence_text": evidence, "terms_url": d["license_url"],
                       "verification_status": "primary_page_checked", "verified_at": now.date().isoformat()},
            "scope": {"date_range": d.get("created"), "languages": ["he"], "document_types": [d["document_type"]],
                      "creator_names": [c["name"] for c in d["creators"]], "expected_handwriting": "yes",
                      "estimated_scan_count": d["canvas_count"]},
            "ingest": {"method": "iiif", "access_notes": "NLI IIIF Presentation 2.1 manifest and Image API; MARC via IIIF marc endpoint.",
                       "agent_notes": f"scripts/ingest_nli_manuscripts.py, batch {Path(a.plan).name}; discovery term {d.get('term')}.",
                       "blocked_reason": None},
            "evidence": [{"kind": "primary_url", "citation": d["manifest_url"], "quote": f"license: {d['license_url']}"},
                         {"kind": "primary_url", "citation": f"https://iiif.nli.org.il/IIIFv21/marc/bib/{d['record_id']}",
                          "quote": f"939 {d['rights_939']}; 903 {d['rights_903']}"}],
        })
        unit_dir = SCANS / sid
        unit_dir.mkdir(parents=True, exist_ok=True)
        for seq, (ci, c, url, img_bytes, (w, h), ratio) in enumerate(got, start=1):
            eid = f"{sid}__p{ci + 1:04d}"
            path = unit_dir / f"{eid}.jpg"
            path.write_bytes(img_bytes)
            new_entries.append({
                "entry_id": eid, "source_id": sid, "source_record_id": d["record_id"],
                "sequence": {"index": ci + 1, "label": str(c.get("label") or ci + 1), "physical_unit_count": d["canvas_count"]},
                "title": f"{d['title']} — {c.get('label') or ci + 1}",
                "creators": d["creators"],
                "dates": {"created": d.get("created"), "created_precision": d["created_precision"],
                          "accessed_at": now.date().isoformat()},
                "languages": d.get("languages") or ["he"], "script": ["Hebr"], "document_type": d["document_type"],
                "handwriting": {"extent": "full_page", "hebrew_extent": "full_page",
                                "notes": f"NLI manuscript {d['record_id']}; canvas {ci + 1} of {d['canvas_count']}; "
                                         f"ink ratio {ratio:.3f} (automatic, not viewed)."
                                         + (" Catalogue marks it as a copy." if d.get("is_copy") else "")},
                "files": [{"role": "original", "local_path": str(path.relative_to(ROOT)), "source_url": url,
                           "provider_file_id": c["@id"].rsplit("/", 1)[-1],
                           "sha256": hashlib.sha256(img_bytes).hexdigest(), "mime_type": "image/jpeg",
                           "bytes": len(img_bytes), "width_px": w, "height_px": h}],
                "rights": {**rights, "attribution_text": attribution, "attribution_url": item_url,
                           "verification_status": "primary_page_checked", "evidence_text": evidence,
                           "verified_at": now.date().isoformat()},
                "provenance": {"acquired_at": now.isoformat().replace("+00:00", "Z"), "acquired_by": "claude-code",
                               "source_landing_url": item_url,
                               "notes": "Downloaded through the NLI IIIF Image API (long side at most 2500 px) by scripts/ingest_nli_manuscripts.py."},
                "holding_institution": "National Library of Israel",
                "holding_shelfmark": d.get("shelfmark") or d["record_id"],
                "quality": {"usable_for_htr": True, "legibility": "unknown", "exclusion_reasons": [],
                            "notes": "Blank-page gate by ink ratio only; not visually inspected."},
                "transcription": {"status": "none", "text_path": None, "alto_path": None, "hocr_path": None,
                                  "source_url": None, "created_by": "unknown",
                                  "rights": {"rights_basis": "public_domain", "license_expression": None,
                                             "commercial_use_allowed": None, "derivatives_allowed": None,
                                             "redistribution_allowed": None, "attribution_required": None,
                                             "verification_status": "unverified", "evidence_text": None, "verified_at": None}},
            })
        print(f"ingested {sid}: {len(got)} pages", flush=True)
    with (IDX / "sources.jsonl").open("a", encoding="utf-8") as f:
        for s in new_sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with (IDX / "entries.jsonl").open("a", encoding="utf-8") as f:
        for e in new_entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rep = Path(a.plan).with_suffix(".ingest_report.json")
    rep.write_text(json.dumps({"sources": len(new_sources), "entries": len(new_entries), "skips": report},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"sources": len(new_sources), "entries": len(new_entries), "skips": len(report)}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick"); p.add_argument("discovery"); p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, required=True); p.add_argument("--out", required=True)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--exclude-plans", nargs="*", help="earlier batch plans; their records are never re-assessed")
    i = sub.add_parser("ingest"); i.add_argument("plan"); i.add_argument("--pages", type=int, default=3)
    i.add_argument("--min-ink", type=float, default=0.01); i.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    {"pick": cmd_pick, "ingest": cmd_ingest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
