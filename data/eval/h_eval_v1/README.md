# h_eval_v1: handwriting (H) eval set, selection

Selected by `scripts/select_h_eval.py` (commit fc0f32b, committed before it ran), seed 20261118, target 50, from the
HASH index only (no page image was opened). Plan and decisions: `docs/h_eval_set_plan.md`.

| File | What |
|---|---|
| `manifest.jsonl` | one row per selected page: image path and sha256, source, rights, writer, period, strata |
| `manifest.json` | selector commit, seed, HASH commit, caps, counts per stratum, manifest sha256 |
| `flags.jsonl` | units kept out pending a decision by heocr-lead (v1: the 8 `cc_by_sa` units, out) |
| `unscored.jsonl` | pages or units that failed a gate, with the reason |
| `exposure_sweep.json` | where held-out pages appear outside HASH; 0 training hits |

The hold-out list is `data/index/eval_holdout.jsonl`: every page of every selected unit. Per contamination v2 amendment 1 (restricted-eval #1651, owner rule 2026-11-26), only the **scored** pages are protected: rows with
`selected: true` (`train_policy: excluded_scored`; 113 across v1 and v1.1). Their own pixels, in any capture of the same
physical page or any crop, never enter a training list. The other pages of these units (`selected: false`) are
`train_allowed_tagged`: they may be used for training with the tag `train_tag: in_hash_eval_holdout_unselected`. If such
a page is later drawn into a scored set, it becomes `excluded_scored` from then on. Same writer, same unit and same text
are tags, never exclusions.

- **Primary: 44 pages, 31 units, 31 hands, all unseen writers.** The pool ran out below 50. The 10% writer cap is 5 pages,
  so Senesh gives 5. The set grows to about 100 by dated amendments as the intake round adds hands.
- **seen_writer: 3 pages** (Rachel Bluwstein), reported apart and never in the primary score.
- **Earlier dev use (not training):** 3 primary pages and all 3 seen_writer pages were scored in the R3 real diagnostic
  with published-text references. 2 primary pages are hocrgen package fixtures. eval decides how to stratify them.
- **known_text:** 3 primary pages have a published transcription.
- **hand_style** is empty; eval or the reviewers fill it during transcription.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
