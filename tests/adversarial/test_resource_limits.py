"""Evaluator resource and scalar boundaries fail closed."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.numbers import MAX_SAFE_INTEGER
from open_mapping.model.expressions import Expression
from open_mapping.model.json_types import JsonValue


def _expression(value: object) -> Expression:
    return TypeAdapter(Expression).validate_python(value)


def _error_code(expression: Expression, source: JsonValue = None) -> str:
    with pytest.raises(OpenMappingError) as captured:
        evaluate_expression(expression, EvaluationContext(input_document=source))
    return captured.value.issues[0].code.value


def test_expression_depth_is_bounded() -> None:
    raw: object = {"op": "literal", "value": True}
    for _ in range(66):
        raw = {"op": "not", "value": raw}
    assert _error_code(_expression(raw), {}) == "EVALUATION_LIMIT_EXCEEDED"


def test_map_rejects_ten_thousand_and_one_items() -> None:
    expression = _expression(
        {
            "op": "map",
            "collection": {"op": "get", "path": "/items"},
            "expression": {"op": "get", "path": "", "document": "current"},
        }
    )
    assert _error_code(expression, {"items": [None] * 10_001}) == "EVALUATION_LIMIT_EXCEEDED"


def test_total_output_string_length_is_bounded() -> None:
    expression = _expression({"op": "literal", "value": "x" * 1_000_001})
    assert _error_code(expression, {}) == "EVALUATION_LIMIT_EXCEEDED"


def test_unsafe_integer_is_rejected() -> None:
    expression = _expression(
        {
            "op": "add",
            "left": {"op": "literal", "value": MAX_SAFE_INTEGER + 1},
            "right": {"op": "literal", "value": 0},
        }
    )
    assert _error_code(expression, {}) == "NUMERIC_PRECISION_RISK"


def test_divide_by_zero_has_stable_error_code() -> None:
    expression = _expression(
        {
            "op": "divide",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 0},
        }
    )
    assert _error_code(expression, {}) == "DIVIDE_BY_ZERO"


@pytest.mark.parametrize("value", ["2026-02-30T12:00:00Z", "2026-08-12T12:00:00"])
def test_invalid_or_timezone_free_dates_are_rejected(value: str) -> None:
    expression = _expression({"op": "parse_date", "value": {"op": "literal", "value": value}})
    assert _error_code(expression, {}) == "INVALID_DATE"
