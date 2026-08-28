"""FastAPI application assembly."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from telco_twin.api.abuse import BootstrapBodyLimitMiddleware
from telco_twin.api.errors import install_error_handlers
from telco_twin.api.logging import ResponseLoggingMiddleware
from telco_twin.api.routes import (
    approval_keys,
    approvals,
    benchmarks,
    build_info,
    comparisons,
    events,
    health,
    patches,
    scenarios,
    sessions,
    simulations,
)
from telco_twin.api.runtime import ApiRuntime
from telco_twin.api.settings import ApiSettings
from telco_twin.api.tracing import RequestTracingMiddleware
from telco_twin.state.trusted_clock import TrustedClock


class TwinFastAPI(FastAPI):
    """FastAPI application with a typed process-runtime handle."""

    _twin_runtime: ApiRuntime | None = None

    @property
    def runtime(self) -> ApiRuntime:
        """Return the runtime after application assembly has bound it."""
        if self._twin_runtime is None:
            msg = "Twin API runtime is not bound"
            raise RuntimeError(msg)
        return self._twin_runtime

    def bind_runtime(self, runtime: ApiRuntime) -> None:
        """Bind exactly one runtime during application assembly."""
        if self._twin_runtime is not None:
            msg = "Twin API runtime is already bound"
            raise RuntimeError(msg)
        self._twin_runtime = runtime


def create_app(
    settings: ApiSettings | None = None,
    clock: TrustedClock | None = None,
) -> TwinFastAPI:
    """Create the contract-first Twin API application."""
    runtime = ApiRuntime(settings, clock)
    app = TwinFastAPI(
        title="Telco Counterfactual Twin API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.bind_runtime(runtime)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Demo-Session-Token",
        ],
        expose_headers=["Idempotency-Replayed", "X-Request-Id"],
    )
    app.add_middleware(ResponseLoggingMiddleware)
    app.add_middleware(BootstrapBodyLimitMiddleware)
    app.add_middleware(RequestTracingMiddleware)
    install_error_handlers(app)
    for route in (
        health.router(runtime),
        build_info.router(runtime),
        approval_keys.router(runtime),
        sessions.router(runtime),
        scenarios.router(runtime),
        patches.router(runtime),
        simulations.router(runtime),
        comparisons.router(runtime),
        approvals.router(runtime),
        events.router(runtime),
        benchmarks.router(runtime),
    ):
        app.include_router(route)
    return app


app = create_app()
