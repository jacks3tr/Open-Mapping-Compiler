"""FastAPI sidecar for one prepared mapping bundle."""

from __future__ import annotations

import hmac
from typing import Literal

from anyio import CapacityLimiter, to_thread
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from open_mapping import __version__
from open_mapping.errors import OpenMappingError
from open_mapping.mapper import Mapper
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue

_MAX_BODY_BYTES = 10 * 1024 * 1024
_MAX_BATCH_SIZE = 1000


class _TransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: JsonValue


class _BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[JsonValue]
    on_error: Literal["raise", "collect"] = "raise"


def _issue(code: IssueCode, message: str, correction: str) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component="server",
        message=message,
        correction=correction,
    )


def _error_response(status: int, issues: tuple[Issue, ...]) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"issues": [issue.model_dump(mode="json") for issue in issues]},
    )


class _RequestSizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") == "http":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            raw_length = headers.get(b"content-length")
            if raw_length is not None:
                try:
                    too_large = int(raw_length) > _MAX_BODY_BYTES
                except ValueError:
                    too_large = False
                if too_large:
                    response = _error_response(
                        413,
                        (
                            _issue(
                                IssueCode.EVALUATION_LIMIT_EXCEEDED,
                                "request body exceeds the 10 MiB limit",
                                "Send a smaller request body.",
                            ),
                        ),
                    )
                    await response(scope, receive, send)
                    return
            received = 0

            async def limited_receive() -> Message:
                nonlocal received
                message = await receive()
                body = message.get("body", b"")
                if isinstance(body, bytes):
                    received += len(body)
                if received > _MAX_BODY_BYTES:
                    raise _BodyTooLarge
                return message

            try:
                await self._app(scope, limited_receive, send)
            except _BodyTooLarge:
                response = _error_response(
                    413,
                    (
                        _issue(
                            IssueCode.EVALUATION_LIMIT_EXCEEDED,
                            "request body exceeds the 10 MiB limit",
                            "Send a smaller request body.",
                        ),
                    ),
                )
                await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


def create_app(mapper: Mapper, *, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="Open Mapping Compiler", version=__version__)
    app.add_middleware(_RequestSizeLimit)
    execution_limit = CapacityLimiter(4)

    def run_batch(payload: _BatchRequest) -> dict[str, object]:
        if payload.on_error == "collect":
            return {
                "results": [
                    result.model_dump(mode="json") for result in mapper.iter_results(payload.inputs)
                ]
            }
        return {"outputs": mapper.transform_many(payload.inputs)}

    async def require_auth(authorization: str | None = Header(default=None)) -> None:
        if api_key is None:
            return
        expected = f"Bearer {api_key}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise OpenMappingError(
                (
                    _issue(
                        IssueCode.INVALID_INPUT,
                        "authentication is required",
                        "Send the configured bearer token.",
                    ),
                )
            )

    @app.exception_handler(OpenMappingError)
    async def open_mapping_error_handler(request: Request, error: OpenMappingError) -> JSONResponse:
        del request
        if any(issue.message == "authentication is required" for issue in error.issues):
            status = 401
        elif any(
            issue.component == "server" and issue.code is IssueCode.EVALUATION_LIMIT_EXCEEDED
            for issue in error.issues
        ):
            status = 413
        else:
            status = 422
        return _error_response(status, error.issues)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request, error
        return _error_response(
            422,
            (
                _issue(
                    IssueCode.INVALID_INPUT,
                    "request body does not match the endpoint contract",
                    "Send valid JSON with only the documented request fields.",
                ),
            ),
        )

    @app.get("/health", dependencies=[])
    async def health(authorization: str | None = Header(default=None)) -> dict[str, object]:
        await require_auth(authorization)
        return {
            "status": "ok",
            "mapping_id": mapper.mapping_id,
            "compiler_version": __version__,
        }

    @app.get("/metadata")
    async def metadata(authorization: str | None = Header(default=None)) -> dict[str, object]:
        await require_auth(authorization)
        bundle = mapper.bundle
        return {
            "mapping_id": mapper.mapping_id,
            "compiler_version": bundle.compiler_version,
            "bundle_version": bundle.bundle_version,
            "verification_level": bundle.verification.level.value,
            "sample_count": bundle.verification.sample_count,
            "mapping_sha256": bundle.mapping_sha256,
            "source_schema_sha256": bundle.source_schema_sha256,
            "target_schema_sha256": bundle.target_schema_sha256,
        }

    @app.post("/validate")
    async def validate(
        payload: _TransformRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_auth(authorization)
        issues = await to_thread.run_sync(
            mapper.validate_source, payload.input, limiter=execution_limit
        )
        return {
            "valid": not issues,
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }

    @app.post("/transform")
    async def transform(
        payload: _TransformRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, JsonValue]:
        await require_auth(authorization)
        output = await to_thread.run_sync(mapper.transform, payload.input, limiter=execution_limit)
        return {"output": output}

    @app.post("/transform-batch")
    async def transform_batch(
        payload: _BatchRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_auth(authorization)
        if len(payload.inputs) > _MAX_BATCH_SIZE:
            raise OpenMappingError(
                (
                    _issue(
                        IssueCode.EVALUATION_LIMIT_EXCEEDED,
                        "batch contains more than 1000 records",
                        "Split the batch into groups of at most 1000 records.",
                    ),
                )
            )
        return await to_thread.run_sync(run_batch, payload, limiter=execution_limit)

    return app


__all__ = ["create_app"]
