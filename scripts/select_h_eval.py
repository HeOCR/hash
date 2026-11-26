"""Select the handwriting (H) eval set from the HASH index (docs/h_eval_set_plan.md, approved by heocr-lead 2026-11-18).

Metadata only: this script reads data/index/*.jsonl and never opens a page image (it hashes nothing and reads no pixels;
image sha256 and size come from the index). It is committed before it runs; the run records its own commit.

    python3 scripts/select_h_eval.py --version v1 --target 50 --seed 20261118

Writes data/eval/h_eval_<version>/{manifest.jsonl,manifest.json,flags.jsonl,unscored.jsonl} and rewrites
data/index/eval_holdout.jsonl (every page of every selected unit). Per contamination v2 amendment 1 (restricted-eval #1651),
only the scored pages (selected: true, train_policy excluded_scored) are protected: their own pixels, in any capture or crop,
never enter TRAIN. Unselected pages of the same units are train_allowed_tagged (train_tag in_hash_eval_holdout_unselected).
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
    """Hold-out row -> TRAIN policy (contamination v2 amendment 1, restricted-eval #1651)."""
    if row["selected"]:
        return {**row, "train_policy": "excluded_scored"}
    return {**row, "train_policy": "train_allowed_tagged", "train_tag": "in_hash_eval_holdout_unselected"}

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / "data" / "index"
YEAR_NOW = 2026

# Units already used by training inputs (HeOCR/hletterscript upstream entries); out of every eval set.
TRAINING_USED_UNITS = {"commons__bialik_el_hazippor", "commons__bialik_letter_safed_1927", "commons__rachel_aqara_1928"}
# Writers seen by training (hletterscript writers); their other units form the seen_writer stratum, never primary.
SEEN_WRITERS = {"Hayyim Nahman Bialik", "Chaim Nachman Bialik", "Rachel Bluwstein"}
UNKNOWN_NAMES = {"unknown", "", None}
PAGES_PER_UNIT = 3
PAGES_PER_WRITER = 8
WRITER_SHARE = 0.10
PERIODS = ("before_1800", "1800_1899", "1900_1948", "after_1948", "undated")


def load(name):
    return [json.loads(line) for line in (IDX / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def first_year(text):
    if not text:
        return None
    m = re.search(r"(\d{4})", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,2})(st|nd|rd|th)", text)
    return (int(m.group(1)) - 1) * 100 if m else None


def period(year):
    if year is None:
        return "undated"
    if year < 1800:
        return "before_1800"
    if year < 1900:
        return "1800_1899"
    return "1900_1948" if year <= 1948 else "after_1948"


def hands(entry):
    """Named writers of the unit; an unnamed unit is its own hand."""
    names = sorted({c["name"] for c in entry.get("creators", []) if c.get("name") not in UNKNOWN_NAMES
                    and not c["name"].lower().startswith("unknown")})
    return names or [f"unknown:{entry['source_id']}"]


def unit_year(entries):
    years = [first_year(e["dates"].get("created")) for e in entries]
    years = [y for y in years if y is not None]
    return min(years) if years else None


def flags_for(entries):
    """Reasons a unit must go to heocr-lead before it may enter the set (plan §4); [] means plainly PD archival."""
    reasons = []
    e0 = entries[0]
    if any((e["rights"] or {}).get("rights_basis") != "public_domain" for e in entries):
        reasons.append(f"rights_basis {(e0['rights'] or {}).get('rights_basis')} (cc_by_sa units are out of v1)")
    y = unit_year(entries)
    if y is not None and y > 1948:
        reasons.append(f"created {y}, after 1948")
    for c in e0.get("creators", []):
        d = c.get("death_year")
        if d is not None and d > YEAR_NOW - 70:
            reasons.append(f"writer {c['name']} died {d}, less than 70 years ago")
    if y is None and not any(c.get("death_year") for c in e0.get("creators", [])):
        reasons.append("undated and no writer death year")
    return reasons


def page_gate(e):
    """Per-page gates; returns a reason or None."""
    if e["handwriting"].get("hebrew_extent") != "full_page":
        return "hebrew_extent not full_page"
    if "he" not in e.get("languages", []):
        return f"languages {e.get('languages')} without he"
    q = e.get("quality") or {}
    if q.get("usable_for_htr") is False or q.get("exclusion_reasons"):
        return f"quality excluded: {q.get('exclusion_reasons')}"
    orig = [f for f in e["files"] if f["role"] == "original"]
    if not orig or not orig[0]["mime_type"].startswith("image/"):
        return f"original is {orig[0]['mime_type'] if orig else 'missing'}, not an image"
    return None


def row(e, stratum, seed_rank):
    s_rights = e["rights"] or {}
    f = next(f for f in e["files"] if f["role"] == "original")
    y = first_year(e["dates"].get("created"))
    return {
        "entry_id": e["entry_id"], "source_id": e["source_id"], "sequence": e["sequence"],
        "stratum": stratum,
        "image_path": f["local_path"], "image_sha256": f["sha256"], "mime_type": f["mime_type"],
        "width_px": f.get("width_px"), "height_px": f.get("height_px"), "source_url": f["source_url"],
        "provider": None, "holding_institution": e.get("holding_institution"),
        "holding_shelfmark": e.get("holding_shelfmark"), "source_record_id": e.get("source_record_id"),
        "accessed_at": e["dates"].get("accessed_at"),
        "rights_basis": s_rights.get("rights_basis"), "license_expression": s_rights.get("license_expression"),
        "evidence_text": s_rights.get("evidence_text"), "verification_status": s_rights.get("verification_status"),
        "attribution": s_rights.get("attribution_text"),
        "writers": hands(e), "writer_death_years": [c.get("death_year") for c in e.get("creators", [])],
        "seen_writer": stratum == "seen_writer",
        "created": e["dates"].get("created"), "period": period(y),
        "document_type": e.get("document_type"), "languages": e.get("languages"),
        "known_text": e["transcription"]["status"] != "none",
        "hand_style": None, "rights_flag": None, "privacy_flag": None,
        "title": e.get("title"), "seed_rank": seed_rank,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    a = ap.parse_args()

    entries, sources = load("entries.jsonl"), {s["source_id"]: s for s in load("sources.jsonl")}
    units = defaultdict(list)
    for e in entries:
        units[e["source_id"]].append(e)
    for es in units.values():
        es.sort(key=lambda e: e["sequence"]["index"])

    rng = random.Random(a.seed)
    flagged, unscored, eligible = [], [], {}
    for uid in sorted(units):
        es = units[uid]
        if uid in TRAINING_USED_UNITS:
            unscored.append({"source_id": uid, "reason": "unit used by a training input (hletterscript)"})
            continue
        reasons = flags_for(es)
        if reasons:
            flagged.append({"source_id": uid, "pages": len(es), "title": es[0]["title"], "reasons": reasons})
            continue
        ok = []
        for e in es:
            why = page_gate(e)
            (unscored.append({"entry_id": e["entry_id"], "reason": why}) if why else ok.append(e))
        if ok:
            eligible[uid] = ok

    cap_writer = min(PAGES_PER_WRITER, int(WRITER_SHARE * a.target))
    taken_writer = Counter()

    def take(uid, room):
        es = eligible[uid]
        ws = [w for w in hands(es[0]) if not w.startswith("unknown:")]
        k = min(PAGES_PER_UNIT, len(es), room, *[cap_writer - taken_writer[w] for w in ws] or [PAGES_PER_UNIT])
        if k <= 0:
            return []
        pick = sorted(rng.sample(range(len(es)), k))
        for w in ws:
            taken_writer[w] += k
        return [es[i] for i in pick]

    seen_units = [u for u in eligible if set(hands(eligible[u][0])) & SEEN_WRITERS]
    primary_units = [u for u in eligible if u not in seen_units]

    cells = defaultdict(list)
    for u in primary_units:
        es = eligible[u]
        cells[(period(unit_year(es)), es[0].get("document_type"))].append(u)
    order = sorted(cells)
    rng.shuffle(order)
    for c in order:
        rng.shuffle(cells[c])

    selected, rank = [], 0
    progress = True
    while len(selected) < a.target and progress:
        progress = False
        for c in order:
            while cells[c] and len(selected) < a.target:
                u = cells[c].pop(0)
                got = take(u, a.target - len(selected))
                if got:
                    for e in got:
                        selected.append(row(e, "primary", rank)); rank += 1
                    progress = True
                    break
    seen_sel = []
    for u in sorted(seen_units, key=lambda u: hashlib.sha256(f"{a.seed}:{u}".encode()).hexdigest()):
        for e in take(u, PAGES_PER_UNIT):
            seen_sel.append(row(e, "seen_writer", rank)); rank += 1

    for r in selected + seen_sel:
        r["provider"] = sources[r["source_id"]].get("provider")

    out = ROOT / "data" / "eval" / f"h_eval_{a.version}"
    out.mkdir(parents=True, exist_ok=True)
    dump = lambda p, rows: p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                                        encoding="utf-8")
    rows = selected + seen_sel
    dump(out / "manifest.jsonl", rows)
    dump(out / "flags.jsonl", flagged)
    dump(out / "unscored.jsonl", unscored)

    sel_units = sorted({r["source_id"] for r in rows})
    chosen = {r["entry_id"] for r in rows}
    holdout = [train_policy({"entry_id": e["entry_id"], "source_id": u, "eval_set": f"h_eval_{a.version}",
                             "selected": e["entry_id"] in chosen}) for u in sel_units for e in units[u]]
    dump(IDX / "eval_holdout.jsonl", holdout)

    commit = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", "scripts/select_h_eval.py"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "scripts/select_h_eval.py"],
                           capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    count = lambda key, rs: dict(sorted(Counter(str(r[key]) for r in rs).items()))
    meta = {
        "eval_set": f"h_eval_{a.version}", "plan": "docs/h_eval_set_plan.md",
        "selector": "scripts/select_h_eval.py", "selector_commit": commit, "selector_dirty": bool(dirty),
        "hash_commit": head, "seed": a.seed, "target": a.target,
        "caps": {"pages_per_unit": PAGES_PER_UNIT, "pages_per_writer": cap_writer},
        "primary_pages": len(selected), "primary_units": len({r["source_id"] for r in selected}),
        "primary_hands": len({w for r in selected for w in r["writers"]}),
        "seen_writer_pages": len(seen_sel),
        "holdout_units": len(sel_units), "holdout_pages": len(holdout),
        "flagged_units": len(flagged), "unscored": len(unscored),
        "primary_by_period": count("period", selected), "primary_by_document_type": count("document_type", selected),
        "primary_by_provider": count("provider", selected), "primary_known_text": sum(r["known_text"] for r in selected),
        "manifest_sha256": hashlib.sha256((out / "manifest.jsonl").read_bytes()).hexdigest(),
        "hand_style": "empty: filled by eval or reviewers during transcription (plan §5)",
        "signed": "data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource",
    }
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("primary_pages", "primary_units", "primary_hands", "seen_writer_pages",
                                           "holdout_pages", "flagged_units", "unscored", "selector_dirty")}))


if __name__ == "__main__":
    main()
