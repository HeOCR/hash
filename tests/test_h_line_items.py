"""The H line items cover exactly the registered H pages, carry no text, and stay on their images."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "data" / "eval" / "h_line_items_v1.json"
SETS = ("h_eval_v1", "h_eval_v1_1")


def manifests():
    rows = {}
    for s in SETS:
        p = ROOT / "data" / "eval" / s / "manifest.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["entry_id"]] = dict(r, eval_set=s)
    return rows


def test_line_items():
    d = json.loads(ITEMS.read_text(encoding="utf-8"))
    rows = manifests()
    for s in SETS:
        assert d["manifest_sha256"][s] == hashlib.sha256(
            (ROOT / "data" / "eval" / s / "manifest.jsonl").read_bytes()).hexdigest()
    assert d["segmenter"]["recognition"] == "none"
    keys = [p["page_key"] for p in d["pages"]]
    assert sorted(keys) == sorted(rows), "line items must cover exactly the registered H pages"
    for p in d["pages"]:
        r = rows[p["page_key"]]
        assert (p["image"], p["image_sha256"], p["eval_set"], p["stratum"]) == (
            r["image_path"], r["image_sha256"], r["eval_set"], r["stratum"])
        assert p["segmenter"] in ("blla", "legacy") and p["page_flag"] in (None, "no_hebrew_text", "poor")
        assert p["prefill_source"] is None and p["prefill_from_stock"] is False
        W, H = p["image_size"]
        assert [ln["i"] for ln in p["lines"]] == list(range(len(p["lines"])))
        for ln in p["lines"]:
            assert ln["prefill"] == "", "no machine text may reach an H reference"
            if ln["box"] is None:
                assert ln["box_status"] == "no_polygon"
                continue
            x0, y0, x1, y1 = ln["box"]
            assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H
