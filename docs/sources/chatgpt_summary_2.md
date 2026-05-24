# ChatGPT Research Survey 2 — Hebrew Handwriting Sources Table

*Ingested 2026-05-23. Prompt: broad table of Hebrew handwriting repositories with rights analysis.*

## Key findings

Large survey covering OPenn sub-collections, European national libraries, ML datasets, and aggregators.
Best leads are the OPenn institutional sub-collections (all CC0) and selected PD-only items at MDZ and
Internet Archive. ML-ready datasets (HHD_v0, HHD_gender) remain non-commercial or conflicting; avoid.

---

## Recommended sources

### OPenn sub-collections (CC0 1.0 Universal throughout)

OPenn is a bulk-download platform operated by the University of Pennsylvania Libraries.
All content is CC0. Bulk rsync/FTP access available.

| Sub-collection | Approx. count | Notes |
|---|---|---|
| British Library Hebrew MSS | ~1,300 MSS | BL digitized, hosted OPenn, separate from bl.uk (which restricts commercial) |
| Cairo Genizah fragments | large | Several Genizah-holding institutions contribute to OPenn; verify by collection |
| Curated Judaica (Katz Center etc.) | hundreds | Mixed handwriting; filter by `expected_handwriting` |
| Manchester / John Rylands Library Hebrew | dozens | CC BY 4.0 per JRL policy (not CC0 like most OPenn) — verify per item |
| Zucker Ketubah Collection | 249 | Marriage contracts, all PD |

### Leipzig University Library — Hebrew Manuscripts
- ~68 Hebrew MSS; digital images released under PDM/PD.
- URL: https://www.manuscripta-mediaevalia.de/ (search Leipzig Hebrew)

### MDZ / Bayerische Staatsbibliothek — Hebrew Manuscripts
- Large digitized Hebrew collection; PDM-marked items are safe.
- Restrict to PDM-flagged items; some items have licensing notes on the scan page.
- URL: https://www.digitale-sammlungen.de/

### Internet Archive — Hebrew Manuscripts (PDM mirrors)
- PDM-tagged uploads from various libraries. Quality and format vary.
- Useful as a discovery/overflow source when OPenn/LoC copies are unavailable.
- URL: https://archive.org/search?q=hebrew+manuscripts&and[]=mediatype%3A%22texts%22

### HuggingFace — sivan22/hebrew-handwritten-dataset
- 5,093 rows of isolated Hebrew character crops; CC BY 3.0.
- Useful as external HTR reference; not page-level scans.
- URL: https://huggingface.co/datasets/sivan22/hebrew-handwritten-dataset

### PICRYL — Hebrew Manuscripts (aggregator)
- Aggregates PD items from NYPL, LoC, Europeana, etc. with direct download links.
- Not a primary source; use as discovery/cross-reference tool only.
- URL: https://picryl.com/

---

## Sources to avoid

| Source | Reason |
|---|---|
| BnF / Gallica Hebrew MSS | Commercial use not permitted under Gallica terms |
| Bodleian Digital Library Hebrew | Non-commercial restriction on digital scans |
| Vatican DigiVatLib Hebrew | Commercial use explicitly forbidden |
| GitHub HebHTR | No clear permissive license on training data |
| HHD_gender (Zenodo) | Rights conflict with underlying dataset |

---

## Updates to existing records

- **LoC Hebrew Manuscripts**: more specific URL is `https://www.loc.gov/collections/hebraic-manuscripts/about-this-collection/`
- **NYPL Digital Collections**: Hebrew Illuminated Manuscripts sub-collection at `https://digitalcollections.nypl.org/collections/hebrew-illuminated-manuscripts` has ~1,174 items
