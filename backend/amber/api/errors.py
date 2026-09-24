"""Error bodies (plan §9): `{"issues": [...]}` for a 422, `{"error", "detail"}` for everything else.

Routes raise `ApiError` or return `issues_response`. `install` makes FastAPI's own errors (a 404 for an
unknown path, a 405, anything unexpected) come back in the same `{"error", "detail"}` shape.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from amber.contracts import ValidationErrorBody, ValidationIssue

log = logging.getLogger("amber.api")


class ApiError(Exception):
    """An error the client can act on: `error` is a stable code, `detail` a sentence for people."""

    def __init__(self, status: int, error: str, detail: str, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.status, self.error, self.detail, self.headers = status, error, detail, headers


def issues_response(issues: list[ValidationIssue]) -> JSONResponse:
    """The 422 for a design that can't run: the UI highlights every node and edge it names (§7.5)."""
    return JSONResponse(ValidationErrorBody(issues=issues).model_dump(mode="json", exclude_none=True), 422)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError) -> JSONResponse:
        return _error(e.status, e.error, e.detail, e.headers)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException) -> JSONResponse:
        return _error(e.status_code, _code(e.status_code), str(e.detail), e.headers)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal", "Something went wrong on our side. Try again.")


def _error(status: int, error: str, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status, headers)


def _code(status: int) -> str:
    return {404: "not_found", 405: "method_not_allowed"}.get(status, f"http_{status}")
