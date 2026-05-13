# Convenience targets that wrap the repo's pre-PR / release commands.
# Mandatory pre-PR commands live in AGENTS.md; this Makefile mirrors that list
# without becoming the source of truth for it.

PYTHON ?= python3

.PHONY: help validate artifacts exports release test all check

help:
	@echo "Targets:"
	@echo "  validate   - run scripts/validate_indexes.py (schema + file integrity)"
	@echo "  artifacts  - regenerate NOTICE.md, CITATION.cff, datapackage.json"
	@echo "  exports    - regenerate exports/*.csv and dist/entries.parquet"
	@echo "  release    - assemble dist/<package>-<version>.tar.gz"
	@echo "  test       - run pytest"
	@echo "  check      - validate + artifacts --check + exports --check + test"
	@echo "  all        - validate + artifacts + exports + test + release"

validate:
	$(PYTHON) scripts/validate_indexes.py
	$(PYTHON) scripts/validate_datapackage.py

artifacts:
	$(PYTHON) scripts/generate_release_artifacts.py
	$(PYTHON) scripts/update_readme_status.py

exports:
	$(PYTHON) scripts/build_exports.py

release: artifacts exports
	$(PYTHON) scripts/build_release.py

test:
	$(PYTHON) -m pytest

check:
	$(PYTHON) scripts/validate_indexes.py
	$(PYTHON) scripts/validate_datapackage.py
	$(PYTHON) scripts/generate_release_artifacts.py --check
	$(PYTHON) scripts/update_readme_status.py --check
	$(PYTHON) scripts/build_exports.py --check
	$(PYTHON) -m pytest

all: validate artifacts exports test release
