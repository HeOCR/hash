#!/usr/bin/env python3
"""Validate datapackage.json against the Frictionless Data Package spec.

Metadata-only: this script validates the descriptor against the published
spec without walking the JSONL resource bodies. It exists as a CI step
that is independent of the pytest harness, mirroring how
`validate_indexes.py` and pytest both enforce the JSONL contract from
different code paths.

A `frictionless validate datapackage.json` CLI invocation is not
equivalent: in frictionless 5.x the CLI walks resource bodies by default
and has no manifest-only flag, and JSONL is not a Frictionless-native
format, so the CLI returns INVALID on the resources before reaching any
spec check. `Package.metadata_validate` bypasses the resource layer and
checks only the descriptor — which is the contract we publish.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from frictionless import Package
except ImportError as exc:  # pragma: no cover - exercised when deps are absent.
    raise SystemExit(
        "Missing dependency: frictionless. Install development dependencies "
        "with `python3 -m pip install -r requirements-dev.txt`."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DATAPACKAGE_PATH = REPO_ROOT / "datapackage.json"


def main() -> int:
    package = Package(str(DATAPACKAGE_PATH))
    errors = list(Package.metadata_validate(package.to_descriptor()))
    for error in errors:
        print(f"ERROR: {error.message}", file=sys.stderr)
    if errors:
        return 1
    print(
        f"ok: datapackage.json metadata valid "
        f"({package.name} v{package.version})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
