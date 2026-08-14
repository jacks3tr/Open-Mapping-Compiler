"""OpenAPI 3.1 schema extraction."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.schema import SchemaDocument
from open_mapping.serialization.yaml_loader import load_safe_yaml


class OpenApiSelectorKind(StrEnum):
    COMPONENT = "component"
    REQUEST = "request"
    RESPONSE = "response"


class OpenApiSelector(OpenMappingModel):
    kind: OpenApiSelectorKind
    component_name: str | None = None
    operation_id: str | None = None
    status_code: str | None = None
    media_type: str = "application/json"


def parse_openapi_selector(value: str) -> OpenApiSelector:
    parts = value.split(":")
    kind_raw = parts[0]
    try:
        kind = OpenApiSelectorKind(kind_raw)
    except ValueError as exc:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="adapters.openapi",
                    message=f"unknown OpenAPI selector kind {kind_raw!r}",
                    correction="Use component, request, or response.",
                ),
            )
        ) from exc
    if kind == OpenApiSelectorKind.COMPONENT:
        if len(parts) != 2 or not parts[1]:
            raise OpenMappingError(
                (
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="adapters.openapi",
                        message="component selector requires component:NAME",
                        correction="Use a selector such as component:ProductionOrder.",
                    ),
                )
            )
        return OpenApiSelector(kind=kind, component_name=parts[1])
    if kind == OpenApiSelectorKind.REQUEST:
        if len(parts) != 2 or not parts[1]:
            raise OpenMappingError(
                (
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="adapters.openapi",
                        message="request selector requires request:OPERATION_ID",
                        correction="Use a selector such as request:createProductionOrder.",
                    ),
                )
            )
        return OpenApiSelector(kind=kind, operation_id=parts[1])
    if len(parts) not in {2, 3} or not parts[1]:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="adapters.openapi",
                    message="response selector requires response:OPERATION_ID[:STATUS]",
                    correction="Use a selector such as response:getProductionOrder:200.",
                ),
            )
        )
    return OpenApiSelector(
        kind=kind,
        operation_id=parts[1],
        status_code=parts[2] if len(parts) == 3 else "200",
    )


def _load_document(path: Path) -> JsonValue:
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return load_safe_yaml(content)
    try:
        return cast(JsonValue, json.loads(content))
    except json.JSONDecodeError as exc:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="adapters.openapi",
                    message=f"invalid JSON in OpenAPI document {path.name}",
                    correction="Use a valid JSON or YAML OpenAPI document.",
                ),
            )
        ) from exc


def _extract_schema(document: JsonValue, selector: OpenApiSelector, source_uri: str) -> JsonValue:
    if not isinstance(document, dict):
        raise OpenMappingError(
            (_openapi_issue("OpenAPI root must be an object", "Use a valid OpenAPI document."),)
        )
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3.1"):
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                    severity=Severity.ERROR,
                    component="adapters.openapi",
                    message="only OpenAPI 3.1 documents are supported",
                    correction="Convert the document to OpenAPI 3.1.",
                ),
            )
        )
    if selector.kind == OpenApiSelectorKind.COMPONENT:
        name = selector.component_name or ""
        components = document.get("components")
        schemas = components.get("schemas") if isinstance(components, dict) else None
        if not isinstance(schemas, dict) or name not in schemas:
            raise OpenMappingError(
                (
                    _openapi_issue(
                        f"component schema {name!r} was not found", "Check components.schemas."
                    ),
                )
            )
        return cast(JsonValue, schemas[name])
    if selector.kind == OpenApiSelectorKind.REQUEST:
        operation = _find_operation(document, selector.operation_id or "")
        request_body = operation.get("requestBody")
        if not isinstance(request_body, dict):
            raise OpenMappingError(
                (
                    _openapi_issue(
                        "operation has no requestBody", "Add a requestBody to the operation."
                    ),
                )
            )
        content = request_body.get("content")
        if not isinstance(content, dict) or selector.media_type not in content:
            raise OpenMappingError(
                (
                    _openapi_issue(
                        f"media type {selector.media_type!r} is missing",
                        "Add the media type to requestBody.content.",
                    ),
                )
            )
        media = content[selector.media_type]
        if not isinstance(media, dict) or "schema" not in media:
            raise OpenMappingError(
                (
                    _openapi_issue(
                        "request media object has no schema", "Add a schema to the media type."
                    ),
                )
            )
        return cast(JsonValue, media["schema"])
    operation = _find_operation(document, selector.operation_id or "")
    responses = operation.get("responses")
    status = selector.status_code or "200"
    if not isinstance(responses, dict) or status not in responses:
        raise OpenMappingError(
            (_openapi_issue(f"response {status!r} was not found", "Check operation responses."),)
        )
    response_obj = responses[status]
    content = response_obj.get("content") if isinstance(response_obj, dict) else None
    if not isinstance(content, dict) or selector.media_type not in content:
        raise OpenMappingError(
            (
                _openapi_issue(
                    f"media type {selector.media_type!r} is missing from response {status}",
                    "Add the media type to response content.",
                ),
            )
        )
    media = content[selector.media_type]
    if not isinstance(media, dict) or "schema" not in media:
        raise OpenMappingError(
            (
                _openapi_issue(
                    "response media object has no schema", "Add a schema to the media type."
                ),
            )
        )
    return cast(JsonValue, media["schema"])


def _openapi_issue(message: str, correction: str) -> Issue:
    return Issue(
        code=IssueCode.INVALID_INPUT,
        severity=Severity.ERROR,
        component="adapters.openapi",
        message=message,
        correction=correction,
    )


def _find_operation(document: dict[str, object], operation_id: str) -> dict[str, object]:
    matches: list[tuple[str, str, dict[str, object]]] = []
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise OpenMappingError(
            (_openapi_issue("OpenAPI document has no paths", "Add paths to the document."),)
        )
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            if operation.get("operationId") == operation_id:
                matches.append((path, method, operation))
    if not matches:
        raise OpenMappingError(
            (
                _openapi_issue(
                    f"operationId {operation_id!r} was not found",
                    "Check paths and operationId values.",
                ),
            )
        )
    if len(matches) > 1:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="adapters.openapi",
                    message=f"duplicate operationId {operation_id!r}",
                    correction="Make operationId values unique.",
                ),
            )
        )
    return matches[0][2]


def _resolve_schema(schema: JsonValue, document: JsonValue) -> JsonValue:
    current = schema
    seen = 0
    while isinstance(current, dict) and isinstance(current.get("$ref"), str) and seen < 64:
        ref = str(current["$ref"])
        if not ref.startswith("#/"):
            return current
        target: JsonValue = document
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or token not in target:
                raise OpenMappingError(
                    (
                        _openapi_issue(
                            f"unresolved local reference {ref!r}",
                            "Check the OpenAPI schema reference.",
                        ),
                    )
                )
            target = cast(JsonValue, target[token])
        current = target
        seen += 1
    return current


def load_openapi_schema(
    path: Path, *, selector: OpenApiSelector, schema_id: str | None
) -> SchemaDocument:
    document = _load_document(path)
    schema = _resolve_schema(_extract_schema(document, selector, path.name), document)
    resolved_id = schema_id
    if resolved_id is None and isinstance(schema, dict):
        root_id = schema.get("$id")
        if isinstance(root_id, str) and root_id:
            resolved_id = root_id
    if resolved_id is None:
        resolved_id = selector.component_name or selector.operation_id
    return parse_json_schema(
        schema,
        schema_id=resolved_id,
        source_uri=f"{path.name}:{selector.kind.value}:{selector.operation_id or selector.component_name or ''}:{selector.status_code or ''}",
    )


def load_schema(
    path: Path,
    *,
    format_name: Literal["json-schema", "openapi"],
    selector: OpenApiSelector | None,
    schema_id: str | None,
) -> SchemaDocument:
    if format_name == "openapi":
        if selector is None:
            raise OpenMappingError(
                (
                    _openapi_issue(
                        "OpenAPI inputs require a selector",
                        "Pass --selector with a component, request, or response selector.",
                    ),
                )
            )
        return load_openapi_schema(path, selector=selector, schema_id=schema_id)
    if selector is not None:
        raise OpenMappingError(
            (
                _openapi_issue(
                    "selectors are only valid for OpenAPI inputs",
                    "Remove the selector for JSON Schema inputs.",
                ),
            )
        )
    from open_mapping.adapters.json_schema import load_json_schema

    return load_json_schema(path, schema_id=schema_id)
