"""Expression operation tests."""

from __future__ import annotations

from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant


def _evaluate(
    expression: dict[str, object], input_doc: object | None = None, output_doc: object | None = None
) -> object:
    parsed: Expression = TypeAdapter(Expression).validate_python(expression)
    return evaluate_expression(
        parsed,
        EvaluationContext(
            input_document=input_doc if input_doc is not None else {},
            output_document=output_doc if output_doc is not None else {},
        ),
    )


def test_object_array_map() -> None:
    result = _evaluate(
        {
            "op": "map",
            "collection": {
                "op": "array",
                "items": [{"op": "literal", "value": 1}, {"op": "literal", "value": 2}],
            },
            "expression": {
                "op": "multiply",
                "left": {"op": "get", "path": "", "document": "current"},
                "right": {"op": "literal", "value": 10},
            },
        }
    )
    assert result == [10, 20]


def test_casts() -> None:
    assert (
        _evaluate(
            {"op": "cast", "value": {"op": "literal", "value": "12"}, "target_type": "integer"}
        )
        == 12
    )
    assert (
        _evaluate(
            {"op": "cast", "value": {"op": "literal", "value": "TRUE"}, "target_type": "boolean"}
        )
        is True
    )
    assert (
        _evaluate({"op": "cast", "value": {"op": "literal", "value": 1}, "target_type": "string"})
        == "1"
    )


def test_boolean_and_conditional() -> None:
    assert (
        _evaluate(
            {
                "op": "equals",
                "left": {"op": "literal", "value": 1},
                "right": {"op": "literal", "value": 1},
            }
        )
        is True
    )
    assert _evaluate({"op": "not", "value": {"op": "literal", "value": False}}) is True
    assert (
        _evaluate(
            {
                "op": "and",
                "operands": [{"op": "literal", "value": True}, {"op": "literal", "value": True}],
            }
        )
        is True
    )
    assert (
        _evaluate(
            {
                "op": "if",
                "condition": {"op": "literal", "value": True},
                "then": {"op": "literal", "value": "a"},
                "otherwise": {"op": "literal", "value": "b"},
            }
        )
        == "a"
    )


def test_lookup_concat_coalesce() -> None:
    assert (
        _evaluate(
            {
                "op": "lookup",
                "key": {"op": "literal", "value": "A"},
                "values": {"A": 1},
                "default": {"op": "literal", "value": 0},
            }
        )
        == 1
    )
    assert (
        _evaluate(
            {
                "op": "concat",
                "operands": [{"op": "literal", "value": "a"}, {"op": "literal", "value": "b"}],
                "separator": "-",
            }
        )
        == "a-b"
    )
    assert (
        _evaluate(
            {
                "op": "coalesce",
                "operands": [
                    {"op": "get", "path": "/missing"},
                    {"op": "literal", "value": "fallback"},
                ],
            }
        )
        == "fallback"
    )


def test_numeric_and_round() -> None:
    assert (
        _evaluate(
            {
                "op": "add",
                "left": {"op": "literal", "value": 1},
                "right": {"op": "literal", "value": 2},
            }
        )
        == 3
    )
    assert (
        _evaluate(
            {
                "op": "divide",
                "left": {"op": "literal", "value": 7},
                "right": {"op": "literal", "value": 2},
            }
        )
        == 3.5
    )
    assert _evaluate({"op": "round", "value": {"op": "literal", "value": 2.5}, "digits": 0}) == 3


def test_dates() -> None:
    assert (
        _evaluate(
            {
                "op": "format_date",
                "value": {
                    "op": "parse_date",
                    "value": {"op": "literal", "value": "2026-08-11T08:30:00-04:00"},
                },
                "pattern": "YYYY-MM-DDThh:mm:ss.SSSZ",
            }
        )
        == "2026-08-11T12:30:00.000Z"
    )


def test_invariant_assertions() -> None:
    def run(assertion: dict[str, object]) -> bool:
        invariant = Invariant(id="i", assertion=assertion)
        return not evaluate_invariant(invariant, input_document={}, output_document={})

    assert run({"op": "not_null", "value": {"op": "literal", "value": 1}})
    assert run({"op": "in", "value": {"op": "literal", "value": 1}, "allowed": [1, 2]})
    assert run({"op": "matches", "value": {"op": "literal", "value": "abc"}, "pattern": "a.*"})
    assert run(
        {
            "op": "greater_than",
            "left": {"op": "literal", "value": 2},
            "right": {"op": "literal", "value": 1},
        }
    )
    assert run({"op": "length_equals", "value": {"op": "literal", "value": "abc"}, "expected": 3})
    assert run({"op": "unique", "value": {"op": "literal", "value": [1, 2]}})


def test_errors() -> None:
    expressions: tuple[dict[str, object], ...] = (
        {
            "op": "divide",
            "left": {"op": "literal", "value": 1},
            "right": {"op": "literal", "value": 0},
        },
        {
            "op": "if",
            "condition": {"op": "literal", "value": 1},
            "then": {"op": "literal", "value": 1},
            "otherwise": {"op": "literal", "value": 2},
        },
        {"op": "parse_date", "value": {"op": "literal", "value": "2026-01-01"}},
    )
    for expression in expressions:
        try:
            _evaluate(expression)
        except OpenMappingError:
            pass
        else:
            raise AssertionError(f"expected error for {expression}")
