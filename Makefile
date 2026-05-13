# Convenience targets that wrap the repo's pre-PR / release commands.
# Mandatory pre-PR commands live in AGENTS.md; this Makefile mirrors that list
# without becoming the source of truth for it.

PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help validate artifacts exports release test all check

help:
	@echo "Targets:"
	@echo "  validate   - run scripts/validate_indexes.py + validate_datapackage.py"
	@echo "  artifacts  - regenerate NOTICE.md, CITATION.cff, datapackage.json,"
	@echo "               and the README status section"
	@echo "  exports    - regenerate exports/*.csv and dist/entries.parquet"
	@echo "  release    - run 'check' first, then assemble dist/<package>-<version>.tar.gz"
	@echo "  test       - run pytest"
	@echo "  check      - validate + all --check gates + pytest + git diff --check"
	@echo "  all        - validate + artifacts + exports + test + release"

validate:
	$(PYTHON) scripts/validate_indexes.py
	$(PYTHON) scripts/validate_datapackage.py

artifacts:
	$(PYTHON) scripts/generate_release_artifacts.py
	$(PYTHON) scripts/update_readme_status.py

exports:
	$(PYTHON) scripts/build_exports.py

# `release` deliberately depends on `check`, not on `artifacts` / `exports`.
# A release target that silently rewrites committed files (NOTICE.md,
# datapackage.json, exports/*.csv) is a footgun: the resulting tarball would
# not match any committed git state. `make check` enforces that everything is
# already in sync; only then do we build the tarball.
release: check
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
	git diff --check

all: validate artifacts exports test release
