"""
HASH Review App — local review UI for pending and verified scan batches.

Run:
    cd /path/to/hash
    pip install flask
    python scripts/review_app/app.py

Then open http://localhost:5757
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as url_quote, unquote as url_unquote
from flask import Flask, abort, jsonify, render_template, request, send_file

# ── Paths ────────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
REPO = HERE.parent.parent   # hash/ root
DATA = REPO / "data"
REVIEW_DIR = DATA / "review"
SCANS_DIR = DATA / "scans"
INDEX_DIR = DATA / "index"
AUDIT_DECISIONS_PATH = REVIEW_DIR / "audit_decisions.json"

app = Flask(__name__, template_folder=str(HERE / "templates"),
            static_folder=str(HERE / "static"))


# ── Data helpers ─────────────────────────────────────────────────────────────

def load_jsonl(path):
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except FileNotFoundError:
        pass
    return records


def load_sources():
    return {s["source_id"]: s for s in load_jsonl(INDEX_DIR / "sources.jsonl")}


def load_verified_entries():
    """Return entries grouped by source_id."""
    entries = load_jsonl(INDEX_DIR / "entries.jsonl")
    by_source = {}
    for e in entries:
        sid = e["source_id"]
        by_source.setdefault(sid, []).append(e)
    return by_source


def load_pending_batches():
    """
    Return list of dicts:
      { batch_id, label, pending_path, decisions_path, entries: [...], decisions: {...} }
    A pending batch is any data/review/*_pending.jsonl file.
    """
    batches = []
    for p in sorted(REVIEW_DIR.glob("*_pending.jsonl")):
        batch_id = p.stem.replace("_pending", "")
        entries = load_jsonl(p)
        dec_path = REVIEW_DIR / f"{batch_id}_decisions.json"
        decisions = {}
        if dec_path.exists():
            try:
                decisions = json.loads(dec_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        batches.append({
            "batch_id": batch_id,
            "label": batch_id.replace("_", " ").title(),
            "pending_path": str(p),
            "decisions_path": str(dec_path),
            "entries": entries,
            "decisions": decisions,
            "total": len(entries),
            "approved": sum(1 for v in decisions.values() if v.get("status") == "approved"),
            "rejected": sum(1 for v in decisions.values() if v.get("status") == "rejected"),
            "commented": sum(1 for v in decisions.values()
                             if v.get("comment", "").strip()),
        })
    return batches


def _entry_image_url(entry, role="thumbnail"):
    """Return the app URL for serving an entry's image file."""
    for f in entry.get("files", []):
        if f["role"] == role and f.get("local_path"):
            # local_path is relative to repo root
            return f"/scan/{f['local_path']}"
    # fall back to the other role
    other = "original" if role == "thumbnail" else "thumbnail"
    for f in entry.get("files", []):
        if f["role"] == other and f.get("local_path"):
            return f"/scan/{f['local_path']}"
    return None


def load_audit_decisions():
    try:
        return json.loads(AUDIT_DECISIONS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _transcript_info(entry):
    """Return display info about the transcription field."""
    t = entry.get("transcription") or {}
    status = t.get("status", "none")
    r = t.get("rights") or {}
    lic = r.get("license_expression")
    return {
        "status": status,
        "license": lic,
        "source_url": t.get("source_url"),
        "has_transcript": status not in ("none", "unknown", None, ""),
    }


def _writer_slug(name):
    return url_quote(name or "unknown", safe="")


def _group_by_writer(entries):
    """Return list of writer-group dicts sorted by entry count desc."""
    by_w = {}
    for e in entries:
        creators = e.get("creators") or []
        if not creators:
            key = "__unknown__"
            name = "Unknown Author"
            death_year = None
            authority_url = None
        else:
            c = creators[0]
            name = c.get("name") or "Unknown"
            key = name
            death_year = c.get("death_year")
            authority_url = c.get("authority_url")
        if key not in by_w:
            by_w[key] = {
                "slug": _writer_slug(key),
                "name": name,
                "death_year": death_year,
                "authority_url": authority_url,
                "entries": [],
            }
        by_w[key]["entries"].append(e)

    groups = []
    for key, g in by_w.items():
        elist = g["entries"]
        years = []
        for e2 in elist:
            d = e2.get("dates") or {}
            created = d.get("created", "") if isinstance(d, dict) else ""
            if created:
                try:
                    years.append(int(str(created)[:4]))
                except (ValueError, TypeError):
                    pass
        g["entry_count"] = len(elist)
        g["date_range"] = (f"{min(years)}–{max(years)}" if years else None)
        g["sample_thumb"] = next(
            (_entry_image_url(e2, "thumbnail") for e2 in elist
             if _entry_image_url(e2, "thumbnail")), None)
        groups.append(g)
    return sorted(groups, key=lambda g: (-g["entry_count"], g["name"]))


def _group_by_source(entries, sources):
    """Return list of source-group dicts sorted by entry count desc."""
    by_s = {}
    for e in entries:
        sid = e["source_id"]
        if sid not in by_s:
            src = sources.get(sid, {})
            by_s[sid] = {
                "source_id": sid,
                "title": src.get("title") or sid,
                "provider": src.get("provider") or "",
                "entries": [],
            }
        by_s[sid]["entries"].append(e)

    groups = []
    for sid, g in by_s.items():
        elist = g["entries"]
        lics = sorted({(e.get("rights") or {}).get("license_expression")
                       for e in elist} - {None})
        g["entry_count"] = len(elist)
        g["licenses"] = lics
        g["sample_thumb"] = next(
            (_entry_image_url(e, "thumbnail") for e in elist
             if _entry_image_url(e, "thumbnail")), None)
        groups.append(g)
    return sorted(groups, key=lambda g: (-g["entry_count"], g["title"]))


def rights_warning(entry):
    """Return a warning string if rights are unclear, or None if clean."""
    r = entry.get("rights", {})
    if not r:
        return "No rights information recorded for this entry."
    basis  = r.get("rights_basis", "unknown")
    lic    = r.get("license_expression")
    vstatus = r.get("verification_status", "unverified")
    if basis == "unknown" or not lic:
        return "License unknown — rights basis not established."
    if vstatus == "unverified":
        return "License unverified — evidence text not yet checked against source page."
    return None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    sources = load_sources()
    all_entries = load_jsonl(INDEX_DIR / "entries.jsonl")
    pending_batches = load_pending_batches()
    writer_groups = _group_by_writer(all_entries)
    source_groups = _group_by_source(all_entries, sources)
    return render_template(
        "index.html",
        pending_batches=pending_batches,
        writer_groups=writer_groups,
        source_groups=source_groups,
        total_entries=len(all_entries),
    )


@app.route("/source/<source_id>")
def source_detail(source_id):
    sources = load_sources()
    all_entries = load_jsonl(INDEX_DIR / "entries.jsonl")
    entries = [e for e in all_entries if e["source_id"] == source_id]
    if not entries:
        abort(404)
    for e in entries:
        e["_thumb_url"]  = _entry_image_url(e, "thumbnail")
        e["_orig_url"]   = _entry_image_url(e, "original")
        e["_transcript"] = _transcript_info(e)
        e["_rights_warning"] = rights_warning(e)
    src = sources.get(source_id, {})
    return render_template(
        "group.html",
        group_type="source",
        group_title=src.get("title") or source_id,
        group_subtitle=src.get("provider") or "",
        authority_url=None,
        back_param="source",
        entries=entries,
    )


@app.route("/writer/<slug>")
def writer_detail(slug):
    name = url_unquote(slug)
    all_entries = load_jsonl(INDEX_DIR / "entries.jsonl")

    if slug == _writer_slug("__unknown__"):
        entries = [e for e in all_entries if not (e.get("creators") or [])]
        display_name = "Unknown Author"
        death_year = None
        authority_url = None
    else:
        entries = [e for e in all_entries
                   if any(c.get("name") == name
                          for c in (e.get("creators") or []))]
        display_name = name
        death_year = None
        authority_url = None
        for e in entries:
            for c in (e.get("creators") or []):
                if c.get("name") == name:
                    death_year = c.get("death_year")
                    authority_url = c.get("authority_url")
                    break
            if death_year is not None:
                break

    if not entries:
        abort(404)
    for e in entries:
        e["_thumb_url"]  = _entry_image_url(e, "thumbnail")
        e["_orig_url"]   = _entry_image_url(e, "original")
        e["_transcript"] = _transcript_info(e)
        e["_rights_warning"] = rights_warning(e)

    subtitle = f"d. {death_year}" if death_year else ""
    return render_template(
        "group.html",
        group_type="writer",
        group_title=display_name,
        group_subtitle=subtitle,
        authority_url=authority_url,
        back_param="writer",
        entries=entries,
    )


@app.route("/review/<batch_id>")
def review_batch(batch_id):
    batches = {b["batch_id"]: b for b in load_pending_batches()}
    if batch_id not in batches:
        abort(404)
    batch = batches[batch_id]
    sources = load_sources()
    source = sources.get("openn__zucker_ketubah_collection", {})

    # Attach image URLs to each entry
    for e in batch["entries"]:
        e["_thumb_url"] = _entry_image_url(e, "thumbnail")
        e["_orig_url"] = _entry_image_url(e, "original")
        e["_decision"] = batch["decisions"].get(e["entry_id"], {})

    return render_template(
        "batch.html",
        batch=batch,
        source=source,
    )


@app.route("/scan/<path:rel_path>")
def serve_scan(rel_path):
    """Serve a scan image by its repo-relative path."""
    full = REPO / rel_path
    if not full.exists():
        abort(404)
    # Only serve image files
    suf = full.suffix.lower()
    if suf not in (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".pdf"):
        abort(403)
    return send_file(str(full))


@app.route("/api/batch/<batch_id>/decide", methods=["POST"])
def save_decisions(batch_id):
    """Save review decisions for a batch."""
    batches = {b["batch_id"]: b for b in load_pending_batches()}
    if batch_id not in batches:
        return jsonify({"error": "batch not found"}), 404

    data = request.get_json(force=True)
    # data = { entry_id: { status: "approved"|"rejected", comment: "..." }, ... }

    dec_path = Path(batches[batch_id]["decisions_path"])
    dec_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    batch = batches[batch_id]
    rejected = sum(1 for v in data.values() if v.get("status") == "rejected")
    approved = len(batch["entries"]) - rejected
    return jsonify({"ok": True, "approved": approved, "rejected": rejected})


@app.route("/api/batch/<batch_id>/status")
def batch_status(batch_id):
    batches = {b["batch_id"]: b for b in load_pending_batches()}
    if batch_id not in batches:
        return jsonify({"error": "not found"}), 404
    b = batches[batch_id]
    return jsonify({
        "batch_id": batch_id,
        "total": b["total"],
        "rejected": b["rejected"],
        "approved": b["total"] - b["rejected"],
    })


@app.route("/audit")
def audit():
    sources    = load_sources()
    entries    = load_jsonl(INDEX_DIR / "entries.jsonl")
    decisions  = load_audit_decisions()

    for e in entries:
        e["_thumb_url"] = _entry_image_url(e, "thumbnail")
        e["_orig_url"]  = _entry_image_url(e, "original")
        e["_decision"]  = decisions.get(e["entry_id"], {})
        src = sources.get(e["source_id"], {})
        e["_source_title"]    = src.get("title") or e.get("holding_institution") or e["source_id"]
        e["_source_provider"] = src.get("provider") or e.get("holding_institution", "")
        e["_rights_warning"]  = rights_warning(e)
        e["_transcript"]      = _transcript_info(e)

    rejected  = sum(1 for d in decisions.values() if d.get("status") == "rejected")
    commented = sum(1 for d in decisions.values() if d.get("comment", "").strip())
    warned    = sum(1 for e in entries if e["_rights_warning"])

    return render_template(
        "audit.html",
        entries=entries,
        decisions=decisions,
        total=len(entries),
        rejected=rejected,
        commented=commented,
        warned=warned,
    )


@app.route("/api/audit/decide", methods=["POST"])
def save_audit_decisions():
    data = request.get_json(force=True)
    AUDIT_DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_DECISIONS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rejected = sum(1 for v in data.values() if v.get("status") == "rejected")
    return jsonify({"ok": True, "rejected": rejected, "total": len(data)})


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5757))
    print(f"\n  HASH Review  →  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
