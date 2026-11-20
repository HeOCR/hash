# H line items v2 for h_eval_v1_1 (`h_line_items_v2_v1_1.json`): 66 pages

This is the companion to `h_line_items_v2.json` (h_eval_v1, registered on its own: lead, 2026-11-20). Both files have
the same shape, fields and rules; see `H_LINE_ITEMS_V2.md`. Geometry only: no recognition, every `prefill` is "".
v1 and the registered h_eval_v1 file are unchanged.

## What differs from the h_eval_v1 run

**Run:** `scripts/rebox_h_eval.py --sets h_eval_v1_1 --v11-rules --overrides data/eval/h_line_items_v2_v1_1_overrides.json`.

**`--v11-rules`** turns on two rules that the v1.1 pages needed (many dense, faded and microfilmed spreads):
- **Join height cap:** a join may not make a line taller than 1.3 × its taller piece.
- **Re-split:** joined and added lines taller than 1.6 × the median line are split again, each part at least 0.6 of a
  line high.

Without the flag, the script reproduces the h_eval_v1 pages identically. This was checked after every change.

**Overrides:** a separate file, `h_line_items_v2_v1_1_overrides.json`, so the registered overrides file never changes.
It also has a new option, `drop_all`, which clears a page's automatic boxes so only manual ones remain.

## The agent check

**What was checked:** the 9 pages with the highest risk score (over-tall lines, many added or re-split boxes), viewed
as overlays and fixed by override. The other pages are measured by the sample below, not checked one by one.

**Fixes:**
- **`nli__ms_990000416060205171__p0004`:** an almost blank, stained spread. Only its 3 written lines are boxed; v1 had
  143 noise boxes.
- **`nli__ms_990000411340205171__p0003`:** a dark flyleaf spread. 8 manual boxes: the top lines, a name, and the
  shelfmark.
- **`nli__ms_990025900380205171__p0001`:** a shelfmark card. Split rows joined by hand.
- **`nli__ms_990000454790205171__p0002`** and **`nli__ms_990043786520205171__p0002`:** slivers and false boxes
  dropped.
- **`poor_boxes`, with v1 boxes kept:** `nli__ms_990043786520205171__p0004` (torn fragment) and
  `nli__ms_990000411340205171__p0004` (square script plus a decorated frame).
- **`poor_boxes`, spread set:** `nli__ms_990025880400205171__p0004` (faded microfilm spread with sprockets).
- **`nli__ms_990000752880205171__p0002`:** flagged **`no_handwriting`**. It is a microfilm resolution-test card with
  no handwriting. Only its printed lines are boxed.

**For eval to decide:** `nli__ms_990000752880205171__p0002`, and also `nli__ms_990000437530205171__p0003`
(other_hebrew_script; a blank spread with only a Latin shelfmark). Neither carries Hebrew handwriting. The 8
`no_hebrew_text` pages keep their flag and their boxes, as eval asked.

## Coverage check (agent)

**Sample:** 8 pages by `sha256("20261120:coverage-v2-v1_1:" + key)` order, 7 primary and 1 other, excluding
`no_hebrew_text` pages.
- Two pages are left out of the count: `nli__ms_990000411340205171__p0004` (keep_v1, poor) and
  `nli__ms_990000437530205171__p0003` (no Hebrew writing).
- The remaining 6 pages hold about 157 lines.

| | v1 (first coverage check) | v2, h_eval_v1_1 (6 pages, about 157 lines) |
|---|---|---|
| missed lines | ~6% | ~5.7% |
| split lines | ~15% | ~5.7% |
| merged boxes | ~3% | ~2.5% |
| false boxes | ~9% of boxes | ~3% of boxes |

**Where the errors are:** missed lines are mostly faded text on the facing page of microfilmed spreads
(`nli__ms_990025817680205171__p0004`). Merges and splits are mostly on a dense, slanted notebook page
(`nli__ms_990036744800205171__p0003`). The screen's fallback controls cover both.

**Totals:** v1 had 2,415 boxes on these pages, and v2 has 1,748 lines.
- 1,123 are blla lines kept as they were, and 34 are legacy lines.
- 395 are joined, 75 split, 102 added and 19 manual.
- 214 boxes were dropped, mostly by `drop_all` on the blank spread.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
