"""Evaluator and invariant edge cases."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import EvaluationLimits
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant


def _expr(value: dict[str, object]) -> Expression:
    return TypeAdapter(Expression).validate_python(value)


def test_cast_branches() -> None:
    context = EvaluationContext(input_document={})
    assert (
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": None}, "target_type": "string"}
            ),
            context,
        )
        == "null"
    )
    assert (
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": True}, "target_type": "string"}
            ),
            context,
        )
        == "true"
    )
    assert (
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": 1.0}, "target_type": "string"}
            ),
            context,
        )
        == "1"
    )
    assert (
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": "1.5"}, "target_type": "number"}
            ),
            context,
        )
        == 1.5
    )
    assert (
        evaluate_expression(
            _expr({"op": "cast", "value": {"op": "literal", "value": 3}, "target_type": "number"}),
            context,
        )
        == 3
    )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": True}, "target_type": "integer"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": "nan"}, "target_type": "number"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": True}, "target_type": "number"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "cast",
                    "value": {"op": "literal", "value": 10**30},
                    "target_type": "integer",
                }
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "cast", "value": {"op": "literal", "value": []}, "target_type": "string"}),
            context,
        )


def test_numeric_and_limit_branches() -> None:
    context = EvaluationContext(input_document={})
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "add",
                    "left": {"op": "literal", "value": True},
                    "right": {"op": "literal", "value": 1},
                }
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "add",
                    "left": {"op": "literal", "value": 10**20},
                    "right": {"op": "literal", "value": 1},
                }
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "round", "value": {"op": "literal", "value": 10**20}}), context
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "map",
                    "collection": {
                        "op": "array",
                        "items": [{"op": "literal", "value": 1}, {"op": "literal", "value": 2}],
                    },
                    "expression": {"op": "literal", "value": 1},
                }
            ),
            context,
            EvaluationLimits(max_array_items=1),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "literal", "value": {"a": 1}}),
            context,
            EvaluationLimits(max_output_nodes=1),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "object",
                    "fields": {
                        "x": {"op": "object", "fields": {"y": {"op": "literal", "value": 1}}}
                    },
                }
            ),
            context,
            EvaluationLimits(max_expression_depth=1),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "format_date", "value": {"op": "literal", "value": 1}, "pattern": "YYYY"}),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "format_date", "value": {"op": "literal", "value": "bad"}, "pattern": "YYYY"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "parse_date", "value": {"op": "literal", "value": "bad"}}), context
        )


def test_invariant_remaining_branches() -> None:
    assert evaluate_invariant(
        Invariant(
            id="i",
            when={"op": "get", "path": "/missing", "document": "input"},
            assertion={"op": "not_null", "value": {"op": "literal", "value": 1}},
        ),
        input_document={},
        output_document={},
    )
    assert evaluate_invariant(
        Invariant(
            id="i",
            assertion={
                "op": "length_equals",
                "value": {"op": "literal", "value": 1},
                "expected": 1,
            },
        ),
        input_document={},
        output_document={},
    )
    assert evaluate_invariant(
        Invariant(
            id="i",
            assertion={"op": "unique", "value": {"op": "literal", "value": [{"a": 1}, {"a": 1}]}},
        ),
        input_document={},
        output_document={},
    )
