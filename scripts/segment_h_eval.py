"""Line boxes for the H eval set (h_eval_v1 + h_eval_v1_1), for from-scratch line-by-line typing (heocr-lead, 2026-11-18).

    python3 scripts/segment_h_eval.py --out data/eval/h_line_items_v1.json

Every page in the two registered manifests is segmented with kraken's default baseline segmenter (blla.mlmodel bundled
with kraken, Apache-2.0), text direction horizontal-rl. Segmentation only: no recognition model is loaded or run, so no
machine text exists for these pages and every line's `prefill` is "". Lines keep kraken's reading order (`i`).
Each line has `polygon` (kraken boundary), `baseline` and `box` [x0, y0, x1, y1] (the polygon's bounds, clipped to the
image), in image pixels as displayed: where the file has an EXIF orientation (2-8), it is applied first, as browsers do, and
the page records `exif_orientation` and `image_size` in that displayed frame (tag 0 is invalid and read as 1). A line kraken gives
no polygon for gets `box` null and `box_status` "no_polygon". Nothing is guessed or filtered.
Page overrides come from data/eval/h_line_items_overrides.json (data-collection's agent visual check, committed before the
run): on pages listed under `segmenter` as "legacy", kraken's legacy box segmenter (nlbin + pageseg.segment, Apache-2.0)
replaces blla; its lines have a rectangle `polygon`, no baseline, and `box_status` "segmented_legacy". `page_flags`
("no_hebrew_text", "poor") are copied to the page as `page_flag`; null otherwise.
The output follows heocr-restricted-eval's midcentury_line_items.v1 shape.
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS = ("h_eval_v1", "h_eval_v1_1")
TEXT_DIRECTION = "horizontal-rl"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    import kraken
    from kraken import binarization, blla, pageseg
    from PIL import Image, ImageOps

    model = Path(kraken.__file__).parent / "blla.mlmodel"
    rows, man_sha = [], {}
    for s in SETS:
        p = ROOT / "data" / "eval" / s / "manifest.jsonl"
        man_sha[s] = sha(p)
        rows += [dict(json.loads(l), eval_set=s) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len({r["entry_id"] for r in rows}) == len(rows), "a page is in two manifests"

    ov = json.loads((ROOT / "data" / "eval" / "h_line_items_overrides.json").read_text(encoding="utf-8"))
    assert set(ov["segmenter"]) | set(ov["page_flags"]) <= {r["entry_id"] for r in rows}, "override for an unknown page"
    items, stats = [], Counter()
    for r in rows[: a.limit]:
        img = ROOT / r["image_path"]
        assert sha(img) == r["image_sha256"], f"{r['entry_id']}: image sha256 differs from the manifest"
        im = Image.open(img)
        orient = im.getexif().get(0x0112, 1) or 1
        if orient != 1:
            im = ImageOps.exif_transpose(im)
        W, H = im.size
        engine = ov["segmenter"].get(r["entry_id"], "blla")
        lines = []
        if engine == "legacy":
            seg = pageseg.segment(binarization.nlbin(im.convert("RGB")), text_direction=TEXT_DIRECTION)
            for i, ln in enumerate(seg.lines):
                x0, y0, x1, y1 = (int(v) for v in ln.bbox)
                box = [max(0, x0), max(0, y0), min(W, x1), min(H, y1)]
                stats["segmented_legacy"] += 1
                lines.append({"i": i, "prefill": "", "box": box, "box_status": "segmented_legacy",
                              "polygon": [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
                              "baseline": None, "region": None, "match": None, "tier_a": None, "bidi_risk": None})
            seg.regions = None
        else:
            seg = blla.segment(im.convert("RGB"), text_direction=TEXT_DIRECTION, model=None)
        for i, ln in enumerate(seg.lines if engine == "blla" else []):
            poly = [[int(x), int(y)] for x, y in ln.boundary] if ln.boundary else None
            box, status = None, "no_polygon"
            if poly:
                xs, ys = [p[0] for p in poly], [p[1] for p in poly]
                box, status = [max(0, min(xs)), max(0, min(ys)), min(W, max(xs)), min(H, max(ys))], "segmented"
            stats[status] += 1
            lines.append({"i": i, "prefill": "", "box": box, "box_status": status, "polygon": poly,
                          "baseline": [[int(x), int(y)] for x, y in ln.baseline] if ln.baseline else None,
                          "region": (ln.regions or [None])[0],
                          "match": None, "tier_a": None, "bidi_risk": None})
        items.append({"page_key": r["entry_id"], "eval_set": r["eval_set"], "stratum": r["stratum"],
                      "source_id": r["source_id"], "image": r["image_path"], "image_sha256": r["image_sha256"],
                      "image_size": [W, H], "exif_orientation": orient,
                      "segmenter": engine, "page_flag": ov["page_flags"].get(r["entry_id"]),
                      "coordinate_frame": "display", "prefill_source": None, "prefill_from_stock": False,
                      "regions": len(seg.regions.get("text", [])) if isinstance(seg.regions, dict) else None,
                      "lines": lines})
        print(r["entry_id"], len(lines), flush=True)

    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "scripts/segment_h_eval.py"],
                           capture_output=True, text=True).stdout.strip()
    res = {
        "schema": "h_line_items.v1", "shape_of": "heocr-restricted-eval midcentury_line_items.v1",
        "manifest_sha256": man_sha, "rule": __doc__.strip().splitlines()[0],
        "segmenter": {"engine": "kraken", "engine_version": kraken.__version__ if hasattr(kraken, "__version__") else
                      subprocess.run(["kraken", "--version"], capture_output=True, text=True).stdout.strip(),
                      "engine_licence": "Apache-2.0", "model": "blla.mlmodel (kraken default, bundled)",
                      "model_sha256": sha(model), "model_licence": "Apache-2.0",
                      "text_direction": TEXT_DIRECTION, "recognition": "none",
                      "fallback": "kraken legacy pageseg (nlbin), on the pages in h_line_items_overrides.json"},
        "overrides_sha256": sha(ROOT / "data" / "eval" / "h_line_items_overrides.json"),
        "page_flags": dict(Counter(p["page_flag"] for p in items if p["page_flag"])),
        "hash_commit": head, "script": "scripts/segment_h_eval.py", "script_dirty": bool(dirty),
        "pages_total": len(items), "lines_total": sum(len(p["lines"]) for p in items),
        "stats": dict(stats), "pages": items,
        "signed": "data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource",
    }
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("pages_total", "lines_total", "stats", "script_dirty")}))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    main()
