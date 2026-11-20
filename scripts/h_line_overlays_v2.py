"""Draw H line items v2 on their pages, coloured by box_source, for the agent check (images are not committed).

    python3 scripts/h_line_overlays_v2.py data/eval/h_line_items_v2.json OUT_DIR [ENTRY_ID ...]

Colours: blla blue, legacy teal, joined green, split orange, added magenta, manual red; dropped boxes grey. Each line's
reading-order number is drawn at its right end.
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
C = {"blla": "#1f4fff", "legacy": "#008080", "joined": "#00a000", "split": "#ff8000", "added": "#e000e0",
     "manual": "#ff0000"}


def main():
    items, out, keys = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    pages = {p["page_key"]: p for p in json.loads(items.read_text(encoding="utf-8"))["pages"]}
    for k in keys or list(pages):
        p = pages[k]
        im = ImageOps.exif_transpose(Image.open(ROOT / p["image"])).convert("RGB")
        d = ImageDraw.Draw(im)
        w = max(2, im.width // 500)
        for x in p.get("dropped", []):
            d.rectangle(x["box"], outline="#909090", width=w)
        for ln in p["lines"]:
            c = C.get(ln["box_source"], "#000000")
            d.rectangle(ln["box"], outline=c, width=w)
            d.text((ln["box"][2] + 4, ln["box"][1]), str(ln["i"]), fill=c, font_size=max(14, im.width // 60))
        s = 1500 / max(im.size)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)))
        im.save(out / f"{k}.png")


if __name__ == "__main__":
    main()
