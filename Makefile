.PHONY: bootstrap check-specs python-lint python-typecheck python-test frontend-check frontend-typecheck frontend-test frontend-build contracts-check release-evidence-check verify security sbom-generate sbom-check probe generate-release-evidence

bootstrap:
	uv sync --project backend --locked --all-groups
	pnpm --dir frontend install --frozen-lockfile

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

frontend-check:
	pnpm --dir frontend check

frontend-test:
	pnpm --dir frontend test

frontend-build:
	pnpm --dir frontend build

contracts-check:
	uv run --project backend python scripts/export_schemas.py --check
	uv run --project backend python -m telco_twin.api.openapi_contract --check
	uv run --project backend python scripts/export_mcp_tools.py --check

release-evidence-check:
	uv run --project backend python scripts/verify_release_manifest.py

verify: check-specs python-lint python-typecheck python-test frontend-check frontend-typecheck frontend-test frontend-build contracts-check release-evidence-check

security: sbom-check
	uv run --project backend python scripts/assert_no_execution_surface.py specs/schemas backend/src/telco_twin/mcp backend/src/telco_twin/api
	uv run --project backend python scripts/scan_synthetic_boundary.py backend/src backend/fixtures frontend/src specs artifacts/eval

sbom-generate:
	bash scripts/generate_sbom.sh --repo-root . --out artifacts/security/component-inventory.json

sbom-check:
	test -f artifacts/security/component-inventory.json
	tmp_dir="$$(mktemp -d)"; trap 'rm -rf "$$tmp_dir"' EXIT; bash scripts/generate_sbom.sh --repo-root . --out "$$tmp_dir/component-inventory.json"; cmp "$$tmp_dir/component-inventory.json" artifacts/security/component-inventory.json

probe:
	./scripts/with_compose_cleanup.sh -f docker-compose.yml -- uv run --project backend python scripts/probe_stack.py --out artifacts/probe/local-stack-probe.json

generate-release-evidence:
	uv run --project backend python scripts/generate_release_evidence.py
	uv run --project backend python scripts/verify_release_manifest.py
