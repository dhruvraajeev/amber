"""The two endpoints that take a design (plan §9): validate it, or run it.

Both take raw JSON, not a typed body: `sim/graph.validate` must see a broken design as it was sent, so it
can report every problem at once with node ids the UI can highlight. A typed body would have FastAPI
answer first, with its own error shape and nothing the canvas can use.
"""

import math
import time
from functools import partial

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from amber.api.errors import ApiError, issues_response
from amber.api.limits import MAX_WALL_S, read_json
from amber.contracts import Design, RunConfig, RunResult, ValidationErrorBody
from amber.sim.graph import validate
from amber.sim.kernel import SimTimeout
from amber.sim.run import simulate

router = APIRouter(prefix="/api")


@router.post("/validate", response_model_exclude_none=True)
async def validate_design(request: Request) -> ValidationErrorBody:
    """`{design, config?}` → every issue (§7.6, and §3's run limits when `config` is sent). Always 200."""
    design, config = _design_and_config(await read_json(request))
    return ValidationErrorBody(issues=validate(design, config))


@router.post(
    "/simulate",
    response_model=RunResult,
    response_model_exclude_none=True,
    responses={422: {"model": ValidationErrorBody, "description": "The design can't run as it is."}},
)
async def simulate_design(request: Request) -> RunResult | JSONResponse:
    """`{design, config}` → the RunResult (§7.4), or 422 with the issues, 429, 504 or 501."""
    _take_permit(request)
    design, config = _design_and_config(await read_json(request))
    config = {} if config is None else config  # a run needs one: missing fields come back as issues
    if issues := validate(design, config):
        return issues_response(issues)

    # Threads, because a run is pure CPU and would otherwise freeze every other request (/healthz too);
    # two at a time, because more would only share the same cores. Waiting for a turn isn't timed.
    parsed = Design.model_validate(design), RunConfig.model_validate(config)
    run = partial(simulate, *parsed, wall_limit_s=MAX_WALL_S)
    async with request.app.state.simulations:
        try:
            return await anyio.to_thread.run_sync(run)
        except SimTimeout:
            raise ApiError(
                504,
                "timeout",
                f"This run took longer than {MAX_WALL_S:g} s to simulate, so it was stopped. "
                "Shorten it or lower the traffic.",
            ) from None
        except NotImplementedError as e:  # self-hosted LLM nodes, until Step 21
            detail = str(e)  # not .capitalize(), which would lowercase "LLM"
            raise ApiError(501, "not_implemented", f"{detail[:1].upper()}{detail[1:]}.") from None


def _take_permit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if wait_s := request.app.state.limiter.take(client, time.monotonic()):
        raise ApiError(
            429,
            "rate_limited",
            "Too many simulations from this address. Wait a moment and try again.",
            {"Retry-After": str(math.ceil(wait_s))},  # rounded up: never tell a client to come back early
        )


def _design_and_config(body: object) -> tuple[object, object]:
    """`body["design"]` and `body.get("config")`. A missing design is None, which `validate` reports."""
    if not isinstance(body, dict):
        return None, None
    return body.get("design"), body.get("config")
