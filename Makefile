.PHONY: check-specs python-lint python-typecheck python-test frontend-typecheck verify

check-specs:
	uv run --project backend python scripts/check_specs.py

python-lint:
	uv run --project backend ruff check backend/src backend/tests scripts
	uv run --project backend ruff format --check backend/src backend/tests scripts

python-typecheck:
	uv run --project backend basedpyright
	uv run --project backend mypy backend/src backend/tests scripts

python-test:
	uv run --project backend pytest backend/tests -q

frontend-typecheck:
	pnpm --dir frontend typecheck

verify: check-specs python-lint python-typecheck python-test frontend-typecheck
