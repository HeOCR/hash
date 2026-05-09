# Licensing Policy

This repository is structured for compound licensing.

## Metadata

Metadata authored directly in this repository is dedicated to the public domain
under CC0 1.0 Universal (`CC0-1.0`):

https://creativecommons.org/publicdomain/zero/1.0/

To the extent possible under law, the repository contributors waive copyright
and related rights in this repository-authored metadata.

This includes:

- dataset structure documentation,
- source and entry index metadata authored here,
- validation scripts,
- generated metadata exports derived only from repository-authored metadata.

This CC0 dedication does not apply to third-party scan files, third-party source
metadata copied from providers, or provider-owned descriptive text unless that
material is separately released under compatible terms.

## Scan Files

Scan files are not automatically covered by the metadata license. Each scan must
carry its own entry-level rights record in `data/index/entries.jsonl`.

Use the scan only according to its recorded `rights.license_expression` and
permission fields:

- `commercial_use_allowed`,
- `derivatives_allowed`,
- `scan_redistribution_allowed`,
- `attribution_required`.

## Release Bundles

Remix-friendly public release bundles should include only entries where:

- redistribution is allowed,
- commercial use is allowed,
- derivatives are allowed,
- source and scan-level rights evidence has been checked.

If a release contains a mixture of public-domain, CC0, CC BY, or other compatible
terms, the release must keep per-entry license metadata and include attribution
where required. Do not describe such a bundle as having one uniform scan license
unless every included scan has the same license.

## Exclusions

Do not include scan files with any of the following terms in remix-friendly
bundles:

- non-commercial only,
- no derivatives,
- research-only,
- permission required,
- unknown rights,
- inaccessible source evidence.
