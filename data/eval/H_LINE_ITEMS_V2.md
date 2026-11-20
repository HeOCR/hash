# H line items v2 (`h_line_items_v2.json`): h_eval_v1's 47 pages

**What changed from v1:** v1's kraken boxes, repaired for line-by-line typing. Task from heocr-lead, 2026-11-20. Shay
types h_eval_v1 himself, so the boxes should cost him as little time as possible.
- **Unchanged:** v1 (`h_line_items_v1.json`).
- **Pages:** this file covers the `h_eval_v1` pages only (`sets`). h_eval_v1_1 follows in its own file, so a registered
  file never changes.
- **Geometry only:** no recognition model was run, and every `prefill` is "". eval registers this file before any
  typing.

## How

**Script:** `scripts/rebox_h_eval.py`, at the commit that built the file (`hash_commit` in the file; `script_dirty`
false). The rules are in its docstring. In short:
1. drop stamp and empty boxes;
2. split boxes taller than 1.8 × the page's median line;
3. join the pieces of a row. When both pieces have baselines, they must line up. A join never crosses a spread's
   binding and never exceeds contrib's 40:1 width-to-height limit;
4. add uncovered ink rows (ruling and grid lines removed first);
5. fold a box into a bigger one that holds it, and join again;
6. order the columns right to left, then top to bottom.

**Overrides:** `h_line_items_v2_overrides.json`, from data-collection's page-by-page check of all 47 v2 overlays
(`scripts/h_line_overlays_v2.py`, an agent check, not human review). They were committed before the final run, and
give for 17 pages:
- 15 false boxes dropped (blank grid squares, ruled lines, marbled borders and tape, a stamp, a flourish);
- 46 manual row boxes. Pelliot's damaged fragment is boxed row by row, and missed rows are added on Hatikvah,
  Mira Ben-Ari, Mardumsk, Rachel's "Gan naul" and others;
- spread settings;
- `keep_v1` on 3 pages where the repairs were worse than v1;
- `poor_boxes` on 6 pages: the Kafka spread (576 px), the Tsherniak postcard (strongly slanted), Hirsch pp. 1–2 (dense
  slanted script with marginal additions), and the two LoC amulet pages (magic squares, circular text). On those
  pages Shay's fallback controls carry the rest.

## Fields (contrib's importer reads `h_line_items.v2`)

v1's shape is kept, plus these fields:
- **per line:**
  - `id`: `v1:<i>` for a line taken unchanged from v1. New lines get `j:`, `s:`, `a:` or `m:` ids;
  - `box_source`: blla, legacy, joined, split, added or manual;
  - `merged_from` (joined lines);
  - `v1_ids`;
- **per page:**
  - `dropped`: removed boxes with a reason, for audit;
  - `suspect`: faint boxes, kept;
  - `rebox`: median line height, gutters;
  - `page_flag` may be `poor_boxes`.

`box` is the tight ink rectangle; contrib crops by it.

**Totals:** v1 had 1,861 boxes on these pages, and v2 has 1,285 lines.
- 954 are blla lines kept as they were, and 12 are legacy lines.
- 249 are joined, 4 split, 20 added and 46 manual.
- 20 boxes were dropped.

## Coverage check (agent, after the fix)

**Sample:** 8 pages by `sha256("20261120:coverage-v2:" + key)` order (7 primary, 1 other), counted on the final
overlays.

**Caveat:** the same agent had already checked every page during the fixing pass, so this measures the remaining
errors, not an independent audit.

| | v1 (first coverage check, 10 pages) | v2 (8 pages, about 304 lines) |
|---|---|---|
| missed lines | ~6% | ~2% |
| split lines | ~15% | ~8.5% (~4.6% without the flagged postcard) |
| merged boxes | ~3% | ~3% (6 of 9 on the postcard) |
| false boxes | ~9% of boxes | ~2% of boxes |

Most of what is left: slanted pages (overlapping rectangles) and hemistich columns in poems, where the two halves of a
row stay as separate boxes. The screen's "continued" and "not one line" controls cover both, and their counts come
back in contrib's export.

## Rules (unchanged)

These units are in `data/index/eval_holdout.jsonl`. No H page, box or crop enters any training list, and no machine
text may become, or seed, an H reference.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
