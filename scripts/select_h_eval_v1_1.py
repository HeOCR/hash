"""Select amendment v1.1 of the handwriting (H) eval set from the HASH index (heocr-lead, 2026-11-18).

v1 (data/eval/h_eval_v1/, selector fc0f32b) is never changed. v1.1 only adds pages, from units outside every existing
hold-out. Same rules as v1 (docs/h_eval_set_plan.md) except:

- **Hand rule (lead, 2026-11-18).** Only the person who wrote the page counts as a hand: role ``writer`` (autograph
  or scribe). For sources other than NLI manuscripts (``nli__ms_*``), HASH's legacy role ``author`` also counts,
  because those entries are autographs (letters, diaries, poems in the writer's own hand). For NLI manuscripts,
  ``author`` is the author of the work and never counts. A unit with no counted hand is its own hand.
- **Caps over v1 + v1.1 together:** at most 3 pages per unit; per hand at most min(8, 10% of the combined target).
  v1's pages count toward the caps. Seen writers are as in v1 (hletterscript) and never enter the primary stratum.
- **Balance:** fill by period, then document type, round robin, seeded, as in v1.
- **Main language (lead, 2026-11-18).** The primary stratum takes only units whose main language is Hebrew. The NLI
  catalogue cannot tell the main language (it lists heb first, and 008 says heb, even for Maimonides' Arabic
  commentary; data/review/nli_ms_languages_041.json), so the rule is conservative: a unit is primary-eligible only if
  it records no other Hebrew-script language. Units that also record Yiddish, Judeo-Arabic, Ladino, Judeo-Persian,
  Arabic, Persian, Aramaic or (for NLI manuscripts, all in Hebrew script) German form the ``other_hebrew_script``
  stratum. It is reported apart, filled only after the primary stratum, under the same caps, up to
  OTHER_SCRIPT_SHARE of the combined target.

Metadata only: reads data/index/*.jsonl, never a page image. Committed before it runs.

    python3 scripts/select_h_eval_v1_1.py --target-total 100 --seed 20261119

Writes data/eval/h_eval_v1_1/{manifest.jsonl,manifest.json,flags.jsonl,unscored.jsonl} and appends the v1.1 units'
pages to data/index/eval_holdout.jsonl (v1 rows are kept as they are), each with its train_policy: scored pages
excluded_scored, unselected pages train_allowed_tagged (contamination v2 amendment 1, restricted-eval #1651).
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


def train_policy(row):
    """Hold-out row -> TRAIN policy (contamination v2 amendment 1, restricted-eval #1651); same rule as select_h_eval.py."""
    if row["selected"]:
        return {**row, "train_policy": "excluded_scored"}
    return {**row, "train_policy": "train_allowed_tagged", "train_tag": "in_hash_eval_holdout_unselected"}

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / "data" / "index"
YEAR_NOW = 2026
VERSION = "v1_1"
BASE = "h_eval_v1"
TRAINING_USED_UNITS = {"commons__bialik_el_hazippor", "commons__bialik_letter_safed_1927", "commons__rachel_aqara_1928"}
SEEN_WRITERS = {"Hayyim Nahman Bialik", "Chaim Nachman Bialik", "Rachel Bluwstein"}
PAGES_PER_UNIT = 3
PAGES_PER_WRITER = 8
WRITER_SHARE = 0.10
OTHER_SCRIPT_SHARE = 0.10
HEBREW_SCRIPT_OTHER = {"yi", "jrb", "lad", "jpr", "ar", "fa", "arc", "yid", "ara", "per"}


def main_language_hebrew(entry):
    langs = set(entry.get("languages", [])) - {"he"}
    other = set(HEBREW_SCRIPT_OTHER)
    if entry["source_id"].startswith("nli__ms_"):
        other |= {"de", "ger"}
    return "he" in entry.get("languages", []) and not (langs & other)


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def first_year(text):
    if not text:
        return None
    m = re.search(r"(\d{4})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,2})(st|nd|rd|th)", text)
    return (int(m.group(1)) - 1) * 100 if m else None


HEB_NUM = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10, "כ": 20}


def year_of(entry):
    created = entry["dates"].get("created") or ""
    y = first_year(created)
    if y is not None and y > 1000:
        return y
    m = re.search(r'מאה\s*([א-ת"״׳\']+)', created)
    if m:
        n = sum(HEB_NUM.get(c, 0) for c in m.group(1))
        if 10 <= n <= 21:
            return (n - 1) * 100 + 50
    return None


def period(year):
    if year is None:
        return "undated"
    if year < 1800:
        return "before_1800"
    if year < 1900:
        return "1800_1899"
    return "1900_1948" if year <= 1948 else "after_1948"


def hands(entry):
    nli_ms = entry["source_id"].startswith("nli__ms_")
    counted = {"writer"} if nli_ms else {"writer", "author"}
    names = sorted({c["name"] for c in entry.get("creators", []) if c.get("role") in counted and c.get("name")
                    and not c["name"].lower().startswith("unknown")})
    return names or [f"unknown:{entry['source_id']}"]


def flags_for(entries):
    reasons, e0 = [], entries[0]
    if any((e["rights"] or {}).get("rights_basis") != "public_domain" for e in entries):
        reasons.append(f"rights_basis {(e0['rights'] or {}).get('rights_basis')}")
    years = [y for y in (year_of(e) for e in entries) if y is not None]
    if years and max(years) > 1948:
        reasons.append(f"created {max(years)}, after 1948")
    for c in e0.get("creators", []):
        d = c.get("death_year")
        if d is not None and d > YEAR_NOW - 70:
            reasons.append(f"{c['name']} died {d}, less than 70 years ago")
    if not years and not any(c.get("death_year") for c in e0.get("creators", [])):
        reasons.append("undated and no death year")
    return reasons


def page_gate(e):
    if e["handwriting"].get("hebrew_extent") != "full_page":
        return "hebrew_extent not full_page"
    if "he" not in e.get("languages", []):
        return f"languages {e.get('languages')} without he"
    q = e.get("quality") or {}
    if q.get("usable_for_htr") is False or q.get("exclusion_reasons"):
        return f"quality excluded: {q.get('exclusion_reasons')}"
    orig = [f for f in e["files"] if f["role"] == "original"]
    if not orig or not orig[0]["mime_type"].startswith("image/"):
        return "original is not an image"
    return None


def row(e, stratum, rank, provider):
    r = e["rights"] or {}
    f = next(f for f in e["files"] if f["role"] == "original")
    return {
        "entry_id": e["entry_id"], "source_id": e["source_id"], "sequence": e["sequence"], "stratum": stratum,
        "image_path": f["local_path"], "image_sha256": f["sha256"], "mime_type": f["mime_type"],
        "width_px": f.get("width_px"), "height_px": f.get("height_px"), "source_url": f["source_url"],
        "provider": provider, "holding_institution": e.get("holding_institution"),
        "holding_shelfmark": e.get("holding_shelfmark"), "source_record_id": e.get("source_record_id"),
        "accessed_at": e["dates"].get("accessed_at"),
        "rights_basis": r.get("rights_basis"), "license_expression": r.get("license_expression"),
        "evidence_text": r.get("evidence_text"), "verification_status": r.get("verification_status"),
        "attribution": r.get("attribution_text"),
        "writers": hands(e), "writer_death_years": [c.get("death_year") for c in e.get("creators", [])],
        "creators": e.get("creators", []), "seen_writer": stratum == "seen_writer",
        "created": e["dates"].get("created"), "period": period(year_of(e)),
        "document_type": e.get("document_type"), "languages": e.get("languages"),
        "known_text": e["transcription"]["status"] != "none", "copy": "copy" in (e["handwriting"].get("notes") or ""),
        "hand_style": None, "rights_flag": None, "privacy_flag": None, "title": e.get("title"), "seed_rank": rank,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-total", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    a = ap.parse_args()

    entries = load(IDX / "entries.jsonl")
    sources = {s["source_id"]: s for s in load(IDX / "sources.jsonl")}
    holdout = load(IDX / "eval_holdout.jsonl")
    base = load(ROOT / "data" / "eval" / BASE / "manifest.jsonl")
    held_units = {h["source_id"] for h in holdout}
    by_id = {e["entry_id"]: e for e in entries}

    units = defaultdict(list)
    for e in entries:
        units[e["source_id"]].append(e)
    for es in units.values():
        es.sort(key=lambda e: e["sequence"]["index"])

    cap_writer = min(PAGES_PER_WRITER, int(WRITER_SHARE * a.target_total))
    taken = Counter()
    for r in base:
        for w in hands(by_id[r["entry_id"]]):
            if not w.startswith("unknown:"):
                taken[w] += 1
    need = a.target_total - sum(r["stratum"] == "primary" for r in base)

    rng = random.Random(a.seed)
    flagged, unscored, eligible = [], [], {}
    for uid in sorted(units):
        if uid in held_units:
            continue
        es = units[uid]
        if uid in TRAINING_USED_UNITS:
            unscored.append({"source_id": uid, "reason": "unit used by a training input (hletterscript)"}); continue
        reasons = flags_for(es)
        if reasons:
            flagged.append({"source_id": uid, "pages": len(es), "title": es[0]["title"], "reasons": reasons}); continue
        ok = []
        for e in es:
            why = page_gate(e)
            (unscored.append({"entry_id": e["entry_id"], "reason": why}) if why else ok.append(e))
        if ok:
            eligible[uid] = ok

    def take(uid, room):
        es = eligible[uid]
        ws = [w for w in hands(es[0]) if not w.startswith("unknown:")]
        k = min(PAGES_PER_UNIT, len(es), room, *([cap_writer - taken[w] for w in ws] or [PAGES_PER_UNIT]))
        if k <= 0:
            return []
        pick = sorted(rng.sample(range(len(es)), k))
        for w in ws:
            taken[w] += k
        return [es[i] for i in pick]

    seen_units = [u for u in eligible if set(hands(eligible[u][0])) & SEEN_WRITERS]
    other_units = [u for u in eligible if u not in seen_units and not all(main_language_hebrew(e) for e in eligible[u])]
    primary_units = [u for u in eligible if u not in seen_units and u not in other_units]
    cells = defaultdict(list)
    for u in primary_units:
        cells[(period(year_of(eligible[u][0])), eligible[u][0].get("document_type"))].append(u)
    order = sorted(cells)
    rng.shuffle(order)
    for c in order:
        rng.shuffle(cells[c])

    selected, rank, progress = [], 0, True
    while len(selected) < need and progress:
        progress = False
        for c in order:
            while cells[c] and len(selected) < need:
                u = cells[c].pop(0)
                got = take(u, need - len(selected))
                if got:
                    for e in got:
                        selected.append(row(e, "primary", rank, sources[u].get("provider"))); rank += 1
                    progress = True
                    break
    other_sel, room = [], int(OTHER_SCRIPT_SHARE * a.target_total)
    for u in sorted(other_units, key=lambda u: hashlib.sha256(f"{a.seed}:other:{u}".encode()).hexdigest()):
        if len(other_sel) >= room:
            break
        for e in take(u, room - len(other_sel)):
            other_sel.append(row(e, "other_hebrew_script", rank, sources[u].get("provider"))); rank += 1
    seen_sel = []
    for u in sorted(seen_units, key=lambda u: hashlib.sha256(f"{a.seed}:{u}".encode()).hexdigest()):
        for e in take(u, PAGES_PER_UNIT):
            seen_sel.append(row(e, "seen_writer", rank, sources[u].get("provider"))); rank += 1

    out = ROOT / "data" / "eval" / f"h_eval_{VERSION}"
    out.mkdir(parents=True, exist_ok=True)
    dump = lambda p, rows: p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                                        encoding="utf-8")
    rows = selected + other_sel + seen_sel
    dump(out / "manifest.jsonl", rows)
    dump(out / "flags.jsonl", flagged)
    dump(out / "unscored.jsonl", unscored)
    chosen = {r["entry_id"] for r in rows}
    new_hold = [train_policy({"entry_id": e["entry_id"], "source_id": u, "eval_set": f"h_eval_{VERSION}",
                              "selected": e["entry_id"] in chosen}) for u in sorted({r["source_id"] for r in rows}) for e in units[u]]
    dump(IDX / "eval_holdout.jsonl", holdout + new_hold)

    git = lambda *args: subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()
    count = lambda key, rs: dict(sorted(Counter(str(r[key]) for r in rs).items()))
    primary_all_hands = {w for r in base if r["stratum"] == "primary" for w in r["writers"]} | \
        {w for r in selected for w in r["writers"]}
    meta = {
        "eval_set": f"h_eval_{VERSION}", "amends": BASE, "base_manifest_sha256":
            hashlib.sha256((ROOT / "data" / "eval" / BASE / "manifest.jsonl").read_bytes()).hexdigest(),
        "selector": "scripts/select_h_eval_v1_1.py",
        "selector_commit": git("log", "-1", "--format=%H", "--", "scripts/select_h_eval_v1_1.py"),
        "selector_dirty": bool(git("status", "--porcelain", "--", "scripts/select_h_eval_v1_1.py")),
        "hash_commit": git("rev-parse", "HEAD"), "seed": a.seed, "target_total": a.target_total,
        "caps": {"pages_per_unit": PAGES_PER_UNIT, "pages_per_writer": cap_writer},
        "hand_rule": "role writer; plus role author outside nli__ms_ sources (legacy autograph convention); else unknown:<unit>",
        "added_primary_pages": len(selected), "added_primary_units": len({r["source_id"] for r in selected}),
        "added_primary_hands": len({w for r in selected for w in r["writers"]}),
        "added_seen_writer_pages": len(seen_sel), "added_other_hebrew_script_pages": len(other_sel),
        "main_language_rule": "primary only if no other Hebrew-script language is recorded (lead 2026-11-18)",
        "combined_primary_pages": len(selected) + sum(r["stratum"] == "primary" for r in base),
        "combined_primary_hands": len(primary_all_hands),
        "holdout_added_pages": len(new_hold), "flagged_units": len(flagged), "unscored": len(unscored),
        "added_by_period": count("period", selected), "added_by_document_type": count("document_type", selected),
        "added_by_provider": count("provider", selected), "added_copies": sum(r["copy"] for r in selected),
        "manifest_sha256": hashlib.sha256((out / "manifest.jsonl").read_bytes()).hexdigest(),
        "signed": "data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource",
    }
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("added_primary_pages", "added_primary_units", "added_primary_hands", "added_other_hebrew_script_pages",
                                           "combined_primary_pages", "combined_primary_hands", "flagged_units",
                                           "selector_dirty")}))


if __name__ == "__main__":
    main()
