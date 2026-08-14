"""Property and table tests for the shared JSON number contract."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.numbers import MAX_SAFE_INTEGER, round_half_away_from_zero
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant


def _cast(value: object, target_type: str) -> object:
    expression: Expression = TypeAdapter(Expression).validate_python(
        {"op": "cast", "value": {"op": "literal", "value": value}, "target_type": target_type}
    )
    return evaluate_expression(expression, EvaluationContext(input_document={}))


@pytest.mark.parametrize(
    "value",
    ["", " ", "\t1", "1 ", "0x10", "0b10", "0o10", "Infinity", "-Infinity", "NaN", "1_000"],
)
def test_number_cast_rejects_non_decimal_string_forms(value: str) -> None:
    with pytest.raises(OpenMappingError) as captured:
        _cast(value, "number")
    assert captured.value.issues[0].code.value == "TYPE_MISMATCH"


@pytest.mark.parametrize("value", ["0", "-0", "+12", "1.25", ".5", "1.", "1e3", "-2.5E-2"])
def test_number_cast_accepts_strict_decimal_grammar(value: str) -> None:
    result = _cast(value, "number")
    assert isinstance(result, (int, float)) and not isinstance(result, bool)
    assert math.isfinite(float(result))


@pytest.mark.parametrize("value", ["1.0", "1e2", " 1", "1 ", "0x10", "1_0", "+", "-"])
def test_integer_cast_requires_whole_base_ten_string(value: str) -> None:
    with pytest.raises(OpenMappingError) as captured:
        _cast(value, "integer")
    assert captured.value.issues[0].code.value == "TYPE_MISMATCH"


@pytest.mark.parametrize("value", [str(MAX_SAFE_INTEGER + 1), str(-MAX_SAFE_INTEGER - 1)])
def test_integer_cast_enforces_javascript_safe_range(value: str) -> None:
    with pytest.raises(OpenMappingError) as captured:
        _cast(value, "integer")
    assert captured.value.issues[0].code.value == "NUMERIC_PRECISION_RISK"


def test_semantic_json_equality_uses_json_number_values_not_serializer_spelling() -> None:
    assert semantic_json_equal(1, 1.0)
    assert semantic_json_equal({"b": [2.0], "a": 1}, {"a": 1.0, "b": [2]})
    assert not semantic_json_equal(True, 1)
    assert not semantic_json_equal([1, 2], [2, 1])


def test_semantic_json_equality_rejects_huge_integer_without_overflow() -> None:
    with pytest.raises(ValueError, match="safe integer"):
        semantic_json_equal(10**400, 10**400)


def test_invariant_equality_membership_and_uniqueness_use_semantic_number_equality() -> None:
    def issues(assertion: dict[str, object]) -> tuple[object, ...]:
        return evaluate_invariant(
            Invariant(id="semantic-number", assertion=assertion),
            input_document={},
            output_document={},
        )

    assert not issues(
        {
            "op": "equals",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 1.0},
        }
    )
    assert not issues({"op": "in", "value": {"op": "literal", "value": 1}, "allowed": [1.0]})
    assert issues({"op": "unique", "value": {"op": "literal", "value": [1, 1.0]}})


@given(
    value=st.floats(
        min_value=-1_000_000,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    digits=st.integers(min_value=0, max_value=6),
)
def test_round_half_away_from_zero_is_finite_and_sign_symmetric(value: float, digits: int) -> None:
    positive = round_half_away_from_zero(abs(value), digits)
    negative = round_half_away_from_zero(-abs(value), digits)
    assert math.isfinite(float(positive))
    assert float(negative) == -float(positive)
