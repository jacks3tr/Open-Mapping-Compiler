"""Invariant evaluation."""

from __future__ import annotations

import re

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.model.invariants import Invariant
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue


def _issue(message: str, correction: str, *, target_path: str | None = None) -> Issue:
    return Issue(
        code=IssueCode.INVARIANT_FAILED,
        severity=Severity.ERROR,
        component="evaluation.invariants",
        message=message,
        correction=correction,
        target_path=target_path,
    )


def _numeric(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric comparison requires numbers")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("numeric comparison rejects non-finite values")
    return result


def evaluate_invariant(
    invariant: Invariant,
    *,
    input_document: JsonValue,
    output_document: JsonValue,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
) -> tuple[Issue, ...]:
    context = EvaluationContext(input_document=input_document, output_document=output_document)
    if invariant.when is not None:
        try:
            condition = evaluate_expression(invariant.when, context, limits)
        except OpenMappingError as exc:
            return tuple(
                _issue(
                    f"invariant {invariant.id!r} when-condition failed",
                    "Fix the invariant condition.",
                )
                for _ in exc.issues
            )
        if not isinstance(condition, bool) or not condition:
            return ()
    try:
        assertion = invariant.assertion
        op = getattr(assertion, "op")
        if op == "equals":
            left = evaluate_expression(getattr(assertion, "left"), context, limits)
            right = evaluate_expression(getattr(assertion, "right"), context, limits)
            ok = semantic_json_equal(left, right)
        elif op == "not_null":
            value = evaluate_expression(getattr(assertion, "value"), context, limits)
            ok = value is not None
        elif op == "in":
            value = evaluate_expression(getattr(assertion, "value"), context, limits)
            ok = any(semantic_json_equal(value, item) for item in getattr(assertion, "allowed"))
        elif op == "matches":
            value = evaluate_expression(getattr(assertion, "value"), context, limits)
            if not isinstance(value, str):
                raise ValueError("matches requires a string")
            ok = re.fullmatch(getattr(assertion, "pattern"), value) is not None
        elif op in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
            left = _numeric(evaluate_expression(getattr(assertion, "left"), context, limits))
            right = _numeric(evaluate_expression(getattr(assertion, "right"), context, limits))
            if op == "greater_than":
                ok = left > right
            elif op == "greater_than_or_equal":
                ok = left >= right
            elif op == "less_than":
                ok = left < right
            else:
                ok = left <= right
        elif op == "unique":
            value = evaluate_expression(getattr(assertion, "value"), context, limits)
            if not isinstance(value, list):
                raise ValueError("unique requires an array")
            ok = all(
                not semantic_json_equal(value[left_index], value[right_index])
                for left_index in range(len(value))
                for right_index in range(left_index + 1, len(value))
            )
        elif op == "length_equals":
            value = evaluate_expression(getattr(assertion, "value"), context, limits)
            if isinstance(value, str):
                length = len(value)
            elif isinstance(value, list):
                length = len(value)
            elif isinstance(value, dict):
                length = len(value)
            else:
                raise ValueError("length_equals supports strings, arrays, and objects")
            ok = length == getattr(assertion, "expected")
        else:
            return (
                _issue(f"unsupported invariant assertion {op!r}", "Use a supported assertion."),
            )
        return (
            ()
            if ok
            else (
                _issue(
                    f"invariant {invariant.id!r} failed",
                    "Correct the source data or mapping so the invariant holds.",
                ),
            )
        )
    except (ValueError, OpenMappingError):
        return (
            _issue(
                f"invariant {invariant.id!r} could not be evaluated",
                "Fix the invariant expression or source data.",
            ),
        )
