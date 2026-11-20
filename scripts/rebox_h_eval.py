"""H line items v2: repair the v1 line boxes, geometry only (data-collection, heocr-lead's task of 2026-11-20).

    python3 scripts/rebox_h_eval.py --out data/eval/h_line_items_v2.json [--sets h_eval_v1] [--pages KEY ...]

Input: data/eval/h_line_items_v1.json (kraken blla + legacy boxes) and the page images, which are checked by sha256.
Overrides: data/eval/h_line_items_v2_overrides.json (data-collection's agent check, committed before the final run).
No recognition model is loaded and no text is produced: every `prefill` is "".

Rules, applied per page and in this order:
1. **Drop.** A box is dropped (and listed in the page's `dropped`, with a reason) when it is:
   - `stamp`: most of its ink is strongly coloured, on a page whose ink is mostly not coloured (under 25%);
   - `empty`: it holds almost no ink.
   Faint boxes that may be bleed-through are only listed in `suspect` for the agent check, never dropped automatically.
2. **Split.** A box taller than SPLIT_H × the page's median line height is cut at the deepest valley of its horizontal
   ink profile, when both parts hold real ink rows. This repeats until no part is too tall.
3. **Join.** Boxes in the same text row are joined into one line. "Same row" means their core bands (the box's middle
   60%) overlap by at least JOIN_OVERLAP of the smaller band, and the horizontal gap between them is at most JOIN_GAP
   × the line height. When both pieces have kraken baselines, one baseline, extended, must pass within 0.35 × the
   line height of the other (slanted writing). A join is refused if it would make the line wider than MAX_ASPECT × its height (contrib's
   40:1 limit), or if it would cross a gutter: a wide blank vertical band, or a spread's binding. On a landscape page,
   the binding is the x near the centre that at most 3% of v1 boxes cross, within 3% of the centre; a page's `spread`
   override decides instead.
4. **Add.** Ink not covered by any box (ruling, grid lines and borders removed first) is grouped into rows. A row
   becomes a new line only if it has 2 or more ink components as dark as the page's boxed writing, real ink density
   and a line's size.
   Then a box lying 70% or more inside a bigger box is folded into it, and the join is run again.
5. **Overrides** from the agent check, per page:
   - `drop`: line ids;
   - `add`: boxes in image pixels;
   - `add_ov`: boxes in the overlay frame (longest side 1500);
   - `flag`: a page flag such as "poor_boxes";
   - `spread`: true or false, to override spread detection;
   - `keep_v1`: true keeps the page's v1 boxes unchanged, where the check found the repairs worse.
   A manual box replaces every box it mostly covers, and it is tightened to its ink.
6. **Order.** Columns run right to left (split at gutters), and lines run top to bottom within a column.

**Line ids.** A line taken unchanged from v1 keeps id `v1:<i>`. Joined, split, added and manual lines get new ids
(`j:<ids>`, `s:<id>:<k>`, `a:<k>`, `m:<k>`). `box_source` and `merged_from` record where each line came from.
`box` is the tight ink rectangle (contrib crops by it). `polygon` is the joined hull or the rectangle.
Signed: data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SPLIT_H = 1.8
JOIN_MAX_GROW = 1.3  # a join may not make the line taller than 1.3 x its taller piece (v1.1 run on)
RESPLIT_H = 1.6  # after joining, joined and added lines taller than this x median line are split again (v1.1 run on)
JOIN_OVERLAP = 0.5
JOIN_GAP = 2.5
MAX_ASPECT = 40.0
EMPTY_INK = 0.004
STAMP_FRAC = 0.5
RESPLIT = JOIN_CAP = False  # set by --v11-rules; off reproduces the h_eval_v1 file
OVERLAY_FRAME = 1500  # overrides may give boxes as `add_ov`, in the frame of h_line_overlays_v2.py (longest side 1500)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(page):
    im = Image.open(ROOT / page["image"])
    if (im.getexif().get(0x0112, 1) or 1) != 1:
        im = ImageOps.exif_transpose(im)
    rgb = np.asarray(im.convert("RGB"))
    assert [rgb.shape[1], rgb.shape[0]] == page["image_size"], page["page_key"]
    return rgb


def ink_mask(rgb):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    k = max(15, (min(g.shape) // 40) | 1)
    th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, k, 15)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # remove ruling, grid lines and page borders: long straight strokes are not writing
    H, W = g.shape
    hor = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, W // 25), 1)))
    ver = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, H // 25))))
    th = cv2.bitwise_and(th, cv2.bitwise_not(cv2.bitwise_or(hor, ver)))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    colour = (hsv[..., 1] > 90) & (hsv[..., 2] > 60)
    return th > 0, colour


def tight(box, ink):
    x0, y0, x1, y1 = box
    sub = ink[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    if len(xs) == 0:
        return None
    return [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max() + 1), int(y0 + ys.max() + 1)]


def core(b):
    h = b[3] - b[1]
    return b[1] + 0.2 * h, b[3] - 0.2 * h


def rect(b):
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]


def gutters(ink, W):
    """x ranges of tall blank vertical bands in the middle 60% of the page (spread gutters)."""
    col = ink.mean(axis=0)
    blank = col < 0.002
    out, x = [], int(0.2 * W)
    while x < int(0.8 * W):
        if blank[x]:
            s = x
            while x < int(0.8 * W) and blank[x]:
                x += 1
            if x - s > W * 0.03:
                out.append((s, x))
        x += 1
    return out


def process(page, ov):
    rgb = load(page)
    H, W = rgb.shape[:2]
    ink, colour = ink_mask(rgb)
    lines, dropped, suspect = [], [], []
    # colour marks a stamp only when the page's writing is not itself coloured (blue or violet ink is common)
    page_colour = (ink & colour).sum() / max(ink.sum(), 1)
    stamp_rule = page_colour < 0.25
    for ln in page["lines"]:
        if not ln["box"]:
            continue
        b = [max(0, ln["box"][0]), max(0, ln["box"][1]), min(W, ln["box"][2]), min(H, ln["box"][3])]
        sub, csub = ink[b[1]:b[3], b[0]:b[2]], colour[b[1]:b[3], b[0]:b[2]]
        n = sub.sum()
        lid = f"v1:{ln['i']}"
        if sub.size == 0 or n / sub.size < EMPTY_INK:
            dropped.append({"id": lid, "box": b, "reason": "empty"}); continue
        if stamp_rule and (sub & csub).sum() / max(n, 1) > STAMP_FRAC:
            dropped.append({"id": lid, "box": b, "reason": "stamp"}); continue
        lines.append({"id": lid, "box": b, "src": page["segmenter"] if page["segmenter"] == "legacy" else "blla",
                      "from": [lid], "poly": ln["polygon"], "baseline": ln["baseline"], "region": ln["region"]})
    hs = [l["box"][3] - l["box"][1] for l in lines]
    mh = float(np.median(hs)) if hs else 40.0
    # faint boxes: median grey of their ink much lighter than the page's text ink
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    page_ink = np.median(g[ink]) if ink.any() else 0
    for l in lines:
        x0, y0, x1, y1 = l["box"]
        m = ink[y0:y1, x0:x1]
        if m.any() and np.median(g[y0:y1, x0:x1][m]) > page_ink + 45:
            suspect.append({"id": l["id"], "box": l["box"], "why": "faint (bleed-through?)"})
    def split_tall(lines, limit, only=None):
        out = []
        for l in lines:
            stack = [l]
            while stack:
                c = stack.pop()
                x0, y0, x1, y1 = c["box"]
                if (only and c["src"] not in only) or y1 - y0 <= limit * mh:
                    out.append(c); continue
                prof = ink[y0:y1, x0:x1].mean(axis=1)
                lo, hi = int(0.3 * mh), (y1 - y0) - int(0.3 * mh)
                if hi <= lo:
                    out.append(c); continue
                cut = lo + int(np.argmin(prof[lo:hi]))
                top, bot = prof[:cut], prof[cut:]
                if prof[cut] > 0.5 * prof.max() or (top > 0.05).sum() < 0.3 * mh or (bot > 0.05).sum() < 0.3 * mh:
                    out.append(c); continue
                for k, (a, z) in enumerate(((y0, y0 + cut), (y0 + cut, y1))):
                    tb = tight([x0, a, x1, z], ink)
                    if tb:
                        cid = c["id"] or ("j:" + "+".join(c["from"]) if c["from"] else "x")
                        stack.append({"id": f"s:{cid}:{k}", "box": tb, "src": "split", "from": c["from"], "poly": None,
                                      "baseline": None, "region": c["region"]})
        return out

    # 2. split
    lines = split_tall(lines, SPLIT_H)
    gut = gutters(ink, W)
    # spreads: on a landscape page, the x near the centre that the fewest v1 boxes cross is the binding, when at most 3%
    # of v1 boxes cross it and it lies within 3% of the centre (blla rarely draws a line across a binding). A page's
    # `spread` override (true/false) decides instead.
    v1b = [l["box"] for l in page["lines"] if l["box"]]
    spread = ov.get(page["page_key"], {}).get("spread")
    if v1b and (spread is True or (spread is None and W > 1.2 * H)):
        xs = range(int(0.38 * W), int(0.62 * W), max(1, W // 400))
        best = min(xs, key=lambda x: (sum(b[0] < x < b[2] for b in v1b), abs(x - W / 2)))
        auto = sum(b[0] < best < b[2] for b in v1b) <= 0.03 * len(v1b) and abs(best / W - 0.5) <= 0.03
        if spread is True or auto:
            gut.append((best - 2, best + 2))
    def crosses(a, b):
        """True if the union of a and b would span a gutter."""
        return any(min(a[0], b[0]) < s_ and max(a[2], b[2]) > e_ for s_, e_ in gut)
    def join_all(lines):
        lines.sort(key=lambda l: -l["box"][2])
        merged = True
        while merged:
            merged = False
            for i in range(len(lines)):
                for j in range(i + 1, len(lines)):
                    a, b = lines[i]["box"], lines[j]["box"]
                    (ca0, ca1), (cb0, cb1) = core(a), core(b)
                    ov_ = min(ca1, cb1) - max(ca0, cb0)
                    if ov_ < JOIN_OVERLAP * min(ca1 - ca0, cb1 - cb0):
                        continue
                    h = max(a[3] - a[1], b[3] - b[1])
                    gap = max(a[0], b[0]) - min(a[2], b[2])
                    ba, bb = lines[i]["baseline"], lines[j]["baseline"]
                    if ba and bb and len(ba) >= 2 and len(bb) >= 2:
                        # slanted writing: B's baseline must lie on A's baseline extended (within 0.35 x line height)
                        (xa0, ya0), (xa1, ya1) = ba[0], ba[-1]
                        slope = (ya1 - ya0) / (xa1 - xa0) if xa1 != xa0 else 0.0
                        xb = (bb[0][0] + bb[-1][0]) / 2
                        yb = (bb[0][1] + bb[-1][1]) / 2
                        if abs(ya0 + slope * (xb - xa0) - yb) > 0.35 * mh:
                            continue
                    if gap > JOIN_GAP * h or crosses(a, b):
                        continue
                    nb = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    if JOIN_CAP and (nb[3] - nb[1]) > JOIN_MAX_GROW * max(a[3] - a[1], b[3] - b[1]):
                        continue  # the union would swallow a neighbouring row
                    if (nb[2] - nb[0]) > MAX_ASPECT * max(1, min(a[3] - a[1], b[3] - b[1])):
                        continue
                    if gap < -0.5 * min(a[2] - a[0], b[2] - b[0]):  # heavy horizontal overlap: two lines, not pieces
                        continue
                    pts = [q for l in (lines[i], lines[j]) for q in (l["poly"] or rect(l["box"]))]
                    hull = cv2.convexHull(np.array(pts, np.int32)).reshape(-1, 2).tolist()
                    bl = None
                    if lines[i]["baseline"] and lines[j]["baseline"]:
                        bl = sorted(lines[i]["baseline"] + lines[j]["baseline"], key=lambda q: -q[0])
                    lines[i] = {"id": None, "box": nb, "src": "joined", "from": lines[i]["from"] + lines[j]["from"],
                                "poly": hull, "baseline": bl, "region": lines[i]["region"]}
                    del lines[j]; merged = True; break
                if merged:
                    break
        return lines

    # 3. join (greedy, right to left within rows)
    lines = join_all(lines)
    # 4. add missed ink rows
    cover = np.zeros_like(ink, np.uint8)
    for l in lines:
        x0, y0, x1, y1 = l["box"]
        pad = int(0.3 * mh)
        cover[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = 1
    for d in dropped:
        x0, y0, x1, y1 = d["box"]
        cover[y0:y1, x0:x1] = 1
    rest = (ink & (cover == 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(rest, 8)
    # writing ink: as dark as the page's boxed text (grid lines and faint bleed-through are lighter)
    boxed = np.zeros_like(ink)
    for l in lines:
        x0, y0, x1, y1 = l["box"]
        boxed[y0:y1, x0:x1] = True
    text_ink = np.median(g[ink & boxed]) if (ink & boxed).any() else page_ink
    comps = []
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if not (a > 0.05 * mh * mh and 0.3 * mh <= h <= 2.5 * mh and w < 0.6 * W and h < 0.6 * H):
            continue
        if np.median(g[y:y + h, x:x + w][lab[y:y + h, x:x + w] == k]) > text_ink + 35:
            continue
        comps.append(st[k])
    rows, ncomp = [], []
    for x, y, w, h, a in sorted(comps, key=lambda s: -(s[0] + s[2])):
        b = [int(x), int(y), int(x + w), int(y + h)]
        for t, r in enumerate(rows):
            (c0, c1), (d0, d1) = core(r), core(b)
            if min(c1, d1) - max(c0, d0) > 0.3 * min(c1 - c0, d1 - d0) and max(r[0], b[0]) - min(r[2], b[2]) < 1.5 * mh \
                    and not crosses(r, b):
                r[:] = [min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3])]; ncomp[t] += 1; break
        else:
            rows.append(b); ncomp.append(1)
    k = 0
    for r, nc in zip(rows, ncomp):
        dens = rest[r[1]:r[3], r[0]:r[2]].mean() if r[3] > r[1] and r[2] > r[0] else 0
        if nc >= 2 and dens >= 0.04 and r[2] - r[0] >= 2 * mh and r[0] > 0.01 * W and r[2] < 0.99 * W and r[1] > 0.01 * H and r[3] < 0.99 * H:
            lines.append({"id": f"a:{k}", "box": r, "src": "added", "from": [], "poly": None, "baseline": None,
                          "region": None}); k += 1
    # 4b. fold boxes lying mostly (70%+) inside a bigger box into it, then join again (rows split between old and added pieces)
    def area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    lines.sort(key=lambda l: -area(l["box"]))
    kept = []
    for l in lines:
        for big in kept:
            b, c = l["box"], big["box"]
            inter = area([max(b[0], c[0]), max(b[1], c[1]), min(b[2], c[2]), min(b[3], c[3])])
            if area(b) and inter >= 0.7 * area(b):
                big["from"] = big["from"] + l["from"]
                if big["src"] in ("blla", "legacy", "added") and l["from"]:
                    big["src"], big["id"] = ("joined", None) if big["src"] != "added" else ("added", big["id"])
                break
        else:
            kept.append(l)
    lines = join_all(kept)
    if RESPLIT:
        lines = split_tall(lines, RESPLIT_H, only={"joined", "added"})
    # 5. overrides
    po = ov.get(page["page_key"], {})
    lines = [l for l in lines if (l["id"] or "") not in set(po.get("drop", []))
             and not set(l["from"]) & set(po.get("drop_from", []))]
    f = max(W, H) / OVERLAY_FRAME if max(W, H) > OVERLAY_FRAME else 1.0  # overlays are only ever downscaled
    adds = list(po.get("add", [])) + [[round(v * f) for v in b] for b in po.get("add_ov", [])]
    for t, b in enumerate(adds):
        b = [max(0, b[0]), max(0, b[1]), min(W, b[2]), min(H, b[3])]
        # a manual box replaces the boxes it mostly covers
        lines = [l for l in lines if not (l["box"][0] >= b[0] - 0.3 * mh and l["box"][2] <= b[2] + 0.3 * mh
                                          and l["box"][1] >= b[1] - 0.5 * mh and l["box"][3] <= b[3] + 0.5 * mh)]
        lines.append({"id": f"m:{t}", "box": tight(b, ink) or b, "src": "manual", "from": [], "poly": None,
                      "baseline": None, "region": None})
    # tighten, finalise ids
    for l in lines:
        tb = tight(l["box"], ink)
        if tb:
            l["box"] = tb
        if l["id"] is None:
            l["id"] = "j:" + "+".join(l["from"])
    # 6. order: columns split at gutters, right column first; top to bottom inside
    cuts = sorted(((s + e) / 2 for s, e in gut), reverse=True)
    def col(b):
        cx = (b[0] + b[2]) / 2
        return sum(cx < c for c in cuts)
    lines.sort(key=lambda l: (col(l["box"]), (l["box"][1] + l["box"][3]) / 2))
    res = []
    for i, l in enumerate(lines):
        res.append({"i": i, "id": l["id"], "prefill": "", "box": l["box"],
                    "box_status": "segmented" if l["src"] in ("blla", "joined", "split") else
                    ("segmented_legacy" if l["src"] == "legacy" else l["src"]),
                    "box_source": l["src"], "merged_from": l["from"] if l["src"] == "joined" else None,
                    "v1_ids": l["from"], "polygon": l["poly"] or rect(l["box"]), "baseline": l["baseline"],
                    "region": l["region"], "match": None, "tier_a": None, "bidi_risk": None})
    return res, dropped, suspect, {"median_line_h": mh, "gutters": gut, "page_colour_ink": round(float(page_colour), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sets", nargs="*", default=["h_eval_v1", "h_eval_v1_1"])
    ap.add_argument("--pages", nargs="*")
    ap.add_argument("--overrides", default="data/eval/h_line_items_v2_overrides.json")
    ap.add_argument("--v11-rules", action="store_true",
                    help="v1.1 run on: join height cap (JOIN_MAX_GROW) and re-split of tall joined/added lines")
    a = ap.parse_args()
    v1p = ROOT / "data/eval/h_line_items_v1.json"
    v1 = json.loads(v1p.read_text(encoding="utf-8"))
    ovp = ROOT / a.overrides
    global RESPLIT, JOIN_CAP
    RESPLIT = JOIN_CAP = a.v11_rules
    ov = json.loads(ovp.read_text(encoding="utf-8")) if ovp.exists() else {"pages": {}}
    pages, stats = [], Counter()
    for p in v1["pages"]:
        if p["eval_set"] not in a.sets or (a.pages and p["page_key"] not in a.pages):
            continue
        assert sha(ROOT / p["image"]) == p["image_sha256"], p["page_key"]
        if ov["pages"].get(p["page_key"], {}).get("keep_v1"):
            # the agent check found v2's repairs worse than v1 on this page: keep v1's boxes unchanged
            lines = [dict(l, id=f"v1:{l['i']}", box_source="legacy" if l["box_status"] == "segmented_legacy" else "blla",
                          merged_from=None, v1_ids=[f"v1:{l['i']}"]) for l in p["lines"] if l["box"]]
            dropped, suspect, info = [], [], {"keep_v1": True}
        else:
            lines, dropped, suspect, info = process(p, ov["pages"])
        q = {k: v for k, v in p.items() if k != "lines"}
        q.update(lines=lines, dropped=dropped, suspect=suspect, rebox=info)
        fl = ov["pages"].get(p["page_key"], {}).get("flag")
        if fl and not q.get("page_flag"):
            q["page_flag"] = fl
        pages.append(q)
        c = Counter(l["box_source"] for l in lines)
        stats.update(c); stats["dropped"] += len(dropped); stats["v1_lines"] += len(p["lines"])
        print(p["page_key"], len(p["lines"]), "->", len(lines), dict(c), "dropped", len(dropped), "suspect", len(suspect), flush=True)
    assert all(l["prefill"] == "" for p in pages for l in p["lines"])
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "scripts/rebox_h_eval.py",
                            a.overrides], capture_output=True, text=True).stdout.strip()
    res = {"schema": "h_line_items.v2", "shape_of": "heocr-restricted-eval midcentury_line_items.v1",
           "from": {"file": "data/eval/h_line_items_v1.json", "sha256": sha(v1p)}, "sets": a.sets,
           "rule": __doc__.strip().splitlines()[0], "recognition": "none",
           "params": {"v11_rules": a.v11_rules, "join_max_grow": JOIN_MAX_GROW if a.v11_rules else None,
                      "resplit_h": RESPLIT_H if a.v11_rules else None, "split_h": SPLIT_H, "join_overlap": JOIN_OVERLAP, "join_gap": JOIN_GAP, "max_aspect": MAX_ASPECT,
                      "empty_ink": EMPTY_INK, "stamp_frac": STAMP_FRAC, "opencv": cv2.__version__},
           "overrides": a.overrides, "overrides_sha256": sha(ovp) if ovp.exists() else None, "hash_commit": head,
           "script": "scripts/rebox_h_eval.py", "script_dirty": bool(dirty),
           "pages_total": len(pages), "lines_total": sum(len(p["lines"]) for p in pages), "stats": dict(stats),
           "pages": pages, "signed": "data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource"}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("pages_total", "lines_total", "stats", "script_dirty")}))


if __name__ == "__main__":
    main()
