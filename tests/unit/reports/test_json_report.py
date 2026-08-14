"""Machine-readable report contracts."""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from open_mapping.model.expressions import Expression
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionOrigin,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.model.verification import (
    SampleVerificationResult,
    StaticVerificationResult,
    VerificationReport,
)
from open_mapping.reports.json_report import render_suggestions_json, render_verification_json
from open_mapping.serialization.suggestions import suggestion_report_sha256


def suggested(target_path: str) -> MappingSuggestion:
    return MappingSuggestion(
        target_path=target_path,
        confidence_band=ConfidenceBand.HIGH,
        disposition=SuggestionDisposition.SUGGESTED,
        confidence_score=0.95,
        confidence_method="heuristic-v0.1",
        selected_source_path=target_path,
        expression={"op": "get", "path": target_path, "document": "input"},
    )


def report(items: tuple[MappingSuggestion, ...]) -> SuggestionReport:
    return SuggestionReport(
        report_version="0.1",
        source_schema_id="source",
        source_schema_version="0.1",
        target_schema_id="target",
        target_schema_version="0.1",
        suggestions=items,
        summary=SuggestionSummary(total_targets=len(items), high=len(items), suggested=len(items)),
    )


def test_suggestion_json_is_deterministic_and_contains_reconciled_summary() -> None:
    value = report((suggested("/name"),))
    rendered = render_suggestions_json(value)
    assert rendered == render_suggestions_json(value)
    parsed = json.loads(rendered)
    assert parsed["summary"] == value.summary.model_dump(mode="json")
    assert parsed["suggestion_report_sha256"] == suggestion_report_sha256(value)
    assert rendered.endswith("\n")


def test_verification_json_does_not_leak_redacted_dynamic_values() -> None:
    issue = Issue(
        code=IssueCode.SOURCE_SCHEMA_VALIDATION,
        severity=Severity.ERROR,
        component="verification.dynamic",
        message="source sample has incompatible type at /quantity",
        correction="Provide a number.",
        sample_id="sample-1",
    )
    value = VerificationReport(
        mapping_id="m",
        static=StaticVerificationResult(issues=(), mapped_target_paths=(), mapping_sha256="x"),
        samples=(SampleVerificationResult(sample_id="sample-1", output=None, issues=(issue,)),),
    )
    rendered = render_verification_json(value)
    assert "secret-raw-value" not in rendered
    assert "incompatible type at /quantity" in rendered


def test_suggestion_json_discloses_model_origin_paths_reason_and_static_rejection() -> None:
    model = suggested("/name").model_copy(
        update={
            "origin": SuggestionOrigin.MODEL,
            "selected_source_path": None,
            "selected_source_paths": ("/first", "/last"),
            "expression": TypeAdapter(Expression).validate_python(
                {
                    "op": "concat",
                    "operands": [
                        {"op": "get", "path": "/first", "document": "input"},
                        {"op": "get", "path": "/last", "document": "input"},
                    ],
                    "separator": " ",
                }
            ),
            "reason": "Combine the names.",
            "issues": (
                Issue(
                    code=IssueCode.TYPE_MISMATCH,
                    severity=Severity.ERROR,
                    component="verification.static",
                    message="Static rejection detail.",
                    correction="Fix the expression.",
                    target_path="/name",
                ),
            ),
        }
    )
    parsed = json.loads(render_suggestions_json(report((model,))))
    suggestion = parsed["suggestions"][0]
    assert suggestion["origin"] == "model"
    assert suggestion["selected_source_paths"] == ["/first", "/last"]
    assert suggestion["reason"] == "Combine the names."
    assert suggestion["issues"][0]["message"] == "Static rejection detail."
