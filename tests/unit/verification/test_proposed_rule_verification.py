"""Partial static-verification contract for suggested rules."""

from __future__ import annotations

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.issues import IssueCode, Severity
from open_mapping.model.mappings import MappingRule
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.static import verify_proposed_rule


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["status", "lines", "bad", "maybe", "fallback", "maybeOther"],
            "properties": {
                "status": {"type": "string", "enum": ["A", "B"]},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["sku"],
                        "properties": {"sku": {"type": "string"}},
                    },
                },
                "bad": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["wrong"],
                        "properties": {"wrong": {"type": "string"}},
                    },
                },
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
                "maybeOther": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
                "optionalA": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["partNumber"],
                        "properties": {"partNumber": {"type": "string"}},
                    },
                },
                "optionalB": {
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
            "required": ["status", "lines", "unrelated", "label"],
            "properties": {
                "status": {"type": "string", "enum": ["A"]},
                "label": {"type": "string"},
                "unrelated": {"type": "string"},
                "lines": {
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
        source_uri="target",
    )
    return source, target


def test_proposed_rule_runs_enum_check_without_unrelated_coverage_errors() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/status",
        expression={"op": "get", "path": "/status", "document": "input"},
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(issue.code == IssueCode.TYPE_MISMATCH for issue in issues)
    assert not any(issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED for issue in issues)


def test_proposed_rule_runs_nested_array_item_coverage_checks() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/lines",
        expression={
            "op": "map",
            "collection": {"op": "get", "path": "/lines", "document": "input"},
            "expression": {
                "op": "object",
                "fields": {"wrong": {"op": "get", "path": "/sku", "document": "current"}},
            },
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED
        and issue.target_path == "/lines/items/partNumber"
        for issue in issues
    )
    assert not any(issue.target_path == "/unrelated" for issue in issues)


def test_proposed_rule_preserves_cast_warnings() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/status",
        expression={
            "op": "cast",
            "target_type": "string",
            "value": {"op": "get", "path": "/status", "document": "input"},
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(issue.severity == Severity.ERROR for issue in issues)


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "get", "path": "/bad", "document": "input"},
            "otherwise": {"op": "get", "path": "/lines", "document": "input"},
        },
        {
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/bad", "document": "input"},
                {"op": "get", "path": "/lines", "document": "input"},
            ),
        },
    ],
    ids=("conditional", "coalesce"),
)
def test_proposed_rule_checks_composite_array_item_shapes(
    expression: dict[str, object],
) -> None:
    source, target = _schemas()
    rule = MappingRule(target="/lines", expression=expression)

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED
        and issue.target_path == "/lines/items/partNumber"
        for issue in issues
    )
    assert not any(issue.target_path == "/unrelated" for issue in issues)


def test_proposed_rule_accepts_nullable_structural_coalesce_with_valid_fallback() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/lines",
        expression={
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/maybe", "document": "input"},
                {"op": "get", "path": "/fallback", "document": "input"},
            ),
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert not any(issue.severity == Severity.ERROR for issue in issues)


def test_proposed_rule_rejects_all_nullable_structural_coalesce() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/lines",
        expression={
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/maybe", "document": "input"},
                {"op": "get", "path": "/maybeOther", "document": "input"},
            ),
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines" for issue in issues
    )


def test_proposed_rule_rejects_all_optional_structural_coalesce() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/lines",
        expression={
            "op": "coalesce",
            "operands": (
                {"op": "get", "path": "/optionalA", "document": "input"},
                {"op": "get", "path": "/optionalB", "document": "input"},
            ),
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines" for issue in issues
    )


def test_proposed_rule_rejects_map_over_optional_collection() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/lines",
        expression={
            "op": "map",
            "collection": {"op": "get", "path": "/optionalA", "document": "input"},
            "expression": {"op": "get", "path": "/", "document": "current"},
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/lines" for issue in issues
    )


def test_proposed_rule_rejects_non_exhaustive_scalar_lookup_without_default() -> None:
    source, target = _schemas()
    rule = MappingRule(
        target="/label",
        expression={
            "op": "lookup",
            "key": {"op": "get", "path": "/status", "document": "input"},
            "values": {"A": "Active"},
        },
    )

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/label" for issue in issues
    )


@pytest.mark.parametrize(
    "expression",
    [
        {
            "op": "if",
            "condition": {"op": "literal", "value": True},
            "then": {"op": "object", "fields": {"partNumber": {"op": "literal", "value": "a"}}},
            "otherwise": {
                "op": "object",
                "fields": {"partNumber": {"op": "literal", "value": "b"}},
            },
        },
        {
            "op": "coalesce",
            "operands": (
                {
                    "op": "lookup",
                    "key": {"op": "get", "path": "/status", "document": "input"},
                    "values": {"A": {"partNumber": "lookup"}},
                },
                {
                    "op": "object",
                    "fields": {"partNumber": {"op": "literal", "value": "fallback"}},
                },
            ),
        },
        {
            "op": "coalesce",
            "operands": (
                {
                    "op": "object",
                    "fields": {"partNumber": {"op": "literal", "value": "first"}},
                },
                {"op": "object", "fields": {"wrong": {"op": "literal", "value": "later"}}},
            ),
        },
    ],
    ids=("if-coverage", "absorbed-lookup-null", "unreachable-coalesce-operand"),
)
def test_proposed_rule_accepts_sound_composite_object_coverage(
    expression: dict[str, object],
) -> None:
    source, target = _schemas()
    rule = MappingRule(target="/lines/items", expression=expression)

    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)

    assert not any(issue.severity == Severity.ERROR for issue in issues)
