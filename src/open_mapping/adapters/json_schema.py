"""JSON Schema Draft 2020-12 adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonScalar, JsonValue
from open_mapping.model.schema import JsonType, SchemaDocument, SchemaField
from open_mapping.pointers import escape_pointer_token
from open_mapping.serialization.canonical_json import canonical_json

_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _issue(code: IssueCode, message: str, correction: str, schema_id: str | None = None) -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component="adapters.json_schema",
        message=message,
        correction=correction,
        schema_id=schema_id,
    )


def _type_set(raw: Any) -> frozenset[JsonType]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        return frozenset({JsonType(raw)})
    if isinstance(raw, list):
        result: set[JsonType] = set()
        for item in raw:
            result.add(JsonType(item))
        return frozenset(result)
    raise OpenMappingError(
        (
            _issue(
                IssueCode.INVALID_INPUT,
                "schema type must be a string or array",
                "Use a valid JSON Schema type.",
            ),
        )
    )


def _infer_types(schema: dict[str, Any]) -> frozenset[JsonType]:
    if "type" in schema:
        return _type_set(schema["type"])
    if "properties" in schema or "additionalProperties" in schema:
        return frozenset({JsonType.OBJECT})
    if "items" in schema:
        return frozenset({JsonType.ARRAY})
    if "enum" in schema:
        result: set[JsonType] = set()
        for item in schema["enum"]:
            if item is None:
                result.add(JsonType.NULL)
            elif isinstance(item, bool):
                result.add(JsonType.BOOLEAN)
            elif isinstance(item, int):
                result.add(JsonType.INTEGER)
            elif isinstance(item, float):
                result.add(JsonType.NUMBER)
            elif isinstance(item, str):
                result.add(JsonType.STRING)
        return frozenset(result)
    return frozenset(JsonType)


def _enum_scalars(values: Any) -> tuple[JsonScalar, ...]:
    if not isinstance(values, list):
        return ()
    result: list[JsonScalar] = []
    for value in values:
        if (
            value is None
            or isinstance(value, (str, int, float, bool))
            and isinstance(value, bool) is not None
        ):
            if value is not None and isinstance(value, bool):
                result.append(value)
            elif value is None:
                result.append(None)
            elif isinstance(value, (str, int, float)):
                result.append(value)
    return tuple(result)


def _dereference(schema: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], str]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema, "#"
    if not ref.startswith("#/"):
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.REMOTE_REF_DISABLED,
                    f"remote reference {ref!r} is disabled",
                    "Use local references only.",
                ),
            )
        )
    tokens = [unescape_fragment(token) for token in ref[2:].split("/")]
    current: Any = document
    for token in tokens:
        if not isinstance(current, dict) or token not in current:
            raise OpenMappingError(
                (
                    _issue(
                        IssueCode.INVALID_INPUT,
                        f"unresolved local reference {ref!r}",
                        "Check the $ref path.",
                    ),
                )
            )
        current = current[token]
    if not isinstance(current, dict):
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                    "referenced schema must be an object",
                    "Use an object schema at the reference.",
                ),
            )
        )
    return current, ref


def unescape_fragment(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _parse_node(
    node: Any,
    pointer: str,
    required: bool,
    document: dict[str, Any],
    ref_stack: set[str],
    fields: list[SchemaField],
    schema_id: str,
    source_uri: str,
    location: str,
) -> frozenset[JsonType]:
    if isinstance(node, bool):
        if node:
            return frozenset(JsonType)
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                    "boolean false schema has no representable fields",
                    "Use an object schema.",
                ),
            )
        )
    if not isinstance(node, dict):
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.INVALID_INPUT,
                    "schema node must be an object or boolean",
                    "Use a valid JSON Schema node.",
                ),
            )
        )
    if "nullable" in node:
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                    "OpenAPI 3.0 nullable extension is not supported by the JSON Schema adapter",
                    "Use OpenAPI 3.1 type arrays or handle OpenAPI in the OpenAPI adapter.",
                ),
            )
        )
    if "$ref" in node:
        target, ref = _dereference(node, document)
        if ref in ref_stack:
            raise OpenMappingError(
                (
                    _issue(
                        IssueCode.CYCLIC_REF,
                        f"cyclic local reference {ref!r}",
                        "Remove the recursive reference.",
                    ),
                )
            )
        return _parse_node(
            target,
            pointer,
            required,
            document,
            ref_stack | {ref},
            fields,
            schema_id,
            source_uri,
            f"{location} -> {ref}",
        )

    if "allOf" in node:
        merged: dict[str, Any] = {}
        properties: dict[str, Any] = {}
        required_set: set[str] = set()
        for part in node["allOf"]:
            resolved, ref = (
                _dereference(part if isinstance(part, dict) else {}, document)
                if isinstance(part, dict) and "$ref" in part
                else (part, "")
            )
            if ref in ref_stack:
                raise OpenMappingError(
                    (
                        _issue(
                            IssueCode.CYCLIC_REF,
                            f"cyclic local reference {ref!r}",
                            "Remove the recursive reference.",
                        ),
                    )
                )
            if not isinstance(resolved, dict):
                continue
            for key, value in resolved.items():
                if key == "properties":
                    properties.update(value if isinstance(value, dict) else {})
                elif key == "required" and isinstance(value, list):
                    required_set.update(item for item in value if isinstance(item, str))
                elif key not in {"$schema", "$id", "title", "description"}:
                    if value is None:
                        continue
                    if key in merged and merged[key] != value:
                        raise OpenMappingError(
                            (
                                _issue(
                                    IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                                    f"conflicting allOf keyword {key!r}",
                                    "Split the schema into compatible branches.",
                                ),
                            )
                        )
                    merged[key] = value
        merged["properties"] = properties
        if required_set:
            merged["required"] = sorted(required_set)
        node = merged

    if "oneOf" in node or "anyOf" in node:
        alternatives = node.get("oneOf") or node.get("anyOf")
        if not isinstance(alternatives, list) or not alternatives:
            raise OpenMappingError(
                (
                    _issue(
                        IssueCode.INVALID_INPUT,
                        "oneOf/anyOf must be a non-empty array",
                        "Use a valid JSON Schema union.",
                    ),
                )
            )
        union_types: set[JsonType] = set()
        for alt in alternatives:
            alt_types = _parse_node(
                alt, pointer, required, document, ref_stack, fields, schema_id, source_uri, location
            )
            if JsonType.OBJECT in alt_types:
                raise OpenMappingError(
                    (
                        _issue(
                            IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                            "structurally incompatible object alternatives are not supported",
                            "Use a single object schema or compatible allOf merge.",
                        ),
                    )
                )
            union_types.update(alt_types)
        return frozenset(union_types)

    types = _infer_types(node)
    title = node.get("title")
    description = node.get("description")
    enum_values = _enum_scalars(node.get("enum"))
    minimum = node.get("minimum")
    maximum = node.get("maximum")
    min_length = node.get("minLength")
    max_length = node.get("maxLength")
    pattern = node.get("pattern")
    item_types = frozenset(JsonType)

    if pointer != "":
        fields.append(
            SchemaField(
                pointer=pointer,
                types=types,
                required=required,
                title=title if isinstance(title, str) else None,
                description=description if isinstance(description, str) else None,
                enum_values=enum_values,
                minimum=minimum if isinstance(minimum, (int, float)) else None,
                maximum=maximum if isinstance(maximum, (int, float)) else None,
                min_length=min_length if isinstance(min_length, int) else None,
                max_length=max_length if isinstance(max_length, int) else None,
                pattern=pattern if isinstance(pattern, str) else None,
                item_types=item_types,
                source_location=location,
            )
        )

    if JsonType.OBJECT in types and isinstance(node.get("properties"), dict):
        required_names = set(
            node.get("required", []) if isinstance(node.get("required"), list) else []
        )
        for key, child in sorted(node["properties"].items()):
            child_pointer = pointer + "/" + escape_pointer_token(str(key))
            _parse_node(
                child,
                child_pointer,
                str(key) in required_names,
                document,
                ref_stack,
                fields,
                schema_id,
                source_uri,
                f"{location}#/properties/{str(key).replace('~', '~0').replace('/', '~1')}",
            )

    if JsonType.ARRAY in types and "items" in node:
        item_schema = node["items"]
        item_types = (
            _infer_types(item_schema)
            if isinstance(item_schema, dict)
            else _infer_types(item_schema if isinstance(item_schema, dict) else {})
        )
        if isinstance(item_schema, dict):
            item_pointer = pointer + "/items"
            _parse_node(
                item_schema,
                item_pointer,
                False,
                document,
                ref_stack,
                fields,
                schema_id,
                source_uri,
                f"{location}#/items",
            )
        # Re-read the field so item_types is populated after child parsing.
        for index, existing in enumerate(fields):
            if existing.pointer == pointer and JsonType.ARRAY in existing.types:
                fields[index] = existing.model_copy(update={"item_types": item_types})
                break
        else:
            fields.append(
                SchemaField(
                    pointer=pointer,
                    types=types,
                    required=required,
                    item_types=item_types,
                    source_location=location,
                )
            )

    return types


def parse_json_schema(
    document: JsonValue, *, schema_id: str | None, source_uri: str
) -> SchemaDocument:
    if not isinstance(document, dict):
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.INVALID_INPUT,
                    "JSON Schema root must be an object",
                    "Use a valid JSON Schema document.",
                ),
            )
        )
    dialect = document.get("$schema", _DIALECT)
    if isinstance(dialect, str) and dialect != _DIALECT:
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.UNSUPPORTED_SCHEMA_FEATURE,
                    f"unsupported JSON Schema dialect {dialect!r}",
                    "Use JSON Schema Draft 2020-12.",
                ),
            )
        )
    resolved_id = schema_id
    if resolved_id is None:
        root_id = document.get("$id")
        if isinstance(root_id, str) and root_id:
            resolved_id = root_id
    if resolved_id is None:
        raise OpenMappingError(
            (
                _issue(
                    IssueCode.INVALID_INPUT,
                    "schema_id is required when $id is absent",
                    "Pass a schema ID or add $id.",
                ),
            )
        )
    version = document.get("x-schema-version", "unversioned")
    if not isinstance(version, str) or not version:
        version = "unversioned"
    fields: list[SchemaField] = []
    _parse_node(document, "", True, document, set(), fields, resolved_id, source_uri, source_uri)
    fields.sort(key=lambda field: tuple(field.pointer.split("/")))
    root_types = _infer_types(document)
    if JsonType.OBJECT not in root_types and "properties" in document:
        root_types = frozenset({JsonType.OBJECT})
    return SchemaDocument(
        schema_id=resolved_id,
        schema_version=version,
        dialect=_DIALECT if not isinstance(dialect, str) else dialect,
        root_types=root_types,
        fields=tuple(fields),
        canonical_source_json=canonical_json(document),
    )


def load_json_schema(path: Path, *, schema_id: str | None) -> SchemaDocument:
    content = path.read_text(encoding="utf-8")
    try:
        document: JsonValue = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.INVALID_INPUT,
                    severity=Severity.ERROR,
                    component="adapters.json_schema",
                    message=f"invalid JSON in schema file {path.name}",
                    correction="Use a valid JSON document.",
                    schema_id=schema_id,
                ),
            )
        ) from exc
    if schema_id is None and isinstance(document, dict):
        root_id = document.get("$id")
        if isinstance(root_id, str) and root_id:
            schema_id = root_id
        else:
            schema_id = path.stem
    if schema_id is None:
        schema_id = path.stem
    return parse_json_schema(document, schema_id=schema_id, source_uri=path.name)
