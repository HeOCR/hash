# AGENTS.md

Operational rules for agents and humans contributing scans, sources, or tooling
to this repository. If anything below conflicts with `docs/dataset_structure.md`
or `LICENSE.md`, those documents win — this file is a working summary, not a
re-derivation of policy.

## What this repo is

A small, agent-friendly dataset of public-domain (or permissively licensed)
scans of handwritten Hebrew documents, paired with per-scan rights evidence.
Canonical layout, schema motivation, and ingestion model live in
[`docs/dataset_structure.md`](docs/dataset_structure.md). Compound licensing
(CC0 metadata, per-scan rights) is described in [`LICENSE.md`](LICENSE.md).
The machine-readable contracts are
[`schemas/source.schema.json`](schemas/source.schema.json) and
[`schemas/entry.schema.json`](schemas/entry.schema.json).

## Mandatory pre-PR commands

Run these from the repo root before opening or updating a PR. The first two are
also run in CI (`.github/workflows/ci.yml`) on every push to `main` and every
PR — they must stay green.

```bash
python3 scripts/validate_indexes.py
python3 -m pytest
git diff --check
```

`validate_indexes.py` must end with `ok: N sources, M entries`. `pytest` must
report all tests passing. `git diff --check` must produce no output.

## GitHub workflow

- One PR per coherent change. No batching unrelated work.
- Open PRs non-draft.
- Apply exactly one of these labels:
  - `enhancement` — content additions (new sources, scans, tooling) and
    feature work.
  - `documentation` — docs-only changes.
  - `bug` — fixes for incorrect data, schema, or tooling behavior.
- No milestones are configured; do not invent one.
- PR bodies should be detailed: what changed, why, validation evidence (paste
  the validator output and pytest summary), and any caveats. PR #3 and PR #4
  are the established tone reference.
- Use the `git` and `gh` CLIs. Do not push to `main` directly; always go
  through a PR.
- Standard commit hygiene: conventional `type(scope): subject`, real
  `Co-Authored-By` trailer when collaborating, no `--no-verify`, no force-push
  to `main`.

## Ingest rules

### In scope

- Hand-WRITTEN Hebrew-script content. Not printed, not typeset.
- Allowed `document_type` values: `letter`, `diary`, `notebook`, `draft`,
  `speech`, `receipt`, `form`, `marginalia`, `postcard`, `poem`, `other`.
- Post-1929 work is preferred but not required, as long as the rights
  situation is clean.

### Out of scope

- Printed or typeset pages, even if Hebrew.
- Signature-only crops.
- Vector teaching samples and synthetic font specimens.
- Non-Hebrew documents (or pages with no meaningful Hebrew handwriting).
- Anything still in copyright. Israel uses life + 70: the author must have
  died on or before December 31 of `(current_year − 71)`. If you can't
  establish that, reject.

### Rights evidence (primary-page rule)

Every entry's `rights.evidence_text` must quote the actual file page that
hosts the scan (e.g., the Wikimedia Commons file page). Collection-level or
landing-page claims are not enough — the evidence must be specific to the
file you ingested. `rights.verification_status` of `primary_page_checked`
means exactly that: a human or agent read that file page and copied the
license text into the record.

### Accepted licenses

- `PDM-1.0`
- `CC0-1.0`
- `CC-BY-4.0`
- `CC-BY-SA-4.0` (with the caveat below)
- Jurisdiction public-domain refs such as `LicenseRef-Public-Domain-Israel`,
  `LicenseRef-Public-Domain-Ukraine`.

### Rejected licenses

- `CC-BY-NC`, `CC-BY-NC-SA`, `CC-BY-ND`.
- "Research only", "permission required", "educational use only".
- Anything unknown, ambiguous, or sourced from a "rights unclear" landing.

### One scan = one entry

- Each physical page or scan unit is its own row in
  `data/index/entries.jsonl`.
- Multi-page items: one row in `data/index/sources.jsonl`, multiple entry
  rows named `<source_id>__p0001`, `<source_id>__p0002`, ....
- When you add a later page of an existing source, update the existing
  source row in place: extend `urls.related`, bump `scope.estimated_scan_count`,
  and append to `ingest.access_notes` and `ingest.agent_notes` rather than
  duplicating the source.

### Required per-scan metadata

For each `entries[].files[]` entry that has a `local_path`, populate:

- `sha256` — full file SHA-256 (lowercase hex).
- `bytes` — file size in bytes.
- `mime_type` — e.g., `image/jpeg`.
- `width_px` and `height_px` — pixel dimensions.

Helpers (macOS):

```bash
shasum -a 256 FILE
stat -f%z FILE
file --mime-type -b FILE
sips -g pixelWidth -g pixelHeight FILE
```

The validator now re-checks every file's existence, size, and SHA-256 against
the recorded metadata. Mismatches block CI.

### Transcription stub

Every new entry must include a transcription block with:

- `status: "none"`
- `text_path`, `alto_path`, `hocr_path`, `source_url`: `null`
- `created_by: "unknown"`
- `rights.verification_status: "unverified"` and all positive permission
  flags left `null`

Never claim transcript permissions you have not personally verified on the
transcript's own source page.

## Source naming

Source IDs use lowercase, double-underscore-separated tokens and must match
the regex enforced by `schemas/source.schema.json`
(`^[a-z0-9]+(?:__[a-z0-9_]+)+$`).

- Wikimedia Commons sources: `commons__<slug>` — for example,
  `commons__rachel_aqara_1928`.
- Use only ASCII lowercase letters, digits, and `_`. Separate logical tokens
  with `__`.
- The slug should be stable and recognizable; prefer the author or work name
  plus a disambiguator (year, page topic) over the Commons filename.

## Avoid NLI direct fetches

Do not pull files directly from the National Library of Israel — Cloudflare
has blocked prior automated attempts and the failure mode is silent. NLI
material that has already been mirrored to Wikimedia Commons is fine to
ingest from Commons, because the rights claim then lives on the Commons file
page (and that is what `evidence_text` must quote).

## Wikimedia download etiquette

When fetching from `upload.wikimedia.org`:

- Send a descriptive `User-Agent` header. This repo uses
  `public-domain-hand-written-hebrew-scans-ingest/1.0 (https://github.com/HeOCR/public-domain-hand-written-hebrew-scans)`.
- Space requests roughly 2 seconds apart. Aggressive batches get rate-limited.
- On HTTP 429, back off ~90 seconds and retry only the failed subset. Do not
  hammer.
- Always download the file actually referenced from the Commons file page,
  not a thumbnail or a Special:FilePath redirect captured at a previous size.

## CC-BY-SA caveat

`CC-BY-SA-4.0` is only acceptable when the licensor actually holds rights
over the underlying work. A modern photographer's CC-BY-SA grant on a
*photograph of someone else's still-in-copyright handwriting* does NOT make
the handwriting free — reject those entries. PR #3's body is the canonical
write-up of this policy. When in doubt, treat the underlying work and the
photographic reproduction as two separate rights questions and require both
to be clean.

## What NOT to commit

The following are already in `.gitignore` and should never appear in a diff:

- `.claude/` — local agent session state.
- `.DS_Store` — macOS Finder metadata.
- `__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd` — Python bytecode caches.

If `git status` shows any of these as untracked, leave them untracked. Do
not `git add -f` to override the ignore.
