# Gemini Research Summary 2 — Commercial-Use Hebrew Handwriting Sources

*Ingested 2026-05-23. Prompt: best repositories for redistribution-friendly handwritten Hebrew.*

## Key finding

Almost all pre-packaged, ML-ready Hebrew handwriting datasets (e.g. HHD) are licensed
"Non-Commercial Research Purpose Only." To build a commercially usable dataset, source
high-resolution scans directly from digital library archives under CC0, PD, or CC BY.

---

## Recommended sources

### 1. OPenn (University of Pennsylvania Libraries)

All content released under **CC0 1.0 Universal** (Public Domain Dedication).

- **Collection:** Katz Center for Advanced Judaic Studies — hundreds of digitized
  handwritten Hebrew manuscripts, codices, and historical documents.
- **Access:** Designed for bulk downloading. Pull entire directories of high-res
  TIFFs/JPEGs and XML metadata via **rsync or direct FTP**.
- URL: https://openn.library.upenn.edu/

### 2. Wikimedia Commons

Every file must be PD, CC0, CC BY, or CC BY-SA — always redistribution + commercial safe.

- **Collections:** `Category:Hebrew manuscripts`, `Category:Hebrew handwriting`.
  Thousands of individual pages, fragments, letters.
- **Access:** MediaWiki API or Wikimedia Toolforge for bulk category scraping.
- URL: https://commons.wikimedia.org/

### 3. New York Public Library (NYPL) Digital Collections

Out-of-copyright digital materials: completely free for any use including commercial,
no permission required.

- **Collections:** Hebrew Illuminated Manuscripts, historical Ketubbot (handwritten
  marriage contracts), early modern letters.
- **Access:** Filter "Search only public domain materials" on the portal; download
  high-res files directly or use the public API.
- URL: https://digitalcollections.nypl.org/

### 4. Library of Congress (LoC)

US government entity; items lacking known copyright restrictions are free for general use.

- **Collections:** "Hebrew Manuscripts" — handwritten texts, religious commentaries,
  drafts spanning centuries.
- **Access:** Robust JSON API; query Hebrew Manuscript collection and download
  JPEG/TIFF files programmatically.
- URL: https://www.loc.gov/collections/hebrew-manuscripts/

---

## Sources to avoid or check carefully

- **HHD (Hebrew Handwritten Dataset):** Strictly non-commercial.
- **British Library & Cambridge Digital Library:** Hold incredible Cairo Genizah /
  Hebrew manuscript collections but terms frequently restrict commercial reuse or
  require paid permissions.
- **Ktiv (National Library of Israel aggregator):** Aggregates from hundreds of
  libraries worldwide. The actual medieval texts are out of copyright, but holding
  institutions often place restrictive terms on their digital photographs.
