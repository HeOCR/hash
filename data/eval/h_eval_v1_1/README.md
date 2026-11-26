# h_eval_v1_1: amendment 1.1 to the handwriting (H) eval set

Selected by `scripts/select_h_eval_v1_1.py` (commit 8902662, committed before it ran), seed 20261119, combined
target 100 primary pages, from the HASH index only (no page image was opened). v1 (`data/eval/h_eval_v1/`) is
unchanged; v1.1 only adds pages, from units outside every earlier hold-out.

- **Added primary: 56 pages, 19 units, 19 hands** (18 new writers plus Hannah Senesh, who reaches the 8-page cap).
  v1 + v1.1 primary: 100 pages, 49 hands. All from NLI: before 1800 15, 1800s 23, 1900–1948 12, undated 6;
  letters 18, other 26, poems 6, diaries 3, notebooks 3. 32 of the 56 pages are catalogued copies, whose scribe is
  unknown, so each such unit counts as its own hand.
- **other_hebrew_script: 10 pages.** Units that also record Yiddish, Judeo-Arabic, Ladino, Judeo-Persian, Persian or
  (NLI) German. Reported apart, never in the primary score (lead 2026-11-18). The NLI catalogue lists Hebrew first
  for all of them (`data/review/nli_ms_languages_041.json`), so it cannot tell the main language; the rule is
  conservative.
- **Hand rule (lead 2026-11-18):** role `writer` counts; `author` counts only outside `nli__ms_*` sources, where HASH's
  legacy entries are autographs; otherwise a unit is its own hand.
- **Hold-out:** 108 pages appended to `data/index/eval_holdout.jsonl` with `eval_set` `h_eval_v1_1`: 66 `selected: true` (scored, excluded from training) and 42 `selected: false` (train-allowed, tagged). This follows the owner rule in `../h_eval_v1/README.md`.
- **Exposure:** 0 training hits; one hocrgen package fixture holds a different page of a selected Senesh unit.
- **Flagged:** 12 units (the 8 cc_by_sa units, out as in v1; 4 undated NLI letters with no named person).

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
