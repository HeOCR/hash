# HTR draft engines: what produced `data/transcripts/candidates/`

This file records, for the h_eval_v1 card, the engines whose output is in HASH's HTR candidate files, their terms, and
the run that produced them. It is facts from the repository history and the scripts; nothing was re-run. The candidate
files are unchanged (eval pins them at c5bc0bd).

## The run

- **Commit:** 3cb163a, 2026-05-27, "Kraken + Consolidated HTR passes for all 187 untranscribed entries" (scripts added
  in cf1d4d4 the same day).
- **Kraken pass** (`scripts/kraken_transcribe.py`, writes `*.escriptorium.txt`): 185 of 187 entries gave text.
  - Segmentation model: DOI 10.5281/zenodo.14602568, "General segmentation model for print and handwriting" (Benjamin
    Kiessling), Apache-2.0. The DOI now resolves to record 22879549, published 2026-09-21, after the run, so the exact
    record version used in May is not known.
  - Recognition model: DOI 10.5281/zenodo.5468286, "Medieval Hebrew manuscripts version 1.0" (BiblIA_01, Daniel Stoekl
    Ben Ezra), published 2021-09-06, CC BY-SA 4.0. It is a medieval book-hand model; the commit notes it is "imperfect
    for 19th-20th c. cursive".
  - Engine: kraken, Apache-2.0. The run did not record its kraken version (the host has 7.0.2 today).
- **Transkribus: never run.** `transkribus_transcribe.py` needed credentials that were not set; no `*.transkribus.txt`
  file exists. Transkribus output is in no draft.
- **Consolidation** (`scripts/consolidate_transcripts.py`, writes `*.consolidated.txt`): OpenAI API, model alias
  `gpt-4o` (the dated snapshot behind the alias was not recorded), temperature 0, text only. Its input was the Kraken
  text alone, since the Transkribus input was missing. 5 of 187 entries gave substantive text; 182 are `[blank]`.
  - Terms: OpenAI's terms for API output (Services Agreement / Terms of Use, as in force in May 2026) assign the output
    to the customer, and restrict using output to develop models that compete with OpenAI.

## What this means for h_eval_v1 (47 pages)

| Draft state | Pages |
|---|---|
| `consolidated.txt` is `[blank]` | 36 |
| no candidate files at all (the 6 pages with a published transcription) | 6 |
| `consolidated.txt` has text | 5: `commons__kafka_hebrew_writings__p0001`, `commons__pelliot_hebreu_1__p0001`, `loc__2018757784__p0004`, `loc__2018757784__p0005`, `loc__2023530854__p0002` |

The Kraken files are fragments: a median of 648 Hebrew letters per page on the 41 pages that have one, with sub-word
noise.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
