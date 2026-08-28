"""RFC 9457-style structured failures with stable machine codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, override

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette import status
from starlette.exceptions import HTTPException as StarletteHttpException

from telco_twin.api.tracing import current_request_id

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class ProblemDetails(BaseModel):
    """Machine-readable failure envelope returned by every HTTP boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: str


@dataclass(frozen=True, slots=True)
class ProblemError(Exception):
    """Typed application failure translated only at the HTTP boundary."""

    status: int
    code: str
    title: str
    detail: str
    headers: tuple[tuple[str, str], ...] = ()

    @override
    def __str__(self) -> str:
        """Return the stable machine code without untrusted detail."""
        return self.code


def problem_response(error: ProblemError) -> JSONResponse:
    """Serialize one typed problem without including untrusted request content."""
    request_id = current_request_id()
    body = ProblemDetails(
        type=f"https://telco-twin.invalid/problems/{error.code}",
        title=error.title,
        status=error.status,
        code=error.code,
        detail=error.detail,
        request_id=request_id,
    )
    headers = {"X-Request-Id": request_id, **dict(error.headers)}
    return JSONResponse(
        status_code=error.status,
        content=body.model_dump(mode="json"),
        media_type="application/problem+json",
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Install one structured translation funnel for application and framework failures."""

    @app.exception_handler(ProblemError)
    async def handle_problem(_: Request, error: ProblemError) -> JSONResponse:
        return problem_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        _: Request,
        validation_error: RequestValidationError,
    ) -> JSONResponse:
        del validation_error
        return problem_response(
            ProblemError(
                status=422,
                code="request_validation_failed",
                title="Request validation failed",
                detail="The request body, path, query, or headers do not match the contract.",
            )
        )

    @app.exception_handler(StarletteHttpException)
    async def handle_framework(_: Request, error: StarletteHttpException) -> JSONResponse:
        missing = error.status_code == status.HTTP_404_NOT_FOUND
        code = "route_not_found" if missing else "method_not_allowed"
        title = "Route not found" if missing else "Method not allowed"
        return problem_response(
            ProblemError(
                status=error.status_code,
                code=code,
                title=title,
                detail="The requested HTTP operation is not part of the public contract.",
            )
        )

    _ = (handle_problem, handle_validation, handle_framework)
