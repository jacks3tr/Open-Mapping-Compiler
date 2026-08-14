"""Pointer and evaluation tests."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import EvaluationLimits
from open_mapping.model.expressions import (
    Expression,
    GetExpression,
    LiteralExpression,
    ObjectExpression,
)
from open_mapping.model.invariants import Invariant
from open_mapping.pointers import (
    assign_pointer,
    escape_pointer_token,
    resolve_pointer,
    split_pointer,
)


def test_pointer_round_trip() -> None:
    assert split_pointer("/a~1b/c~0d") == ("a/b", "c~d")
    assert escape_pointer_token("a/b~c") == "a~1b~0c"


def test_pointer_resolve_and_assign() -> None:
    doc: dict[str, object] = {"a": {"b": [1, 2]}}
    assert resolve_pointer(doc, "/a/b/1") == 2
    result = assign_pointer(doc, "/x/y", 3)
    assert doc == {"a": {"b": [1, 2]}}
    assert result["x"] == {"y": 3}


def test_pointer_errors() -> None:
    with pytest.raises(OpenMappingError):
        resolve_pointer({"a": 1}, "/b")
    with pytest.raises(OpenMappingError):
        assign_pointer({}, "/0", 1)


def test_minimal_evaluator() -> None:
    expr = ObjectExpression(
        op="object",
        fields={
            "name": GetExpression(op="get", path="/name", document="input"),
            "fixed": LiteralExpression(op="literal", value=1),
        },
    )
    result = evaluate_expression(expr, EvaluationContext(input_document={"name": "x"}))
    assert result == {"name": "x", "fixed": 1}


def test_invariant_equals() -> None:
    invariant = Invariant(
        id="check",
        assertion={
            "op": "equals",
            "left": {"op": "get", "path": "/a", "document": "output"},
            "right": {"op": "literal", "value": 1},
        },
    )
    assert evaluate_invariant(invariant, input_document={}, output_document={"a": 1}) == ()
    assert evaluate_invariant(invariant, input_document={}, output_document={"a": 2}) != ()


def test_limits() -> None:
    limits = EvaluationLimits(
        max_expression_depth=1, max_array_items=1, max_output_nodes=2, max_string_length=3
    )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            TypeAdapter(Expression).validate_python(
                {
                    "op": "array",
                    "items": [{"op": "literal", "value": 1}, {"op": "literal", "value": 2}],
                }
            ),
            EvaluationContext(input_document={}),
            limits,
        )
