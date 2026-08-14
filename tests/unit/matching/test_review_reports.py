"""Review and report rendering tests."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import (
    SampleVerificationResult,
    StaticVerificationResult,
    VerificationReport,
)
from open_mapping.reports.markdown_report import (
    render_review_markdown,
    render_verification_markdown,
)
from open_mapping.reports.text_report import render_review_text, render_verification_text
from open_mapping.serialization.suggestions import suggestion_report_sha256


def _fixture() -> tuple[SchemaDocument, SchemaDocument, SuggestionReport]:
    source = parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="t",
    )
    sets = generate_candidates(
        source,
        target,
        source_profiles=(),
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=5,
    )
    report = build_deterministic_suggestions(source, target, candidate_sets=sets, hints=None)
    return source, target, report


def test_review_accept_and_defer() -> None:
    source, target, report = _fixture()
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report),
        mapping_id="m",
        decisions=(
            SuggestionReviewDecision(
                target_path="/a", action=ReviewAction.ACCEPT_SELECTED, reason="ok"
            ),
        ),
    )
    result = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=True,
    )
    assert result.mapping is not None
    text = render_review_text(result)
    markdown = render_review_markdown(result)
    assert "/a" in text
    assert "/a" in markdown


def test_stale_review_rejected() -> None:
    source, target, report = _fixture()
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256="wrong",
        mapping_id="m",
        decisions=(),
    )
    result = assemble_mapping(
        report,
        mapping_id="m",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=False,
    )
    assert result.mapping is None


def test_verification_text_render() -> None:
    report = VerificationReport(
        mapping_id="m",
        static=StaticVerificationResult(issues=(), mapped_target_paths=(), mapping_sha256="x"),
        samples=(SampleVerificationResult(sample_id="a", output=None, issues=()),),
    )
    assert "Static valid" in render_verification_text(report)
    assert "Static valid" in render_verification_markdown(report)
