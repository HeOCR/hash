# Public Domain Hand-Written Hebrew Scans

This repository is intended to be a simple, agent-friendly dataset of scanned
handwritten Hebrew notes, letters, notebook pages, drafts, forms, and similar
documents from the modern Hebrew handwriting period.

The target corpus is limited to scans that can be redistributed and transformed
for downstream uses, including substantial remixing and machine-learning
datasets. The index therefore keeps rights evidence at both source and scan
level instead of assuming that a collection-level label applies to every page.

## Dataset Layout

- `docs/sources/` contains raw research notes and source leads.
- `docs/dataset_structure.md` defines the repository layout and ingestion model.
- `data/index/sources.jsonl` is the source-level catalog, one JSON object per
  institution, collection, item, dataset, or source lead.
- `data/index/entries.jsonl` is the scan-level catalog, one JSON object
  per individual page, note, letter, or other scanned unit.
- `schemas/source.schema.json` and `schemas/entry.schema.json` define the
  machine-readable record contracts.
- `scripts/validate_indexes.py` validates JSONL records against the schemas and
  checks source/entry referential integrity.
- `LICENSE.md` documents the compound licensing policy for metadata and scans.

## Serialization Decision

The canonical editable indexes are newline-delimited JSON (`.jsonl`).

JSONL is deliberately used instead of CSV because these records need nested
rights evidence, multiple URLs, per-field provenance, quality measurements,
and acquisition state. CSV or TSV exports can be generated later for browsing;
Parquet or SQLite exports can be generated later for analytics; the source of
truth stays line-oriented, diffable, streamable JSON.

Run the current validation check with:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_indexes.py
python3 -m pytest
```

## Current Status

The repository currently contains one verified seed scan plus candidate source
leads. Before any additional scan is added to `data/index/entries.jsonl`, an
ingest agent must verify:

1. the scan is actually handwritten Hebrew or materially Hebrew-script,
2. the document date is in scope,
3. the author/date/license combination allows redistribution and derivatives,
4. the file was downloaded from a stable source URL,
5. the local scan file has a stable checksum and recorded provenance.
