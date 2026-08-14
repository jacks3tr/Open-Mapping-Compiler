"""Evaluator, invariant, and verification report error tests."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import EvaluationLimits
from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.verification import StaticVerificationResult, VerificationReport
from open_mapping.reports.markdown_report import render_verification_markdown
from open_mapping.reports.text_report import render_verification_text


def _expr(value: dict[str, object]) -> Expression:
    return TypeAdapter(Expression).validate_python(value)


def test_evaluation_error_paths() -> None:
    context = EvaluationContext(input_document={})
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "add",
                    "left": {"op": "literal", "value": float("inf")},
                    "right": {"op": "literal", "value": 1},
                }
            ),
            context,
        )
    assert (
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": True}, "target_type": "boolean"}
            ),
            context,
        )
        is True
    )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "cast",
                    "value": {"op": "literal", "value": "999999999999999999999999"},
                    "target_type": "integer",
                }
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": "abc"}, "target_type": "number"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "cast", "value": {"op": "literal", "value": []}, "target_type": "number"}),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {"op": "cast", "value": {"op": "literal", "value": 10**30}, "target_type": "number"}
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "map",
                    "collection": {"op": "get", "path": "/arr"},
                    "expression": {"op": "literal", "value": 1},
                }
            ),
            EvaluationContext(input_document={"arr": [1, 2]}),
            EvaluationLimits(max_array_items=1),
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "coalesce",
                    "operands": [
                        {
                            "op": "cast",
                            "value": {"op": "literal", "value": []},
                            "target_type": "string",
                        }
                    ],
                }
            ),
            context,
        )
    assert (
        evaluate_expression(
            _expr(
                {
                    "op": "subtract",
                    "left": {"op": "literal", "value": 3},
                    "right": {"op": "literal", "value": 1},
                }
            ),
            context,
        )
        == 2
    )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr(
                {
                    "op": "add",
                    "left": {"op": "literal", "value": 1e308},
                    "right": {"op": "literal", "value": 1e308},
                }
            ),
            context,
        )
    with pytest.raises(OpenMappingError):
        evaluate_expression(
            _expr({"op": "round", "value": {"op": "literal", "value": 1e308}}), context
        )


def test_invariant_error_paths() -> None:
    for op in ("greater_than_or_equal", "less_than", "less_than_or_equal"):
        assert isinstance(
            evaluate_invariant(
                Invariant(
                    id="i",
                    assertion={
                        "op": op,
                        "left": {"op": "literal", "value": 1},
                        "right": {"op": "literal", "value": 2},
                    },
                ),
                input_document={},
                output_document={},
            ),
            tuple,
        )
    assert isinstance(
        evaluate_invariant(
            Invariant(
                id="i",
                when={"op": "get", "path": "/missing", "document": "input"},
                assertion={"op": "not_null", "value": {"op": "literal", "value": 1}},
            ),
            input_document={},
            output_document={},
        ),
        tuple,
    )
    assert isinstance(
        evaluate_invariant(
            Invariant(
                id="i",
                assertion={
                    "op": "greater_than",
                    "left": {"op": "literal", "value": float("nan")},
                    "right": {"op": "literal", "value": 1},
                },
            ),
            input_document={},
            output_document={},
        ),
        tuple,
    )
    assert isinstance(
        evaluate_invariant(
            Invariant(
                id="i",
                assertion={
                    "op": "length_equals",
                    "value": {"op": "literal", "value": [1, 2]},
                    "expected": 2,
                },
            ),
            input_document={},
            output_document={},
        ),
        tuple,
    )
    assert isinstance(
        evaluate_invariant(
            Invariant(
                id="i",
                assertion={
                    "op": "length_equals",
                    "value": {"op": "literal", "value": {"a": 1}},
                    "expected": 1,
                },
            ),
            input_document={},
            output_document={},
        ),
        tuple,
    )


def test_verification_report_formats() -> None:
    issue = Issue(
        code=IssueCode.SOURCE_PATH_NOT_FOUND,
        severity=Severity.ERROR,
        component="x",
        message="m",
        correction="c",
    )
    report = VerificationReport(
        mapping_id="m",
        static=StaticVerificationResult(
            issues=(issue,), mapped_target_paths=(), mapping_sha256="x"
        ),
        samples=(),
    )
    assert "SOURCE_PATH_NOT_FOUND" in render_verification_text(report)
    assert "SOURCE_PATH_NOT_FOUND" in render_verification_markdown(report)
