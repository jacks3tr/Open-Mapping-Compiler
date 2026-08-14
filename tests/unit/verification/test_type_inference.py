"""Type inference regressions for exact map item contexts."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.expressions import Expression
from open_mapping.model.schema import JsonType, SchemaDocument
from open_mapping.verification.type_inference import infer_expression_type


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["b"],
            "properties": {
                "a": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"x": {"type": "string"}}},
                },
                "b": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"y": {"type": "string"}}},
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {"$id": "target", "type": "object"}, schema_id=None, source_uri="target"
    )
    return source, target


def _map_current(path: str, *, collection: str = "/b") -> Expression:
    return TypeAdapter(Expression).validate_python(
        {
            "op": "map",
            "collection": {"op": "get", "path": collection, "document": "input"},
            "expression": {"op": "get", "path": path, "document": "current"},
        }
    )


def test_map_inference_uses_collection_item_schema() -> None:
    source, target = _schemas()

    assert infer_expression_type(
        _map_current("/y"),
        source_schema=source,
        target_schema=target,
        current_types=(),
    ) == frozenset({JsonType.ARRAY})


def test_map_inference_rejects_current_path_from_unrelated_array() -> None:
    source, target = _schemas()

    assert not infer_expression_type(
        _map_current("/x"),
        source_schema=source,
        target_schema=target,
        current_types=(),
    )


def test_map_inference_preserves_optional_collection_nullability() -> None:
    source, target = _schemas()

    assert infer_expression_type(
        _map_current("/", collection="/a"),
        source_schema=source,
        target_schema=target,
        current_types=(),
    ) == frozenset({JsonType.ARRAY, JsonType.NULL})
