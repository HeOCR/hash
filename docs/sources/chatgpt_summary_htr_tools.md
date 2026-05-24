# HTR Tooling Survey — Layout Analysis and Line Segmentation for Hebrew Manuscripts

*Ingested 2026-05-24. Source: ChatGPT survey on open-source tools for historical Hebrew manuscript
layout analysis. Covers segmentation tools and pre-trained model projects relevant to the HASH
corpus.*

---

## Context

Standard layout analysis tools fail on historical Hebrew because they assume clean, LTR, printed
text.  Historical Hebrew involves RTL writing, complex multi-column layouts (e.g. Talmud + Rashi
commentary), marginalia, and heavily degraded parchment.  The tools below are the current
best-practice open-source options used by digital humanities researchers and computer vision
specialists for this material.

---

## 1. Kraken + eScriptorium (gold standard)

**Kraken** is an open-source OCR/HTR engine optimised for historical documents and non-Latin
scripts.  **eScriptorium** is its web-based graphical interface.

- **RTL / BiDi native.**  Handles RTL and bidirectional text natively.
- **Baseline tracing.**  Does not draw rectangular bounding boxes; traces the exact curvature of
  handwritten baselines and generates polygon masks — essential for sloping or intersecting lines.
- **Output formats.**  Exports ALTO-XML and PAGE-XML, the standard formats for HTR training datasets.
- Kraken repo: <https://github.com/mittagessen/kraken>
- eScriptorium repo: <https://github.com/scripta-studio/escriptorium>
- Docker image available for self-hosted deployment.

### Pre-trained Hebrew models (plug-and-play into eScriptorium)

These projects have released open-source Kraken layout and text-recognition models trained
specifically on hundreds of thousands of Cairo Genizah fragments.  They provide a high-accuracy
first pass of baselines and bounding boxes without any training data collection:

| Project | Training corpus | Model type | Location |
|---------|----------------|------------|----------|
| **MiDRASH Project** | Cairo Genizah (large) | Baseline segmentation + HTR | <https://github.com/MiDRASH-Project> (see releases) |
| **Princeton Geniza Project — HTR4PGP** | Princeton Geniza Lab fragments | Baseline segmentation + HTR | <https://github.com/Princeton-CDH/geniza> (model registry) |

**Relevance to this corpus:** The HASH corpus already includes Cairo Genizah fragments from
Wikimedia Commons (Bodleian T-S items, Halper items) and has `openn__cairo_genizah` as a
candidate source.  These models apply directly to that material.

---

## 2. Eynollah (Qurator-SPK)

Command-line layout analysis tool using pixel-wise deep learning segmentation.

- **Pixel classification:** segments a page into up to 10 classes: background, text region, text
  line, header, image, separator, marginalia, table.
- **Best use case:** highly complex physical layouts — e.g. a central Talmudic text surrounded by
  dense wrapping Rashi commentary.  Eynollah is strong at detecting distinct structural zones
  before drilling down to individual lines.
- **Output:** fully structured PAGE-XML files with coordinates for every detected region and line.
- Repo: <https://github.com/qurator-spk/eynollah>

---

## 3. LayoutParser

Python library providing a unified API for deep learning document image analysis (Mask R-CNN,
Faster R-CNN, etc.).

- **Use case:** building an automated programmatic pipeline from scratch.  You annotate a few
  dozen complex Hebrew pages, train a custom LayoutParser model, and run inference across
  thousands of scans.
- Repo / docs: <https://layout-parser.github.io/>

---

## 4. dhSegment (and Doc-UFCN)

U-Net architecture for pixel-wise semantic segmentation.  Particularly robust against degraded,
stained, or bleed-through manuscripts.

- Instead of finding a "box," it classifies every single pixel as background, text line, or page
  boundary.  Output is a mask that is easily converted to bounding boxes or polygons.
- **Best use case:** the most damaged material in the corpus — heavily degraded Genizah fragments
  and oldest Wikimedia Commons material.
- dhSegment repo: <https://github.com/dhlab-epfl/dhSegment>
- Doc-UFCN paper/repo: <https://github.com/soduco/paper-ufcn-icdar21>

---

## 5. HTR-United catalog

A community catalog of published HTR training datasets and model registries.

- Useful as a discovery tool: catalogs datasets that may include relevant Hebrew training material
  not already tracked in this repo.
- URL: <https://htr-united.github.io/catalog.html>

---

## Recommended workflow for annotation production (from survey)

1. Set up **eScriptorium** via Docker.
2. Load raw CC0 manuscript images from OPenn or Wikimedia.
3. Apply the open-source **MiDRASH Geniza** baseline segmentation model to auto-trace lines.
4. Use the eScriptorium UI to manually correct AI mistakes.
5. Export corrected data as **PAGE-XML** to train a custom model.

This workflow is directly compatible with the HASH corpus:  the OPenn candidate sources and the
already-ingested Wikimedia Commons Genizah items are the right input material.

---

## Notes

- The HASH entry schema already defines `alto_path` and `hocr_path` transcription fields; the
  tools above are what would populate those paths in a future annotation phase.
- This survey covers tooling only, not data sources.  All data-source leads remain in the other
  `docs/sources/chatgpt_summary_*.md` and `gemini_summary_*.md` files.
