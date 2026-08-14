"""Property tests for expression immutability and deterministic ordering."""

from __future__ import annotations

from copy import deepcopy

from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.expressions import Expression

JSON_SCALARS = (
    st.none() | st.booleans() | st.integers(min_value=-1000, max_value=1000) | st.text(max_size=20)
)


@given(values=st.lists(JSON_SCALARS, max_size=20))
def test_array_expression_is_deterministic_and_does_not_mutate_input(values: list[object]) -> None:
    source = {"values": deepcopy(values), "unrelated": {"z": 1, "a": 2}}
    original = deepcopy(source)
    expression: Expression = TypeAdapter(Expression).validate_python(
        {
            "op": "map",
            "collection": {"op": "get", "path": "/values"},
            "expression": {"op": "get", "path": "", "document": "current"},
        }
    )
    first = evaluate_expression(expression, EvaluationContext(input_document=source))
    second = evaluate_expression(expression, EvaluationContext(input_document=source))
    assert semantic_json_equal(first, second)
    assert source == original


def test_object_expression_has_stable_key_and_list_order() -> None:
    expression: Expression = TypeAdapter(Expression).validate_python(
        {
            "op": "object",
            "fields": {
                "z": {"op": "literal", "value": [3, 2, 1]},
                "a": {"op": "literal", "value": [1, 2, 3]},
            },
        }
    )
    expected = {"z": [3, 2, 1], "a": [1, 2, 3]}
    assert evaluate_expression(expression, EvaluationContext(input_document={})) == expected
    assert evaluate_expression(expression, EvaluationContext(input_document={})) == expected
