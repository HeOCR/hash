"""Draw the H line items on their pages for the coverage check (data/eval/H_LINE_ITEMS.md).

    python3 scripts/h_line_overlays.py data/eval/h_line_items_v1.json OUT_DIR ENTRY_ID [ENTRY_ID ...]

Each line polygon is drawn with its reading-order number at the line's right end. Output images are not committed.
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
COLOURS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080"]


def main():
    items, out, keys = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    pages = {p["page_key"]: p for p in json.loads(items.read_text(encoding="utf-8"))["pages"]}
    for k in keys:
        p = pages[k]
        im = ImageOps.exif_transpose(Image.open(ROOT / p["image"])).convert("RGB")
        d = ImageDraw.Draw(im)
        w = max(2, im.width // 600)
        for ln in p["lines"]:
            c = COLOURS[ln["i"] % len(COLOURS)]
            if ln["polygon"]:
                d.line([tuple(q) for q in ln["polygon"]] + [tuple(ln["polygon"][0])], fill=c, width=w)
            if ln["box"]:
                d.text((ln["box"][2] + 3, ln["box"][1]), str(ln["i"]), fill=c)
        s = 1600 / max(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)))
        im.save(out / f"{k}.png")
        print(k, len(p["lines"]))


if __name__ == "__main__":
    main()
