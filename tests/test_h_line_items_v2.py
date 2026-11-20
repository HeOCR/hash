"""H line items v2: every page of its sets, the v1 page records unchanged, no text, boxes on the image, stable ids."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "data" / "eval" / "h_line_items_v2.json"
V1 = ROOT / "data" / "eval" / "h_line_items_v1.json"
SOURCES = {"blla", "legacy", "joined", "split", "added", "manual"}


def test_line_items_v2():
    d = json.loads(ITEMS.read_text(encoding="utf-8"))
    v1 = {p["page_key"]: p for p in json.loads(V1.read_text(encoding="utf-8"))["pages"]}
    assert d["schema"] == "h_line_items.v2" and d["recognition"] == "none"
    assert d["from"]["sha256"] == hashlib.sha256(V1.read_bytes()).hexdigest()
    assert d["script_dirty"] is False
    want = sorted(k for k, p in v1.items() if p["eval_set"] in d["sets"])
    assert sorted(p["page_key"] for p in d["pages"]) == want, "v2 must cover exactly the pages of its sets"
    for p in d["pages"]:
        q = v1[p["page_key"]]
        for k in ("image", "image_sha256", "image_size", "eval_set", "stratum", "exif_orientation"):
            assert p[k] == q[k], (p["page_key"], k)
        W, H = p["image_size"]
        assert [ln["i"] for ln in p["lines"]] == list(range(len(p["lines"])))
        ids = [ln["id"] for ln in p["lines"]]
        assert len(ids) == len(set(ids)), p["page_key"]
        v1_ids = {f"v1:{ln['i']}" for ln in q["lines"]}
        for ln in p["lines"]:
            assert ln["prefill"] == "", "no machine text may reach an H reference"
            assert ln["box_source"] in SOURCES
            assert set(ln["v1_ids"]) <= v1_ids
            if ln["id"].startswith("v1:"):
                assert ln["id"] in v1_ids
            x0, y0, x1, y1 = ln["box"]
            assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H
