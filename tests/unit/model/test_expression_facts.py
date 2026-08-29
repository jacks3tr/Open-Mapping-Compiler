"""Context-free expression traversal facts."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.model.expressions import Expression, analyze_expression


def test_expression_facts_collect_paths_documents_and_operations() -> None:
    expression: Expression = TypeAdapter(Expression).validate_python(
        {
            "op": "concat",
            "operands": [
                {"op": "get", "path": "/first", "document": "input"},
                {"op": "get", "path": "/last", "document": "current"},
            ],
        }
    )

    facts = analyze_expression(expression)

    assert facts.input_paths == frozenset({"/first"})
    assert facts.documents == frozenset({"input", "current"})
    assert facts.operations == frozenset({"concat", "get"})
    assert not facts.is_pure_constant


def test_expression_facts_recognize_computed_constants() -> None:
    expression: Expression = TypeAdapter(Expression).validate_python(
        {
            "op": "add",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 2},
        }
    )

    assert analyze_expression(expression).is_pure_constant
