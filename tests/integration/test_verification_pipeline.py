"""Public execution and code generation must honor static authority."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.errors import OpenMappingError
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.runtime import run_mapping


def _mapping(rule: dict[str, object]) -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="mapping",
        source_schema="source",
        source_schema_version="unversioned",
        target_schema="target",
        target_schema_version="unversioned",
        rules=(rule,),
    )


def _enum_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["A", "B"]}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["A"]}},
        },
        schema_id=None,
        source_uri="target",
    )
    return (
        source,
        target,
        _mapping(
            {
                "target": "/status",
                "expression": {"op": "get", "path": "/status", "document": "input"},
            }
        ),
    )


def _array_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"sku": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    return (
        source,
        target,
        _mapping(
            {
                "target": "/lines",
                "expression": {
                    "op": "map",
                    "collection": {"op": "get", "path": "/lines", "document": "input"},
                    "expression": {
                        "op": "object",
                        "fields": {"wrong": {"op": "get", "path": "/sku", "document": "current"}},
                    },
                },
            }
        ),
    )


def _current_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
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
        {
            "$id": "target",
            "type": "object",
            "required": ["values"],
            "properties": {"values": {"type": "array", "items": {"type": "string"}}},
        },
        schema_id=None,
        source_uri="target",
    )
    return (
        source,
        target,
        _mapping(
            {
                "target": "/values",
                "expression": {
                    "op": "map",
                    "collection": {"op": "get", "path": "/b", "document": "input"},
                    "expression": {"op": "get", "path": "/x", "document": "current"},
                },
            }
        ),
    )


def _composite_array_case(op: str) -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["bad", "good"],
            "properties": {
                "bad": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["wrong"],
                        "properties": {"wrong": {"type": "string"}},
                    },
                },
                "good": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    expression: dict[str, object]
    if op == "if":
        expression = {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "get", "path": "/bad", "document": "input"},
            "otherwise": {"op": "get", "path": "/good", "document": "input"},
        }
    else:
        expression = {
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/bad", "document": "input"},
                {"op": "get", "path": "/good", "document": "input"},
            ),
        }
    return source, target, _mapping({"target": "/lines", "expression": expression})


def _conditional_array_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    return _composite_array_case("if")


def _coalesce_array_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    return _composite_array_case("coalesce")


def _valid_nullable_coalesce_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["maybe", "fallback"],
            "properties": {
                "maybe": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
                "fallback": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "coalesce",
                "operands": (
                    {"op": "get", "path": "/maybe", "document": "input"},
                    {"op": "get", "path": "/fallback", "document": "input"},
                ),
            },
        }
    )
    return source, target, mapping


def _invalid_all_nullable_coalesce_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "maybeA": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
                "maybeB": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "coalesce",
                "operands": (
                    {"op": "get", "path": "/maybeA", "document": "input"},
                    {"op": "get", "path": "/maybeB", "document": "input"},
                ),
            },
        }
    )
    return source, target, mapping


def _invalid_all_optional_coalesce_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "maybeA": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
                "maybeB": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "coalesce",
                "operands": (
                    {"op": "get", "path": "/maybeA", "document": "input"},
                    {"op": "get", "path": "/maybeB", "document": "input"},
                ),
            },
        }
    )
    return source, target, mapping


def _optional_map_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    item_schema = {
        "type": "object",
        "required": ["partNumber"],
        "properties": {"partNumber": {"type": "string"}},
    }
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {
                "optionalLines": {"type": "array", "items": item_schema},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["lines"],
            "properties": {"lines": {"type": "array", "items": item_schema}},
        },
        schema_id=None,
        source_uri="target",
    )
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "map",
                "collection": {
                    "op": "get",
                    "path": "/optionalLines",
                    "document": "input",
                },
                "expression": {"op": "get", "path": "/", "document": "current"},
            },
        }
    )
    return source, target, mapping


def _non_exhaustive_scalar_lookup_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["selector"],
            "properties": {"selector": {"type": "string", "enum": ["known", "other"]}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["label"],
            "properties": {"label": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    mapping = _mapping(
        {
            "target": "/label",
            "expression": {
                "op": "lookup",
                "key": {"op": "get", "path": "/selector", "document": "input"},
                "values": {"known": "Known"},
            },
        }
    )
    return source, target, mapping


def _composite_object_coverage_case(
    kind: str,
) -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["selector"],
            "properties": {"selector": {"type": "string", "enum": ["a", "b"]}},
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["out"],
            "properties": {
                "out": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "string"}},
                }
            },
        },
        schema_id=None,
        source_uri="target",
    )
    object_a = {"op": "object", "fields": {"x": {"op": "literal", "value": "a"}}}
    object_b = {"op": "object", "fields": {"x": {"op": "literal", "value": "b"}}}
    if kind == "if":
        expression: dict[str, object] = {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": object_a,
            "otherwise": object_b,
        }
    elif kind == "coalesce":
        expression = {"op": "coalesce", "operands": (object_a, object_b)}
    else:
        expression = {
            "op": "coalesce",
            "operands": (
                {
                    "op": "lookup",
                    "key": {"op": "get", "path": "/selector", "document": "input"},
                    "values": {"a": {"x": "lookup"}},
                },
                object_b,
            ),
        }
    return source, target, _mapping({"target": "/out", "expression": expression})


def _conditional_object_coverage_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    return _composite_object_coverage_case("if")


def _coalesced_object_coverage_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    return _composite_object_coverage_case("coalesce")


def _absorbed_lookup_object_case() -> tuple[SchemaDocument, SchemaDocument, MappingDocument]:
    return _composite_object_coverage_case("lookup")


@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_accept_valid_nullable_structural_coalesce(
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = _valid_nullable_coalesce_case()

    compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_reject_all_nullable_structural_coalesce(
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = _invalid_all_nullable_coalesce_case()

    with pytest.raises(OpenMappingError):
        compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_reject_all_optional_structural_coalesce(
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = _invalid_all_optional_coalesce_case()

    with pytest.raises(OpenMappingError):
        compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_reject_map_over_optional_collection(
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = _optional_map_case()

    with pytest.raises(OpenMappingError):
        compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_reject_non_exhaustive_scalar_lookup_without_default(
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = _non_exhaustive_scalar_lookup_case()

    with pytest.raises(OpenMappingError):
        compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize(
    "case",
    [
        _conditional_object_coverage_case,
        _coalesced_object_coverage_case,
        _absorbed_lookup_object_case,
    ],
)
@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_accept_sound_composite_object_coverage(
    case: Callable[[], tuple[SchemaDocument, SchemaDocument, MappingDocument]],
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = case()

    compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize(
    "case",
    [_enum_case, _array_case, _current_case, _conditional_array_case, _coalesce_array_case],
)
@pytest.mark.parametrize("compiler", [generate_python, generate_typescript])
def test_public_compilers_block_static_invalid_mapping(
    case: Callable[[], tuple[SchemaDocument, SchemaDocument, MappingDocument]],
    compiler: Callable[..., object],
) -> None:
    source, target, mapping = case()

    with pytest.raises(OpenMappingError):
        compiler(mapping, source_schema=source, target_schema=target)


@pytest.mark.parametrize(
    "case",
    [_enum_case, _array_case, _current_case, _conditional_array_case, _coalesce_array_case],
)
def test_public_runtime_blocks_static_invalid_mapping(
    case: Callable[[], tuple[SchemaDocument, SchemaDocument, MappingDocument]],
) -> None:
    source, target, mapping = case()

    with pytest.raises(OpenMappingError):
        run_mapping(
            mapping,
            source_schema=source,
            target_schema=target,
            source={},
        )
