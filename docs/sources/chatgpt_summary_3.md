# ChatGPT Research Survey 3 — Prioritised Commercial-Use Hebrew Manuscript Sources

*Ingested 2026-05-24. Prompt: best reusable/commercial-safe sources for Hebrew manuscript scans,
with explicit licence verification.*

---

## Key finding

Most useful bulk sources are OPenn sub-collections (CC0 or CC BY 4.0) and the Library of Congress
(public domain).  Modern handwriting datasets (HHD) are non-commercial; the one exception is the
HuggingFace sivan22 character-level dataset (CC BY 3.0 — needs policy decision).

---

## Recommended sources (commercial-safe)

### Bulk / highest-volume first

| Source | Approx. size | Licence | OPenn/direct URL |
|--------|-------------|---------|-----------------|
| **OPenn — British Library Hebrew MSS** | ~1,300 MSS / ~435,000 images | CC0 1.0 (OPenn platform) | `openn.library.upenn.edu/html/0032_contents.html` |
| **Library of Congress — Hebraic Manuscripts** | ~230 MSS (Heb, Judeo-Arabic, Judeo-Persian, Yiddish) | PD / no known copyright restrictions | `loc.gov/collections/hebraic-manuscripts/about-this-collection/` |
| **OPenn — Cairo Genizah project** | Large (Bible fragments, Judeo-Arabic, ketubot, letters, legal docs, prayers) | PD / no known copyright restrictions | `openn.library.upenn.edu/html/genizah_contents.html` |
| **Leipzig University Library — Hebrew MSS** | 68 complete book MSS, 2 scrolls, fragments | Public Domain | `ub.uni-leipzig.de/en/research-library/digital-collections/hebrew-manuscripts` |
| **OPenn — University of Pennsylvania / Katz Center** | Penn Judaica holdings | PD / no known copyright restrictions | `openn.library.upenn.edu/html/0002.html` |
| **OPenn — Collection of Judaica (index)** | All OPenn Judaica repos incl. Gaster Hebrew MSS | Mixed: PD / CC0 / CC BY 4.0 / CC BY-SA 2.0 per repo | `openn.library.upenn.edu/html/judaica_contents.html` |
| **OPenn — University of Manchester Hebrew MSS** | Manchester / John Rylands Hebrew MSS | **CC BY 4.0 via OPenn** *(see caveat below)* | `openn.library.upenn.edu/html/0021.html` |
| **OPenn — Zucker Family Ketubah Collection** | 249 ketubot, 17th–20th c., many regions/scripts | PD / no known copyright restrictions | `openn.library.upenn.edu/html/0051.html` |
| **Wikimedia Commons — Category:Hebrew-language manuscripts** | ~105 direct files + 17 subcategories | Mixed PD / CC / CC BY-SA per file | `commons.wikimedia.org/wiki/Category:Hebrew-language_manuscripts` |
| **Wikimedia Commons — Category:Hebrew calligraphy** | ~74 files + subcategories | Mixed per file | `commons.wikimedia.org/wiki/Category:Hebrew_calligraphy` |
| **NYPL — Hebrew Illuminated Manuscripts** | **1,174 results** (PD-filtered subset) | PD items only | `digitalcollections.nypl.org/collections/hebrew-illuminated-manuscripts` |
| **MDZ / BSB — Hebrew Manuscripts** | **~700 pieces incl. 183 fragments** (12th–18th c.) | PDM items only | `digitale-sammlungen.de/en/hebrew-manuscripts` |
| **Internet Archive — PD Hebrew MSS** | Varies | PDM 1.0 (verify per upload) | `archive.org/` |

### Modern character-level handwriting

| Source | Size | Licence | Notes |
|--------|------|---------|-------|
| **HuggingFace — sivan22/hebrew-handwritten-dataset** | 5,093 rows, 28 classes | **CC BY 3.0** | Characters only, not pages. Needs policy decision — AGENTS.md lists CC-BY-4.0 but not explicitly CC-BY-3.0. |
| **TC-11 HHD_v0** | Isolated characters | CC BY-ND 3.0 | **Rejected per project policy** — CC-BY-ND is on the AGENTS.md reject list. |

---

## Manchester caveat (important)

Manchester's **own** digital collections viewer (`digitalcollections.manchester.ac.uk`) typically
shows CC BY-NC terms.  The OPenn-hosted copy (`openn.library.upenn.edu/html/0021.html`) carries
**CC BY 4.0** — use only the OPenn path.  Do not use Manchester's viewer as a rights source for
this project.

---

## Sources to avoid / use with caution

| Source | Reason |
|--------|--------|
| **BnF / Gallica** | Non-commercial restriction on commercial reuse |
| **Digital Bodleian** | NC restriction |
| **Vatican DigiVatLib** | Commercial use forbidden |
| **Manchester direct (own viewer)** | CC BY-NC — use OPenn copy instead |
| **HHD_gender / HHD_age** | Non-commercial research only / CC BY-NC-SA |
| **HebHTR (GitHub)** | No clear permissive data licence |
| **Ktiv / NLI directly** | Item-specific rights; some allow any use, others require approval — check each item page |

---

## Recommended ingestion priority order

From the survey, the recommended batch sequence for maximum usable volume:

1. **OPenn BL** (~435K images, CC0, bulk rsync)
2. **LoC** (~230 MSS, PD, JSON API)
3. **OPenn Cairo Genizah** (large, CC0)
4. **Leipzig** (~68 MSS, PD, manageable manual batch)
5. **OPenn Judaica** (Penn/Katz + index → discover Gaster MSS etc.)
6. **OPenn Manchester** (CC BY 4.0 via OPenn only)
7. **OPenn Zucker** (249 ketubot, CC0)
8. **Commons** (per-file, category exploration)
9. **NYPL** (PD-filtered subset of 1,174 results)
10. **MDZ** (PDM-only items from ~700 pieces)
11. **Internet Archive** (PDM mirrors, gap-fill only)
12. **HuggingFace sivan22** (CC BY 3.0, character-level, policy decision needed)

---

## Updates applied to sources.jsonl from this survey

- `openn__bl_hebrew_manuscripts`: added landing URL, scale (435K images), Polonsky Foundation link
- `openn__cairo_genizah_fragments`: added specific contents URL
- `openn__manchester_hebrew_manuscripts`: added specific URL, added Manchester NC vs OPenn CC BY 4.0 caveat
- `openn__katz_center_judaica`: added specific URL
- `openn__zucker_ketubah_collection`: added specific URL, confirmed 249 ketubot
- `leipzig__hebrew_manuscripts`: updated URL to direct Leipzig page
- `nypl__hebrew_manuscripts_digital_collections`: added 1,174 count to notes
- `mdz__hebrew_manuscripts`: added specific URL, scale (~700 pieces incl. 183 fragments)
- `archive__hebrew_manuscripts`: added named high-value items to notes
- `huggingface__sivan22_hebrew_handwritten`: added CC BY 3.0 licence, 5,093 / 28-class details, policy note
- **New**: `commons__hebrew_language_manuscripts` (17 subcats + 105 files)
- **New**: `commons__hebrew_calligraphy` (74 files + subcats)
- **New**: `openn__judaica_collection_index` (umbrella discovery page)
