"""Core model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_mapping.model.expressions import GetExpression, LiteralExpression
from open_mapping.model.issues import Issue, IssueCode, Severity, has_errors, sort_issues
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
)
from open_mapping.model.verification import StaticVerificationResult


def _issue(code: IssueCode = IssueCode.INVALID_INPUT, message: str = "m") -> Issue:
    return Issue(
        code=code,
        severity=Severity.ERROR,
        component="test",
        message=message,
        correction="fix",
    )


def test_issue_sort_is_deterministic() -> None:
    first = _issue(IssueCode.TYPE_MISMATCH, "a")
    second = _issue(IssueCode.INVALID_INPUT, "b")
    assert sort_issues([second, first]) == sort_issues([first, second])
    assert has_errors((first, second))
    assert not has_errors((first.model_copy(update={"severity": Severity.INFO}),))


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StaticVerificationResult.model_validate(
            {
                "issues": (),
                "mapped_target_paths": (),
                "mapping_sha256": "x",
                "unexpected": True,
            }
        )


def test_expression_validation() -> None:
    with pytest.raises(ValidationError):
        LiteralExpression.model_validate({"op": "unknown", "value": 1})
    with pytest.raises(ValidationError):
        GetExpression.model_validate({"op": "unknown", "path": "/x"})


def test_suggestion_invariants() -> None:
    with pytest.raises(ValidationError):
        MappingSuggestion.model_validate(
            {
                "target_path": "/x",
                "confidence_band": ConfidenceBand.NONE,
                "disposition": SuggestionDisposition.NO_MATCH,
                "expression": {"op": "literal", "value": 1},
            }
        )
    valid = MappingSuggestion.model_validate(
        {
            "target_path": "/x",
            "confidence_band": ConfidenceBand.NONE,
            "disposition": SuggestionDisposition.NO_MATCH,
            "confidence_method": "heuristic-v0.1",
        }
    )
    assert valid.expression is None
