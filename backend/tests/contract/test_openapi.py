"""Public FastAPI/OpenAPI contract tests."""

from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter

from telco_twin.api.app import create_app
from telco_twin.api.openapi_contract import check_openapi, openapi_bytes

EXPECTED_METHODS = {
    "/.well-known/approval-root": {"get"},
    "/api/approval-requests/{id}": {"get"},
    "/api/approval-requests/{id}/approve": {"post"},
    "/api/approval-requests/{id}/reject": {"post"},
    "/api/benchmarks": {"post"},
    "/api/demo-sessions": {"post"},
    "/api/patches/{id}/simulations": {"post"},
    "/api/runs/{id}/events": {"get"},
    "/api/runs/{id}/evidence": {"get"},
    "/api/scenarios": {"get", "post"},
    "/api/scenarios/{id}": {"get"},
    "/api/scenarios/{id}/diagnose": {"post"},
    "/api/scenarios/{id}/patches": {"post"},
    "/api/simulations/{id}": {"get"},
    "/api/simulations/{id}/approval-requests": {"post"},
    "/api/simulations/{id}/comparisons": {"post"},
    "/build-info": {"get"},
    "/healthz": {"get"},
    "/readyz": {"get"},
}
OPENAPI_ARTIFACT = Path(__file__).resolve().parents[3] / "artifacts/contracts/openapi.json"
OPENAPI_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _operations() -> tuple[tuple[str, str, str], ...]:
    document = OPENAPI_ADAPTER.validate_json(openapi_bytes())
    assert isinstance(document, dict)
    paths = document.get("paths")
    assert isinstance(paths, dict)
    operations: list[tuple[str, str, str]] = []
    for path, path_item in paths.items():
        assert isinstance(path_item, dict)
        for method, operation in path_item.items():
            if method not in {"get", "post"}:
                continue
            assert isinstance(operation, dict)
            operation_id = operation.get("operationId")
            assert isinstance(operation_id, str)
            operations.append((path, method, operation_id))
    return tuple(operations)


def test_fastapi_boundary_package_exists_when_todo_seven_is_implemented() -> None:
    # Given: the accepted Todo 7 package boundary.
    # When: Python resolves the production API package.
    api_spec = find_spec("telco_twin.api")
    # Then: the package exists as a real import surface.
    assert api_spec is not None


def test_fastapi_application_module_exists_when_routes_are_exposed() -> None:
    # Given: the accepted application module location.
    # When: Python resolves the production module.
    app_spec = find_spec("telco_twin.api.app")
    # Then: the module exists rather than a test-only fake.
    assert app_spec is not None


def test_application_factory_is_public_when_contract_generation_runs() -> None:
    # Given: the real application module.
    module = import_module("telco_twin.api.app")
    # When: the contract generator resolves its public factory.
    factory = getattr(module, "create_app", None)
    # Then: a callable production factory is available.
    assert callable(factory)


def test_openapi_has_the_exact_public_route_and_method_set() -> None:
    # Given: the production application factory.
    _ = create_app()
    # When: FastAPI generates its machine-consumed contract.
    methods: dict[str, set[str]] = {}
    for path, method, _ in _operations():
        methods.setdefault(path, set()).add(method)
    # Then: every planned method is present and no extra path exists.
    assert methods == EXPECTED_METHODS


def test_openapi_exposes_no_network_mutation_or_revocation_operation() -> None:
    # Given: the machine-dispatched route paths and operation identifiers.
    _ = create_app()
    dispatch_surface = tuple(
        f"{path} {operation_id}".lower() for path, _, operation_id in _operations()
    )
    # When/Then: forbidden authority has no dispatchable operation.
    assert all(
        term not in surface
        for surface in dispatch_surface
        for term in ("execute", "push-config", "revoke")
    )


def test_generated_openapi_artifact_exists_for_contract_drift_checks() -> None:
    # Given/When: the repository contract artifact is inspected.
    exists = OPENAPI_ARTIFACT.is_file()
    # Then: Todo 7 publishes a nonempty generated OpenAPI artifact.
    assert exists
    assert OPENAPI_ARTIFACT.stat().st_size > 0
    assert OPENAPI_ARTIFACT.read_bytes() == openapi_bytes()
    assert check_openapi() is True
