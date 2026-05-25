# Transcript Acquisition Status

_Last updated: 2026-05-25. Run by automated agent; items requiring human help are listed below._

## Summary

| Status   | Count | Notes                                    |
|----------|-------|------------------------------------------|
| full     | 6     | Complete plain-text transcript           |
| partial  | 1     | Fragment / first folio only              |
| none     | 191   | Not yet transcribed                      |
| **Total**| **198** |                                        |

## Completed transcripts (7 entries)

All files saved to `data/transcripts/`; `entries.jsonl` updated with `transcription` field.

| Entry ID                                    | Source                  | Rights       | Notes                                   |
|---------------------------------------------|-------------------------|--------------|-----------------------------------------|
| `commons__bialik_el_hazippor__p0001`        | Hebrew Wikisource       | PD-old-70    | Full poem with full niqqud (vocalization) |
| `commons__hatikvah_imber_manuscript__p0001` | Hebrew Wikisource       | PD-old-100   | Full 9-stanza original "Tikvatenu" (1886) |
| `commons__rachel_aqara_1928__p0001`         | Hebrew Wikisource       | PD-old-70    | Vocalized version only (stripped unvocalized header) |
| `commons__rachel_gan_naul__p0001`           | Hebrew Wikisource       | PD-old-70    | Full poem with niqqud                   |
| `commons__rachel_rak_al_atzmi__p0001`       | Hebrew Wikisource       | PD-old-70    | Full poem without niqqud (unvocalized)  |
| `commons__begani_netatikha__p0001`          | Hebrew Wikisource       | PD-old-70    | Full poem with niqqud                   |
| `commons__wosner_halachic_ruling_1981__p0001` | Wikimedia Commons description | CC-BY-SA-3.0 | PARTIAL — description text only, not full responsum |

## Items requiring human assistance

### 1. NLI Rosetta archive — 403 Forbidden (144 entries)

All Hannah Senesh materials from the National Library of Israel are served via the NLI Rosetta digital delivery system, which returns HTTP 403 for all programmatic requests without institutional credentials.

**Affected sources:**
- `nli__nnl_archive_al997009912248505171` — Handwritten diary and "Violin" draft (83 pages)
- `nli__nnl_archive_al997009912248705171` — Hebrew/Hungarian diary (43 pages)
- `nli__nnl_archive_al997009912248405171` — Hebrew poem notebook (10 pages)
- `nli__nnl_archive_al997009761278705171` — Pocket diary 1939 (6 pages)
- `nli__nnl_archive_al997009831775705171` — Handwritten speech draft (2 pages)

**All texts are Public Domain in Israel** (Hannah Senesh died 1944, PD from 2014).

**What's needed:**
- NLI institutional login (via the NLI Primo discovery portal or a direct arrangement with NLI) to access IIIF manifests and page images
- After getting image access: OCR or manual transcription per page
- For the poem notebook specifically: **cross-reference with the published collected poems** to identify which poem is on which page — the notebook contains 10 pages (pp. 3–12 of the notebook); known Senesh poems in Hebrew include "אשרי הגפרור" (Blessed is the Match), "הליכה לקיסריה" (Walk to Caesarea / "Eli Eli"), "הנה עץ רימון" and others.

---

### 2. Library of Congress handwritten manuscripts — no OCR available (16 entries)

All 16 LoC entries are handwritten Hebrew manuscripts. The LoC JSON API returns images but no OCR text. None of the items have `words`, `ocr`, or `alto` resources in their API responses.

**Affected sources (with LoC catalog notes):**
- `loc__2018757642` — "Hadashim li-Vekarim": Sephardic diwan, ~65 pizmonim with musical mode notation (Near East / Turkey, Oriental Sephardic script). **5 pages.**
- `loc__2018757719` — **3 pages** (title and content unknown without scan access)
- `loc__2018757724` — **1 page**
- `loc__2018757741` — **1 page**
- `loc__2018757746` — "Prayers for the midnight service": tikkun hatzot, piyyutim by Moses Zacuto; ff. 13r–14v: selihah for Ten Martyrs ("אלה אזכרה"). **4 pages.**
- `loc__2018757763` — **3 pages**
- `loc__2018757784` — **2 pages**
- `loc__2018757798` — "Mishbetset ha-Peninim" by Eliezer Lipman Naizatts: collection of poems and epigrams, many from "Mivhar ha-Peninim" (Vienna 1847, Warsaw 1854). **1 page.**
- `loc__2018757827` — **1 page**
- `loc__2018757834` — **2 pages**
- `loc__2018757836` — **2 pages**
- `loc__2023530824` — **2 pages**
- `loc__2023530854` — **2 pages**
- `loc__2023530855` — **1 page**
- `loc__2023530858` — **1 page**
- `loc__2018757701` — **1 page**

**What's needed:**
- Download page images from LoC IIIF tiles (publicly accessible): `https://tile.loc.gov/image-services/iiif/service:amed:amedscd:{LOC_ID}:{ZFILL_INDEX}/full/max/0/default.jpg`
- Run Hebrew HTR (Handwritten Text Recognition) e.g. using **Transkribus**, **eScriptorium**, or a custom model
- For "Mishbetset ha-Peninim" (loc__2018757798): the printed edition may be available via HebrewBooks.org for cross-reference

---

### 3. Wikimedia Commons — handwritten letters and documents (20 entries)

These are all handwritten primary-source documents uploaded to Wikimedia Commons. Commons file descriptions are metadata captions only (24–132 chars), not transcriptions. No programmatic source found.

**Affected entries:**
| Entry ID | Title (abbreviated) | Creator | Language |
|---|---|---|---|
| `commons__auerbach_letter_shtenzel_1961__p0001` | Auerbach on daily Mishnah study | R. S.Z. Auerbach | Hebrew |
| `commons__bendin_semichah_shtenzel_1933__p0001` | Będzin rabbinical ordination for R. Shtenzel | Będzin Beit Din | Hebrew |
| `commons__blazer_letter_grayevsky_1905__p0001` | Blazer letter to Grayevsky (May 1905) | Yitzchak Blazer | Hebrew |
| `commons__chaim_berlin_halachic_response_1894__p0001` | Halachic response (1894) | Chaim Berlin | Hebrew |
| `commons__chaim_berlin_letter_kollels_1890__p0001` | Letter to Committee of Kollels (1890) | Chaim Berlin | Hebrew |
| `commons__epstein_meltzer_letter_about_kook__p0001` | Joint letter supporting Rav Kook | Epstein & Meltzer | Hebrew |
| `commons__hirsch_torah_letter_1878__p0001` | Torah-thoughts letter, sheet I (1878) | S.R. Hirsch | Hebrew (German?) |
| `commons__hirsch_torah_letter_1878__p0002` | Torah-thoughts letter, sheet II (1878) | S.R. Hirsch | Hebrew (German?) |
| `commons__hirsch_torah_letter_1878__p0003` | Torah-thoughts letter, sheet III (1878) | S.R. Hirsch | Hebrew (German?) |
| `commons__kafka_hebrew_writings__p0001` | Kafka Hebrew exercise notebook | Franz Kafka | Hebrew |
| `commons__landsberg_letter_1859__p0001` | Letter to Sir Moses Montefiore (1859) | R. M. Landsberg | Hebrew |
| `commons__mardumsk_haskama_1931__p0001` | Radomsk Rebbe approbation (1931) | Radomsk Rebbe | Hebrew |
| `commons__mira_ben_ari_letter__p0001` | Handwritten Hebrew letter (pre-1948) | Mira Ben-Ari | Hebrew |
| `commons__rav_kook_letter_03__p0001` | Letter to High Commissioner H. Samuel (May 1923) | Rav A.I. Kook | Hebrew |
| `commons__tsherniak_postcard_1913__p0001` | Postcard to Rabbi Tsirelson (June 1913) | R. Tsherniak | Hebrew |
| `commons__weidenfeld_eruv_letter_1947__p0001` | Weidenfeld on eruv to R. Shtenzel (1947) | R.D.B. Weidenfeld | Hebrew |
| `commons__weidenfeld_letter_shtenzel_1959__p0001` | Weidenfeld on daily halacha study (1959) | R.D.B. Weidenfeld | Hebrew |
| `commons__wosner_letter_halakhah_yomit_1986__p0001` | Wosner on daily halacha study (1986) | R.S.H. Wosner | Hebrew |
| `commons__wosner_support_letter_1990__p0001` | Wosner support letter for Mishnah competition (1990) | R.S.H. Wosner | Hebrew |

**What's needed:** Manual transcription from the scan images (all publicly accessible on Wikimedia Commons — links in entries.jsonl).

**Possible lead for the Kook letter:** "Igrot HaRe'ayah" (published letters) on Hebrew Wikisource has some Kook letters, but the specific letter to Herbert Samuel (17 May 1923) was not found there. The NLI JPress historical press archive may have a published version.

---

### 4. Itzik Manger — still under copyright (2 entries)

`commons__manger_unter_di_khurves__p0001` and `__p0002` are pages of Manger's Yiddish manuscript "Unter di Khurves" (Among the Ruins). Manger died 1969; the text is copyrighted until ~2039 (Israel) or 2040 (EU). **Cannot be transcribed under an open license.**

The Yiddish manuscript images are CC-BY-SA-3.0 on Commons, but the poem text is not PD.

---

### 5. OPenn Zucker Ketubah — no body text in TEI-XML (1 entry)

`openn__zucker__ket_z_238__p0001` — The OPenn TEI-XML at
`https://openn.library.upenn.edu/Data/0051/ket_z_238/data/ket_z_238_TEI.xml`
has a detailed `teiHeader` (metadata) but the `<body>` element is empty (no transcription). The ketubah text is a standard Aramaic formulary customized with proper names.

**What's needed:** Manual transcription from the IIIF-accessible scan, or sourcing the standard Aramaic ketubah formulary and filling in the specific names/dates from the scan.

---

### 6. Pelliot Hébreu 1 — academic access required (1 entry)

`commons__pelliot_hebreu_1__p0001` — An 8th–9th century Selihah (penitential prayer) leaf from the Dunhuang Caves (China), now at BnF (Paris, Hébreu 1412). The BnF Gallica API returns 403. The IDP (International Dunhuang Project) at the British Library also returns 403.

**What's needed:** Access via the BnF researcher portal or the IDP database, both of which require institutional credentials or contact with the curating institution.

---

## Sources tried (programmatic)

| Source | Result |
|--------|--------|
| Hebrew Wikisource (`he.wikisource.org`) | ✅ 6 poems extracted |
| Yiddish Wikisource (`yi.wikisource.org`) | ❌ Manger poem not indexed |
| NLI IIIF / Rosetta | ❌ 403 Forbidden (all archive items) |
| Library of Congress JSON API | ❌ Images only, no OCR |
| BnF Gallica API | ❌ 403 Forbidden |
| IDP (International Dunhuang Project) | ❌ 403 Forbidden |
| Project Ben-Yehuda | ❌ No working API found |
| HebrewBooks.org | ❌ Endpoints 404 |
| Internet Archive | ⚠️ Published books found but not manuscript transcripts |
| Wikimedia Commons Structured Data | ❌ No transcription statements on any item |
| Europeana API | ❌ No matching items |
| Oxford Bodleian Digital Library | ❌ HTML only, no JSON API |

## Script

`scripts/fetch_transcripts.py` — contains the extraction logic for the 7 transcripts above and documents all failed attempts. Run with `python3 scripts/fetch_transcripts.py --dry-run` to preview; remove `--dry-run` to write.
