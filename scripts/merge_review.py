#!/usr/bin/env python3
"""
merge_review.py — Promote approved entries from a review batch into the main index.

Usage:
    python3 scripts/merge_review.py <batch_id> [--dry-run] [--force]

What it does:
    1. Reads  data/review/<batch_id>_pending.jsonl
    2. Reads  data/review/<batch_id>_decisions.json
       (absent decisions file → every entry is considered approved)
    3. For each entry whose status is NOT "rejected":
       - writes it into data/index/entries.jsonl (appends, skips duplicates)
    4. Prints a summary; does NOT delete the pending/decisions files
       (keep them as audit trail).

Options:
    --dry-run   Show what would be merged without writing anything.
    --force     Re-add entries that already exist in entries.jsonl
                (normally a no-op / skip).
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE  = Path(__file__).parent
REPO  = HERE.parent
DATA  = REPO / "data"
REVIEW_DIR   = DATA / "review"
ENTRIES_PATH = DATA / "index" / "entries.jsonl"
SOURCES_PATH = DATA / "index" / "sources.jsonl"

_INGEST_METHOD_ENUM = {"manual_download", "iiif", "api", "scrape", "dataset_download", "unknown"}


def make_source_record(entry: dict) -> dict:
    """Build a minimal verified source record from an entry dict."""
    eid  = entry["entry_id"]
    sid  = re.sub(r"__p\d+$", "", eid)
    prov = entry.get("provenance", {})
    # Strip fields that sources.jsonl rights schema disallows
    rights = {k: v for k, v in entry.get("rights", {}).items()
              if k not in ("attribution_text", "attribution_url")}
    method = prov.get("acquired_by", "unknown")
    if method not in _INGEST_METHOD_ENUM:
        method = "manual_download"
    return {
        "source_id":   sid,
        "record_type": "item",
        "status":      "verified",
        "priority":    "seed",
        "provider":    entry.get("holding_institution") or prov.get("acquired_by", "unknown"),
        "title":       entry.get("title", sid),
        "description": entry.get("handwriting", {}).get("notes", ""),
        "urls": {
            "canonical": prov.get("source_landing_url"),
            "landing":   prov.get("source_landing_url"),
            "api":       None,
            "download":  None,
            "related":   [],
        },
        "rights": rights,
        "scope": {
            "date_range":           entry.get("dates", {}).get("created"),
            "languages":            entry.get("languages", []),
            "document_types":       [entry.get("document_type", "other")],
            "creator_names":        [],
            "expected_handwriting": "yes",
            "estimated_scan_count": entry.get("sequence", {}).get("physical_unit_count"),
        },
        "ingest": {
            "method":         method,
            "access_notes":   prov.get("notes", ""),
            "agent_notes":    "",
            "blocked_reason": None,
        },
        "evidence": [{
            "kind":     "primary_url",
            "citation": prov.get("source_landing_url", ""),
            "quote":    entry.get("rights", {}).get("evidence_text", ""),
        }],
    }


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch_id", help="Batch ID (prefix of *_pending.jsonl)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true",
                        help="Re-add already-existing entries (normally skipped)")
    args = parser.parse_args()

    pending_path   = REVIEW_DIR / f"{args.batch_id}_pending.jsonl"
    decisions_path = REVIEW_DIR / f"{args.batch_id}_decisions.json"

    # ── Load pending entries ──────────────────────────────────
    entries = load_jsonl(pending_path)
    if not entries:
        sys.exit(f"ERROR: No entries found at {pending_path}")

    # ── Load decisions ────────────────────────────────────────
    decisions: dict[str, dict] = {}
    if decisions_path.exists():
        try:
            decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
        except Exception as e:
            sys.exit(f"ERROR: Could not parse {decisions_path}: {e}")
    else:
        print(f"⚠  No decisions file found; treating all {len(entries)} entries as approved.")

    # ── Load existing entry IDs and source IDs ───────────────
    existing_ids: set[str] = {
        e["entry_id"] for e in load_jsonl(ENTRIES_PATH) if "entry_id" in e
    }
    existing_sids: set[str] = {
        s["source_id"] for s in load_jsonl(SOURCES_PATH) if "source_id" in s
    }

    # ── Classify ──────────────────────────────────────────────
    to_merge   = []
    rejected   = []
    duplicates = []
    commented  = []   # approved with comments (logged but still merged)

    for entry in entries:
        eid = entry["entry_id"]
        dec = decisions.get(eid, {})
        status = dec.get("status", "approved")

        if status == "rejected":
            rejected.append(eid)
            continue

        if eid in existing_ids and not args.force:
            duplicates.append(eid)
            continue

        if dec.get("comment", "").strip():
            commented.append(eid)

        to_merge.append(entry)

    # ── Report ────────────────────────────────────────────────
    print(f"\nBatch:      {args.batch_id}")
    print(f"Pending:    {len(entries)} entries")
    print(f"Approved:   {len(to_merge)}  (to merge)")
    if commented:
        print(f"  ↳ with reviewer notes: {len(commented)}")
    print(f"Rejected:   {len(rejected)}")
    if duplicates:
        print(f"Duplicates: {len(duplicates)}  (skipped — already in index)")
    print()

    if rejected:
        print("Rejected entries:")
        for eid in rejected:
            cmt = decisions.get(eid, {}).get("comment", "")
            suffix = f"  # {cmt}" if cmt.strip() else ""
            print(f"  ✗  {eid}{suffix}")
        print()

    if not to_merge:
        print("Nothing to merge.")
        return

    if args.dry_run:
        print("[DRY RUN] Would append these entries to entries.jsonl:")
        for e in to_merge:
            cmt = decisions.get(e["entry_id"], {}).get("comment", "")
            suffix = f"  # NOTE: {cmt}" if cmt.strip() else ""
            print(f"  +  {e['entry_id']}{suffix}")
        print()
        print("[DRY RUN] No files were modified.")
        return

    # ── Auto-create missing source records ───────────────────
    new_sources = []
    for entry in to_merge:
        sid = entry.get("source_id", "")
        if sid and sid not in existing_sids:
            new_sources.append(make_source_record(entry))
            existing_sids.add(sid)

    if new_sources:
        SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SOURCES_PATH, "a", encoding="utf-8") as f:
            for src in new_sources:
                f.write(json.dumps(src, ensure_ascii=False) + "\n")
        print(f"✓  Created {len(new_sources)} new source record(s) in sources.jsonl")

    # ── Append to entries.jsonl ───────────────────────────────
    ENTRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ENTRIES_PATH, "a", encoding="utf-8") as f:
        for entry in to_merge:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"✓  Merged {len(to_merge)} entries into {ENTRIES_PATH.relative_to(REPO)}")
    if commented:
        print()
        print("Entries merged with reviewer notes (may need follow-up):")
        for eid in commented:
            cmt = decisions.get(eid, {}).get("comment", "")
            print(f"  ⚑  {eid}")
            print(f"     Note: {cmt}")
    print()
    print("Pending/decisions files retained as audit trail.")

    # ── Prune stale entries from audit_decisions.json ─────────
    audit_decisions_path = REVIEW_DIR / "audit_decisions.json"
    if audit_decisions_path.exists():
        try:
            audit_dec: dict = json.loads(audit_decisions_path.read_text(encoding="utf-8"))
            stale = [eid for eid in audit_dec if eid not in existing_ids]
            if stale:
                for eid in stale:
                    del audit_dec[eid]
                audit_decisions_path.write_text(
                    json.dumps(audit_dec, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"✓  Pruned {len(stale)} stale decisions from audit_decisions.json")
        except Exception as e:
            print(f"⚠  Could not prune audit_decisions.json: {e}")

    print(f"Run `python3 scripts/validate_indexes.py` to verify the updated index.")


if __name__ == "__main__":
    main()
