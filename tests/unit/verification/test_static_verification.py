"""Soundness regressions for whole-mapping static verification."""

from __future__ import annotations

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.issues import IssueCode
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.static import verify_static


def _schema(schema_id: str, properties: dict[str, object], required: list[str]) -> SchemaDocument:
    return parse_json_schema(
        {
            "$id": schema_id,
            "type": "object",
            "properties": properties,
            "required": required,
        },
        schema_id=None,
        source_uri=schema_id,
    )


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


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "get", "path": "/status", "document": "input"},
        {
            "op": "lookup",
            "key": {"op": "get", "path": "/status", "document": "input"},
            "values": {"A": "A", "B": "B"},
        },
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "literal", "value": "A"},
            "otherwise": {"op": "literal", "value": "B"},
        },
    ],
    ids=("direct-get", "lookup", "conditional"),
)
def test_closed_enum_rejects_any_statically_possible_out_of_domain_value(
    expression: dict[str, object],
) -> None:
    source = _schema(
        "source",
        {"status": {"type": "string", "enum": ["A", "B"]}},
        ["status"],
    )
    target = _schema(
        "target",
        {"status": {"type": "string", "enum": ["A"]}},
        ["status"],
    )

    result = verify_static(
        _mapping({"target": "/status", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/status"
        for issue in result.issues
    )


def test_closed_enum_accepts_source_domain_subset() -> None:
    source = _schema(
        "source",
        {"status": {"type": "string", "enum": ["A"]}},
        ["status"],
    )
    target = _schema(
        "target",
        {"status": {"type": "string", "enum": ["A", "B"]}},
        ["status"],
    )

    result = verify_static(
        _mapping(
            {
                "target": "/status",
                "expression": {"op": "get", "path": "/status", "document": "input"},
            }
        ),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def test_closed_enum_rejects_unbounded_string_output() -> None:
    source = _schema("source", {"status": {"type": "string"}}, ["status"])
    target = _schema(
        "target",
        {"status": {"type": "string", "enum": ["A"]}},
        ["status"],
    )

    result = verify_static(
        _mapping(
            {
                "target": "/status",
                "expression": {"op": "get", "path": "/status", "document": "input"},
            }
        ),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/status"
        for issue in result.issues
    )


def _array_schema(schema_id: str, item_schema: dict[str, object]) -> SchemaDocument:
    return _schema(
        schema_id,
        {"lines": {"type": "array", "items": item_schema}},
        ["lines"],
    )


def test_map_rejects_missing_required_array_item_field() -> None:
    source = _array_schema(
        "source",
        {
            "type": "object",
            "required": ["sku"],
            "properties": {"sku": {"type": "string"}},
        },
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )
    mapping = _mapping(
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
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED
        and issue.target_path == "/lines/items/partNumber"
        for issue in result.issues
    )


def test_map_rejects_missing_nested_required_array_item_field() -> None:
    source = _array_schema(
        "source",
        {
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "string"}},
        },
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["details"],
            "properties": {
                "details": {
                    "type": "object",
                    "required": ["code"],
                    "properties": {"code": {"type": "string"}},
                }
            },
        },
    )
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "map",
                "collection": {"op": "get", "path": "/lines", "document": "input"},
                "expression": {
                    "op": "object",
                    "fields": {"details": {"op": "object", "fields": {}}},
                },
            },
        }
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED
        and issue.target_path == "/lines/items/details/code"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "map",
            "collection": {"op": "get", "path": "/lines", "document": "input"},
            "expression": {"op": "get", "path": "", "document": "current"},
        },
        {"op": "array", "items": ({"op": "literal", "value": "fixed"},)},
    ],
    ids=("mapped-scalars", "literal-scalars"),
)
def test_arrays_of_scalars_are_statically_valid(expression: dict[str, object]) -> None:
    source = _array_schema("source", {"type": "string"})
    target = _array_schema("target", {"type": "string"})

    result = verify_static(
        _mapping({"target": "/lines", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


@pytest.mark.parametrize("source_item_required", [True, False], ids=("complete", "incomplete"))
def test_direct_array_mapping_requires_assignable_item_structure(
    source_item_required: bool,
) -> None:
    source = _array_schema(
        "source",
        {
            "type": "object",
            "required": ["partNumber"] if source_item_required else [],
            "properties": {"partNumber": {"type": "string"}},
        },
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )

    result = verify_static(
        _mapping(
            {
                "target": "/lines",
                "expression": {"op": "get", "path": "/lines", "document": "input"},
            }
        ),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid is source_item_required


def test_current_path_is_resolved_only_against_iterated_collection() -> None:
    source = _schema(
        "source",
        {
            "a": {
                "type": "array",
                "items": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
            "b": {
                "type": "array",
                "items": {"type": "object", "properties": {"y": {"type": "string"}}},
            },
        },
        ["a", "b"],
    )
    target = _schema(
        "target",
        {"values": {"type": "array", "items": {"type": "string"}}},
        ["values"],
    )
    mapping = _mapping(
        {
            "target": "/values",
            "expression": {
                "op": "map",
                "collection": {"op": "get", "path": "/b", "document": "input"},
                "expression": {"op": "get", "path": "/x", "document": "current"},
            },
        }
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(issue.code == IssueCode.SOURCE_PATH_NOT_FOUND for issue in result.issues)


def test_nested_maps_use_the_top_exact_item_context() -> None:
    source = _schema(
        "source",
        {
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["children"],
                    "properties": {
                        "children": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["value"],
                                "properties": {"value": {"type": "string"}},
                            },
                        }
                    },
                },
            }
        },
        ["groups"],
    )
    target = _schema(
        "target",
        {
            "values": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            }
        },
        ["values"],
    )
    mapping = _mapping(
        {
            "target": "/values",
            "expression": {
                "op": "map",
                "collection": {"op": "get", "path": "/groups", "document": "input"},
                "expression": {
                    "op": "map",
                    "collection": {"op": "get", "path": "/children", "document": "current"},
                    "expression": {"op": "get", "path": "/value", "document": "current"},
                },
            },
        }
    )

    assert verify_static(mapping, source_schema=source, target_schema=target).valid


def test_computed_collection_does_not_borrow_an_unrelated_item_shape() -> None:
    source = _schema(
        "source",
        {
            "unrelated": {
                "type": "array",
                "items": {"type": "object", "properties": {"x": {"type": "string"}}},
            }
        },
        [],
    )
    target = _schema(
        "target",
        {"values": {"type": "array", "items": {"type": "string"}}},
        ["values"],
    )
    mapping = _mapping(
        {
            "target": "/values",
            "expression": {
                "op": "map",
                "collection": {
                    "op": "array",
                    "items": (
                        {
                            "op": "object",
                            "fields": {"y": {"op": "literal", "value": "known"}},
                        },
                    ),
                },
                "expression": {"op": "get", "path": "/x", "document": "current"},
            },
        }
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(issue.code == IssueCode.SOURCE_PATH_NOT_FOUND for issue in result.issues)


def _composite_array_schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = _schema(
        "source",
        {
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
            "selector": {"type": "string", "enum": ["bad", "good"]},
        },
        ["bad", "good", "selector"],
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )
    return source, target


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "get", "path": "/bad", "document": "input"},
            "otherwise": {"op": "get", "path": "/good", "document": "input"},
        },
        {
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/bad", "document": "input"},
                {"op": "get", "path": "/good", "document": "input"},
            ),
        },
        {
            "op": "literal",
            "value": [{"wrong": "x"}],
        },
        {
            "op": "lookup",
            "key": {"op": "get", "path": "/selector", "document": "input"},
            "values": {
                "bad": [{"wrong": "x"}],
                "good": [{"partNumber": "P-1"}],
            },
        },
    ],
    ids=("conditional", "coalesce", "literal", "lookup"),
)
def test_all_array_producers_reject_an_invalid_possible_item_shape(
    expression: dict[str, object],
) -> None:
    source, target = _composite_array_schemas()

    result = verify_static(
        _mapping({"target": "/lines", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED
        and issue.target_path == "/lines/items/partNumber"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "get", "path": "/good", "document": "input"},
            "otherwise": {"op": "get", "path": "/good", "document": "input"},
        },
        {
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/good", "document": "input"},
                {"op": "get", "path": "/good", "document": "input"},
            ),
        },
        {"op": "literal", "value": [{"partNumber": "P-1"}]},
        {
            "op": "lookup",
            "key": {"op": "get", "path": "/selector", "document": "input"},
            "values": {
                "bad": [{"partNumber": "P-1"}],
                "good": [{"partNumber": "P-2"}],
            },
        },
    ],
    ids=("conditional", "coalesce", "literal", "lookup"),
)
def test_valid_composite_array_producers_remain_supported(
    expression: dict[str, object],
) -> None:
    source, target = _composite_array_schemas()

    assert verify_static(
        _mapping({"target": "/lines", "expression": expression}),
        source_schema=source,
        target_schema=target,
    ).valid


def test_lookup_array_requires_an_exhaustive_key_domain_or_default() -> None:
    source, target = _composite_array_schemas()
    mapping = _mapping(
        {
            "target": "/lines",
            "expression": {
                "op": "lookup",
                "key": {"op": "get", "path": "/selector", "document": "input"},
                "values": {"good": [{"partNumber": "P-1"}]},
            },
        }
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines"
        for issue in result.issues
    )


def test_nullable_structural_coalesce_accepts_a_valid_fallback() -> None:
    source = _schema(
        "source",
        {
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
        ["maybe", "fallback"],
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )

    result = verify_static(
        _mapping(
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
        ),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def test_all_nullable_structural_coalesce_remains_nullable() -> None:
    source = _schema(
        "source",
        {
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
        [],
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )

    result = verify_static(
        _mapping(
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
        ),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines"
        for issue in result.issues
    )


def test_all_optional_structural_coalesce_remains_nullable() -> None:
    source = _schema(
        "source",
        {
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
        [],
    )
    target = _array_schema(
        "target",
        {
            "type": "object",
            "required": ["partNumber"],
            "properties": {"partNumber": {"type": "string"}},
        },
    )

    result = verify_static(
        _mapping(
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
        ),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines"
        for issue in result.issues
    )


def test_current_get_under_an_optional_parent_remains_nullable() -> None:
    source = _schema(
        "source",
        {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "details": {
                            "type": "object",
                            "required": ["code"],
                            "properties": {"code": {"type": "string"}},
                        }
                    },
                },
            }
        },
        ["lines"],
    )
    target = _schema(
        "target",
        {"values": {"type": "array", "items": {"type": "string"}}},
        ["values"],
    )
    mapping = _mapping(
        {
            "target": "/values",
            "expression": {
                "op": "map",
                "collection": {"op": "get", "path": "/lines", "document": "input"},
                "expression": {
                    "op": "get",
                    "path": "/details/code",
                    "document": "current",
                },
            },
        }
    )

    result = verify_static(mapping, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/values/items"
        for issue in result.issues
    )


def _optional_map_schemas() -> tuple[SchemaDocument, SchemaDocument]:
    item_schema: dict[str, object] = {
        "type": "object",
        "required": ["partNumber"],
        "properties": {"partNumber": {"type": "string"}},
    }
    source = _schema(
        "source",
        {
            "optionalLines": {"type": "array", "items": item_schema},
            "fallback": {"type": "array", "items": item_schema},
        },
        ["fallback"],
    )
    target = _array_schema("target", item_schema)
    return source, target


def _optional_lines_map() -> dict[str, object]:
    return {
        "op": "map",
        "collection": {"op": "get", "path": "/optionalLines", "document": "input"},
        "expression": {"op": "get", "path": "/", "document": "current"},
    }


def test_map_over_optional_collection_remains_nullable() -> None:
    source, target = _optional_map_schemas()

    result = verify_static(
        _mapping({"target": "/lines", "expression": _optional_lines_map()}),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines"
        for issue in result.issues
    )


def test_optional_collection_map_accepts_required_coalesce_fallback() -> None:
    source, target = _optional_map_schemas()

    result = verify_static(
        _mapping(
            {
                "target": "/lines",
                "expression": {
                    "op": "coalesce",
                    "operands": (
                        _optional_lines_map(),
                        {"op": "get", "path": "/fallback", "document": "input"},
                    ),
                },
            }
        ),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def _scalar_lookup_schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = _schema(
        "source",
        {"selector": {"type": "string", "enum": ["known", "other"]}},
        ["selector"],
    )
    target = _schema("target", {"label": {"type": "string"}}, ["label"])
    return source, target


def _scalar_lookup(values: dict[str, str]) -> dict[str, object]:
    return {
        "op": "lookup",
        "key": {"op": "get", "path": "/selector", "document": "input"},
        "values": values,
    }


def test_scalar_lookup_without_default_remains_nullable_when_key_is_not_exhaustive() -> None:
    source, target = _scalar_lookup_schemas()

    result = verify_static(
        _mapping({"target": "/label", "expression": _scalar_lookup({"known": "Known"})}),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/label"
        for issue in result.issues
    )


def test_scalar_lookup_without_default_accepts_exhaustive_enum_keys() -> None:
    source, target = _scalar_lookup_schemas()

    result = verify_static(
        _mapping(
            {
                "target": "/label",
                "expression": _scalar_lookup({"known": "Known", "other": "Other"}),
            }
        ),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def _object_expression(field: str = "x", value: str = "value") -> dict[str, object]:
    return {
        "op": "object",
        "fields": {field: {"op": "literal", "value": value}},
    }


def _structural_coverage_schemas(
    *, array_target: bool = False
) -> tuple[SchemaDocument, SchemaDocument]:
    item_schema: dict[str, object] = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "string"}},
    }
    source = _schema(
        "source",
        {
            "selector": {"type": "string", "enum": ["a", "b"]},
            "lines": {"type": "array", "items": item_schema},
        },
        ["selector", "lines"],
    )
    target = (
        _array_schema("target", item_schema)
        if array_target
        else _schema(
            "target",
            {
                "out": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "string"}},
                }
            },
            ["out"],
        )
    )
    return source, target


@pytest.mark.parametrize(
    ("target_path", "array_target", "expression"),
    [
        ("/out", False, _object_expression()),
        (
            "/out",
            False,
            {
                "op": "if",
                "condition": {"op": "literal", "value": True},
                "then": _object_expression(value="a"),
                "otherwise": _object_expression(value="b"),
            },
        ),
        (
            "/out",
            False,
            {
                "op": "coalesce",
                "operands": (
                    _object_expression(value="a"),
                    _object_expression(value="b"),
                ),
            },
        ),
        (
            "/out",
            False,
            {
                "op": "lookup",
                "key": {"op": "get", "path": "/selector", "document": "input"},
                "values": {"a": {"x": "a"}, "b": {"x": "b"}},
            },
        ),
        ("/lines", True, {"op": "array", "items": (_object_expression(),)}),
        (
            "/lines",
            True,
            {
                "op": "map",
                "collection": {"op": "get", "path": "/lines", "document": "input"},
                "expression": {"op": "get", "path": "/", "document": "current"},
            },
        ),
    ],
    ids=("object", "if", "coalesce", "lookup", "array", "map"),
)
def test_structural_producers_cover_required_targets(
    target_path: str,
    array_target: bool,
    expression: dict[str, object],
) -> None:
    source, target = _structural_coverage_schemas(array_target=array_target)

    result = verify_static(
        _mapping({"target": target_path, "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def _nullable_object_lookup() -> dict[str, object]:
    return {
        "op": "lookup",
        "key": {"op": "get", "path": "/selector", "document": "input"},
        "values": {"a": {"x": "from-lookup"}},
    }


def test_coalesce_absorbs_lookup_missing_key_null_before_object_fallback() -> None:
    source, target = _structural_coverage_schemas()
    expression = {
        "op": "coalesce",
        "operands": (_nullable_object_lookup(), _object_expression(value="fallback")),
    }

    result = verify_static(
        _mapping({"target": "/out", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


def test_coalesce_ignores_unreachable_object_producers_after_non_null_operand() -> None:
    source, target = _structural_coverage_schemas()
    expression = {
        "op": "coalesce",
        "operands": (_object_expression(), _object_expression(field="y")),
    }

    result = verify_static(
        _mapping({"target": "/out", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert result.valid


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": _object_expression(),
            "otherwise": _object_expression(field="y"),
        },
        {
            "op": "coalesce",
            "operands": (_nullable_object_lookup(), _object_expression(field="y")),
        },
    ],
    ids=("if-intersection", "coalesce-reachable-intersection"),
)
def test_composite_object_coverage_requires_every_reachable_non_null_producer(
    expression: dict[str, object],
) -> None:
    source, target = _structural_coverage_schemas()

    result = verify_static(
        _mapping({"target": "/out", "expression": expression}),
        source_schema=source,
        target_schema=target,
    )

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED and issue.target_path == "/out/x"
        for issue in result.issues
    )
