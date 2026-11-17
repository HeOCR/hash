# Handwriting (H) eval set v1: plan

Status: plan, approved by heocr-lead 2026-11-18 with the decisions in §7 (task from lead, Shay-approved 2026-11-18).
Nothing is selected, downloaded or transcribed by this PR.

**Goal.** Give decision 0017's H domain its first scored set: 50–100 rights-clean handwritten Hebrew pages from HASH,
spread over writers, periods, document types and hand styles, with no page, document or (where possible) writer that any
training input has seen. eval pre-registers the set before any transcription exists.

## 1. The pool today (HASH `main` at 6d4ca08)

- **Index:** 197 entries in 48 source units (a unit is one HASH `source_id`: one archival record, letter or manuscript).
- **Writers:** one writer dominates. Hannah Senesh has 143 pages in 5 units; 19 units (27 pages) have no named author;
  the other 18 named writers have 1–4 pages each.
- **Providers:** NLI 143, Wikimedia Commons 29, Library of Congress 24, OPenn 1.
- **Document types:** diary 132, letter 20, other 20, poem 18, draft 5, notebook 1, postcard 1.
- **Periods:** 1700s–1890s about 30 pages; 1900–1948 about 156 (mostly Senesh, 1930s–40s); after 1948 3; undated or earlier 4.
- **Rights:** `public_domain` 188 pages; `cc_by_sa` 9 pages in 8 Commons units (see §4).
- **Transcripts:** 5 pages carry a published transcription (Wikisource or Commons); 187 carry only HTR candidates (GPT-4o,
  Kraken, Transkribus, and a consolidation of these). HTR candidates are never references.

**What the caps leave.** With at most 3 pages per unit and 8 per writer, each unknown-author unit counted as its own hand,
and the training-exposed units removed (§3), the public-domain pool gives about 51 pages from 32 hands. Dropping the two
writers that training has seen (Bialik, Rachel) leaves about 48. So v1 ships at about 50 pages from
HASH as it is (lead 2026-11-18), with honest intervals; the intake round grows it toward 100 through dated amendments.

## 2. Plan

1. **v1 selection from the pool as it is now** (step 2's rules), handed to eval and pre-registered (steps 3–4).
2. **HASH intake round (data-collection), after v1.** Ingest more writers, so the set grows beyond Senesh-heavy material.
   - First from the 14 HASH sources already at `candidate` status, then new LoC, Commons and OPenn items.
   - Targets: at least 20 new hands, more letters, notebooks and records (not diaries), more pre-1900 and post-1948 pages.
   - The usual HASH rules apply: per-scan rights evidence, PD by term or a permissive licence, NLI-API Google-class scans
     excluded.
   - Each new source goes through the normal HASH ingest PR (validate_indexes, release artefacts, exports, tests).
   - **Growth by amendment only.** New hands enter as a dated amendment (v1.1, v1.2, …) with its own selector run, seed
     and pre-registration. v1's pages are never reshuffled or replaced, and v1 scores stay reportable on their own.
3. **Selection (data-collection, scripted, metadata only).**
   - The selector reads only the HASH index, never page images, and is seeded. It and its seed are committed before it
     runs.
   - **Whole units.** A unit's pages are either all eval or all non-eval (0017 rule 1); a unit is the bootstrap cluster.
     Eval takes up to 3 pages of a unit; the unit's other pages are held out too and never enter training.
   - **Caps:** at most 3 pages per unit; at most 8 pages, and at most 10% of the set, per writer.
   - **Balance:** fill per period (before 1800 / 1800–1899 / 1900–1948 / after 1948) and per document type as evenly as
     the pool allows, then by provider. Seeded order inside each cell.
   - **Gates:** `hebrew_extent` is `full_page`; the entry is not blank or a cover; `languages` includes `he` (Yiddish- or
     Aramaic-only pages go to a separate, unscored list).
   - **Size:** about 50 for v1, from what passes now; toward 100 through amendments.
4. **Exclusion and exposure (data-collection runs it, eval runs the official check).** See §3.
5. **Hand-off.** A batch manifest to eval (§5). eval pre-registers before any transcription: strata, measures, the rule
   that admits a reference, and the exposure rule.
6. **Transcription (later).** A new heocr-review volunteer queue, after the mid-century volunteer task is running (§6).

## 3. Exclusion and exposure

- **Already true.** No HASH page or unit is in the R7, R8b or R9 training lists (path check on
  `r7-tesseract-real/data/bynli/train.list`, `r8b-tesseract/data/train_main.list`, `r9-tesseract/data/train_b.list`).
- **Known handwriting training inputs:** `HeOCR/hletterscript` (48 letter crops) draws on three HASH pages:
  `commons__bialik_el_hazippor__p0001`, `commons__bialik_letter_safed_1927__p0003` (no longer in the HASH index) and
  `commons__rachel_aqara_1928__p0001`. Those units are out. Their writers, Bialik and Rachel Bluwstein, are **seen writers**.
- **Sweep before selection.** Re-check every training input that could hold handwriting:
  - R-series lists;
  - hocrsyngen and s16/s17 glyph manifests;
  - hletterscript and hletterscriptgen;
  - HASH transcripts used anywhere as training text.
- **Writers.** The writers list goes into the manifest. Seen writers form a separate `seen_writer` stratum, reported
  apart (lead 2026-11-18). They are never in the primary score, which uses only unseen writers.
- **Text exposure.** Once references exist, eval's `check_train_overlap.py` runs on every compared model's list. Pages
  are then scored zero-exposure first, as with mid-century (word 6-gram, no threshold).
- **Hold-out record.** The selected units go into a HASH hold-out file (`data/index/eval_holdout.jsonl`, added with the
  selection PR). hletterscriptgen, synth-gen and every list builder must refuse units in it.
- **Famous texts.** Some pages have widely published texts, for example Imber's Hatikvah or a Bialik poem. LLM readers
  may know them by heart. These pages are tagged `known_text` and reported as a stratum, not dropped.

## 4. Rights and personal data

- **In without a flag:** pages that are plainly public-domain archival material. That is a holding institution (NLI,
  LoC, a university library via OPenn) or Commons with a PD-by-term basis, and an author dead more than 70 years or a
  pre-1900 document. Shay's 2026-11-06 ruling applies: such pages need no per-page privacy review.
- **Out of v1: the 8 Commons `cc_by_sa` units (9 pages), 1933–1990** (lead 2026-11-18). They are licensed, not PD by
  term; they are modern rabbinic letters and rulings, and some name recipients who may still be living. Taking them in
  later is a privacy question for Shay, through lead.
- **Flagged to lead before they enter the set:**
  - **Any page from after 1948, or by a writer who died less than 70 years ago,** whatever the licence.
  - **Any page whose main content is about a private person:** a medical or legal record, or a personal record of
    someone other than the writer.
  - The flag goes to lead with the unit ID, rights basis and reason. The page stays out until lead says yes.
- **Licence of the set.** Reference text CC0, as for review-app contributions. Images keep each scan's own rights (all
  `public_domain` in v1). The manifest carries each scan's attribution line.

## 5. Batch manifest for eval (HASH/hocrgen style)

One JSONL row per page, plus a `manifest.json` with the selector commit, seed, the HASH commit, and counts per stratum.
Each row has:

- **IDs:** `entry_id`, `source_id` (the unit), `sequence`.
- **Image:** `image_path`, `image_sha256`, `width_px`, `height_px`, and the original `source_url`.
- **Provenance:** `provider`, `holding_institution`, `holding_shelfmark`, `source_record_id`, `accessed_at`.
- **Rights:** `rights_basis`, `license_expression`, `evidence_text`, `terms_url`, `verification_status`, `attribution`.
- **Writer and period:** `writer_id` or `unknown:<source_id>`, `writer_death_year`, `seen_writer` (bool), `created`,
  `period`.
- **Content:** `document_type`, `languages`, `known_text` (bool).
- **Hand style:** `hand_style` is left empty. HASH has no field for it, and filling it means looking at the page. Eval or
  the reviewers fill it during transcription (square / cursive / semi-cursive (rabbinic) / mixed), and it is reported as
  a post-hoc stratum.
- **Flags:** `rights_flag` and `privacy_flag`, each null or a reason; only rows with both null are in the set.

## 6. Transcription and pre-fill (approved by lead 2026-11-18; eval registers it)

There is no reference yet, so the queue needs a starting text or none. Options:

| Option | Speed for the volunteer | Bias |
|---|---|---|
| A. Type from scratch | slowest | none |
| B. Stock Tesseract or our R-series lines as a draft | about the same as A: these readers are trained on print, and their handwriting output is mostly noise | small, but it anchors toward the readers we score |
| C. HASH's existing HTR consolidation (GPT-4o + Kraken + Transkribus) as a draft | fastest | anchors toward those engines; they can't then be scored fairly against it |

**Approved:**

- **A for a calibration subset.** At least 20% of pages, drawn by seed and spread over every stratum, are typed from
  scratch.
- **C for the rest.** Volunteers see the HTR draft marked as a machine draft.
- **Measure the anchoring.** On the calibration pages, eval compares the from-scratch reference with what the
  draft-based flow would have produced (a second volunteer on the same page with the draft). That gives the draft's
  pull, and it is reported with every H score.
- **Engines in the draft** (GPT-4o, Kraken, Transkribus) are scored only on the calibration subset. Elsewhere they carry
  an "anchored" label.
- **Not B.** It costs the same as A and adds bias toward the models we care about most.
- **Draft engines' terms on the card.** The set's card records, for each engine whose output fed the drafts (GPT-4o,
  Kraken, Transkribus), its terms of use and the version or date of the run. It also states that the references are
  human-made: the drafts are only a starting point, and every reference line is typed or corrected by a person.
- **eval's pre-registration fixes the details** (subset seed, measures, the rule that admits a reference).

## 7. Decisions (lead, 2026-11-18)

1. **The 8 `cc_by_sa` units are out of v1.** Excluding them is the safe default; taking them in later goes to Shay as a
   privacy question.
2. **Seen writers (Bialik, Rachel Bluwstein) form a separate `seen_writer` stratum,** reported apart and never in the
   primary score.
3. **v1 ships at about 50 pages** from what passes now, with honest intervals, and grows to 100 by dated amendments as
   the intake adds hands, never by reshuffling v1.
4. **Pre-fill as in §6,** for eval to register; draft engines' terms recorded on the card.
5. **Flags keep going to lead:** pages after 1948, writers dead less than 70 years, pages mainly about a private person.

## Not in this PR

- No selector code, no hold-out file, no manifest, no images; no intake.
- No review-app queue.
- No message to volunteers.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
