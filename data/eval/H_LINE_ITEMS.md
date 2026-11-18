# H line items v1 (`h_line_items_v1.json`)

Line boxes for every page of the registered H eval sets, h_eval_v1 and h_eval_v1_1: 113 pages (100 primary,
10 other_hebrew_script, 3 seen_writer). Volunteers use them to type each page line by line, from scratch (eval's
amendment 1: no text drafts). Task from heocr-lead, 2026-11-18. eval registers this file before any transcription;
contrib builds the typing task from it.

## How the boxes were made

- **Segmenter.** kraken 7.0.2's default baseline segmenter (`blla.mlmodel`, bundled with kraken).
  - Licences: kraken Apache-2.0, model Apache-2.0. The model's sha256 is in the file.
  - Text direction is `horizontal-rl`.
  - Reading order (`i`) is kraken's own.
- **No recognition.** No recognition model is loaded or run, so no machine text exists for any H page. Every `prefill`
  is `""`. The test checks this.
- **Fallback.** kraken's legacy box segmenter (`nlbin` + `pageseg.segment`, Apache-2.0) replaces blla on 5 pages. On
  those pages blla found no lines, or almost none, although text is plainly visible. They are listed in
  `h_line_items_overrides.json`, which was committed before the final run.
  - Legacy lines have a rectangle polygon, no baseline, and `box_status` `segmented_legacy`.
  - R4d, our own segtrain model, was not used. It was trained on printed pages, and its model file does not load in
    kraken 7.
- **Coordinates** are image pixels as displayed. One file (`commons__rachel_gan_naul__p0001`) carries EXIF orientation 8,
  which is applied first, as browsers do. The page records `exif_orientation`, and its `image_size` is the displayed
  size.
- **Shape.** The file follows eval's `midcentury_line_items.v1` (`page_key`, `image`, `image_sha256`, `image_size`,
  `prefill_source`, `prefill_from_stock`, `lines[i, prefill, box, box_status, match, tier_a, bidi_risk]`). It adds:
  - per line: `polygon`, `baseline`, `region`;
  - per page: `eval_set`, `stratum`, `source_id`, `segmenter`, `page_flag`.
- **Reproduce:** `python3 scripts/segment_h_eval.py --out data/eval/h_line_items_v1.json`. Draw boxes for checking with
  `python3 scripts/h_line_overlays.py data/eval/h_line_items_v1.json OUT_DIR ENTRY_ID ...`.

## Coverage check (agent visual check, not human review)

**Sample.** 10 pages, drawn before any box was seen: seed 20261118, `sha256("20261118:coverage:" + entry_id)` order
within each stratum, taking 7 primary, 2 other_hebrew_script and 1 seen_writer.

**Method.** data-collection looked at each page with the blla boxes drawn on it and counted, approximately, from
downscaled overlays:
- **text lines:** handwritten Hebrew lines, plus printed letterhead or caption lines and shelfmarks;
- **missed:** no box covers the line;
- **split:** a line covered by 2 or more boxes;
- **merged:** one box spans 2 or more lines;
- **false:** a box over no text, such as a stain, stamp or bleed-through.

The counts are estimates by an agent, not a human audit.

| page | stratum | text lines | boxes | missed | split | merged | false | verdict |
|---|---|---|---|---|---|---|---|---|
| nli__ms_990036625760205171__p0001 | primary | ~36 | 40 | ~2 | ~12 | ~2 | 0 | usable, fragmented |
| nli__ms_990025880400205171__p0002 | primary | ~58 | 102 | ~3 | ~15 | ~5 | ~30 (bleed-through on the facing leaf) | poor |
| loc__2018757763__p0004 | primary | ~44 | 44 | ~1 | ~4 | 0 | 1 | good |
| loc__2018757763__p0005 | primary | ~33 | 34 | 0 | 1 | 0 | 0 | good |
| nli__nnl_archive_al997009831775705171__p0001 | primary | ~29 | 30 | 1 (part of a line under a stain) | 0 | 1 | 1 | good |
| commons__epstein_meltzer_letter_about_kook__p0001 | primary | ~24 | 25 | 1 | 1 | 0 | 0 | good |
| nli__ms_990000404600205171__p0003 | primary | ~5 handwritten (the rest is a printed title page) | 12 | 0 | 0 | 0 | ~4 (stamp) | good for the handwriting |
| nli__ms_990000409040205171__p0002 | other_hebrew_script | ~26 | 41 | ~2 | ~12 | ~2 | 0 | usable, fragmented |
| nli__ms_990000409040205171__p0004 | other_hebrew_script | ~62 | 66 | ~1 | ~4 | ~1 | 0 | good |
| commons__begani_netatikha__p0001 | seen_writer | ~12 | 9 | ~10 | 0 | 0 | 0 | **failed: legacy fallback** |
| **total** | | **~329** | **403** | **~21 (6%)** | **~49 (15%)** | **~11 (3%)** | **~36 (9% of boxes)** | |

After the fallback, the seen_writer page has 12 legacy boxes for its ~12 lines; only the short date line in the margin
is partly covered. With that page counted from the legacy boxes, about 11 lines are missed, about 3%.

**What blla does.** It is good on clean, evenly written pages (LoC, the 1940s archive page, the letter). It fragments
dense, faded or microfilmed pages into several boxes per line, and it misses pages with large, sparse writing entirely
(the card, the poem). Reading order is right page before left page on spreads, as Hebrew needs. Inside a fragmented row,
the order of the pieces is not always right to left.

**For the typing task (contrib).** Volunteers need ways to:
- mark a box as "no text";
- join a split line (type the whole line in its first piece and mark the rest as "continued");
- report a missed line.
Then they need not type anything twice, and nothing is lost.

## Whole-set screen: pages with fewer than 3 lines

12 pages got fewer than 3 blla lines. data-collection looked at all 12 (an agent check):

- **4 have visible text, so legacy is used:**
  - `commons__hirsch_torah_letter_1878__p0003` (poor: signature flourishes);
  - `nli__ms_990025817680205171__p0002` (a card; legacy found its 3 lines);
  - `nli__ms_990036625760205171__p0002` (a faded full page);
  - `nli__ms_990032583600205171__p0001` (a torn fragment; poor with either engine).
- **8 show no Hebrew handwriting, and are flagged `no_hebrew_text` for eval:**
  - 6 primary: `nli__ms_990035325400205171__p0001`, `…__p0003` (blank ruled leaves; p0001 carries only a pencil
    number), `nli__ms_990036744800205171__p0002` (a flyleaf with a Latin-script shelf note and a stamp),
    `nli__ms_990047583270205171__p0002`, `…__p0003` (blank covers or endpapers), and
    `nli__ms_990025817680205171__p0003` (a near-blank microfilm frame);
  - 2 other_hebrew_script: `nli__ms_990000437530205171__p0002` (a patterned cover with a printed label) and `…__p0004`
    (a blank spread).
  - All 8 came in through data-collection's NLI intake; its ink-ratio gate (0.01) let them through. The manifests are
    unchanged. Whether these pages leave the scored set is eval's decision, through a dated amendment.

## Rules

- These units are in `data/index/eval_holdout.jsonl`. No H page, box or crop enters any training list.
- The boxes are geometry only. No text from any engine may become, or seed, an H reference.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
