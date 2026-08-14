"""Model proposal reconciliation contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.proposals import (
    apply_model_mapping_responses,
    build_deterministic_suggestions,
)
from open_mapping.model.hints import ConstantHint, MappingHints
from open_mapping.model.issues import IssueCode
from open_mapping.model.model_config import ContextMode, ProviderKind
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelProposalAction,
    ModelTargetProposal,
    ModelTargetRequest,
    mapping_context_sha256,
)
from open_mapping.model.providers import ModelBatchRun, ModelRunDisclosure, ModelUsage
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    MatchCandidate,
    SuggestionDisposition,
    SuggestionOrigin,
    SuggestionReport,
    TargetCandidateSet,
)
from open_mapping.serialization.suggestions import load_suggestion_report


def _schemas(
    targets: dict[str, object] | None = None,
) -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["first", "last", "status", "tags"],
            "properties": {
                "first": {"type": "string"},
                "last": {"type": "string"},
                "status": {"type": "string", "enum": ["A", "I"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target_properties = targets or {"value": {"type": "string"}}
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": list(target_properties),
            "properties": target_properties,
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


def _candidate_set(
    target_path: str,
    candidates: Sequence[tuple[str, float]] = (("/first", 0.95), ("/last", 0.75)),
) -> TargetCandidateSet:
    return TargetCandidateSet(
        target_path=target_path,
        candidates=tuple(
            MatchCandidate(source_path=source_path, target_path=target_path, raw_score=score)
            for source_path, score in candidates
        ),
    )


def _baseline(
    source: SchemaDocument,
    target: SchemaDocument,
    *,
    candidate_sets: Sequence[TargetCandidateSet],
    hints: MappingHints | None = None,
) -> SuggestionReport:
    return build_deterministic_suggestions(
        source,
        target,
        candidate_sets=candidate_sets,
        hints=hints,
    )


def _field_summary(schema: SchemaDocument, pointer: str) -> ModelFieldSummary:
    field = schema.field(pointer)
    assert field is not None
    return ModelFieldSummary(
        pointer=pointer,
        types=tuple(item.value for item in field.types),
        required=field.required,
        title=field.title,
        description=field.description,
        enum_values=field.enum_values,
        item_types=tuple(item.value for item in field.item_types),
        constraints={},
    )


def _package(
    source: SchemaDocument,
    target: SchemaDocument,
    candidate_sets: Sequence[TargetCandidateSet],
    *,
    batch_id: str = "batch-001",
) -> MappingContextPackage:
    source_paths = ("/first", "/last", "/status", "/tags")
    return MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id=batch_id,
        context_mode=ContextMode.TARGETED,
        source_schema_id=source.schema_id,
        source_schema_version=source.schema_version,
        target_schema_id=target.schema_id,
        target_schema_version=target.schema_version,
        source_fields=tuple(_field_summary(source, path) for path in source_paths),
        target_requests=tuple(
            ModelTargetRequest(
                target=_field_summary(target, item.target_path),
                candidates=tuple(
                    ModelCandidateSummary(
                        source_path=candidate.source_path,
                        raw_score=candidate.raw_score,
                        evidence=(),
                    )
                    for candidate in item.candidates
                ),
            )
            for item in candidate_sets
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=(
            "get",
            "literal",
            "array",
            "concat",
            "lookup",
        ),
        allowed_source_paths=source_paths,
        raw_samples=None,
    )


def _response(
    package: MappingContextPackage,
    proposals: Sequence[ModelTargetProposal],
) -> ModelMappingResponse:
    return ModelMappingResponse(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        context_sha256=mapping_context_sha256(package),
        batch_id=package.batch_id,
        proposals=tuple(proposals),
    )


def _proposal(
    target_path: str,
    *,
    expression: object | None,
    paths: tuple[str, ...],
    reason: str = "Model proposal reason.",
) -> ModelTargetProposal:
    return ModelTargetProposal.model_validate(
        {
            "target_path": target_path,
            "action": "propose",
            "selected_source_paths": paths,
            "expression": expression,
            "reason": reason,
            "evidence": ["Model evidence."],
        }
    )


def _disclosure(
    package: MappingContextPackage,
    response: ModelMappingResponse,
) -> ModelRunDisclosure:
    return ModelRunDisclosure(
        model_alias="mapping-model",
        provider_name="local",
        provider_kind=ProviderKind.CUSTOM_HTTP,
        model_id="model-1",
        prompt_version="mapping-agent-v1",
        config_sha256="a" * 64,
        context_mode=ContextMode.TARGETED,
        raw_samples_included=False,
        redaction_count=0,
        batch_runs=(
            ModelBatchRun(
                batch_id=package.batch_id,
                context_sha256=mapping_context_sha256(package),
                response_sha256="b" * 64,
                response=response,
                issues=(),
                attempts=1,
                format_repairs=0,
                usage=ModelUsage(input_tokens=10, output_tokens=5),
                latency_ms=1,
            ),
        ),
    )


def _apply(
    baseline: SuggestionReport,
    source: SchemaDocument,
    target: SchemaDocument,
    package: MappingContextPackage,
    response: ModelMappingResponse,
) -> SuggestionReport:
    return apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(package,),
        responses=(response,),
        disclosure=_disclosure(package, response),
    )


def _only(report: SuggestionReport) -> MappingSuggestion:
    assert len(report.suggestions) == 1
    return report.suggestions[0]


def test_model_confirmation_retains_deterministic_direct_outcome() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/first", "document": "input"},
                paths=("/first",),
            ),
        ),
    )

    result = _apply(baseline, source, target, package, response)

    suggestion = _only(result)
    assert suggestion.confidence_band == _only(baseline).confidence_band
    assert suggestion.confidence_score == _only(baseline).confidence_score
    assert suggestion.disposition == _only(baseline).disposition
    assert suggestion.origin == SuggestionOrigin.DETERMINISTIC
    assert suggestion.selected_source_path == "/first"
    assert suggestion.selected_source_paths == ("/first",)
    assert any("Model" in evidence.detail for evidence in suggestion.evidence)
    assert result.model_run_disclosure == _disclosure(package, response)


def test_model_selected_existing_alternative_retains_candidate_band_and_requires_review() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/last", "document": "input"},
                paths=("/last",),
            ),
        ),
    )

    suggestion = _only(_apply(baseline, source, target, package, response))

    assert suggestion.confidence_band == ConfidenceBand.MEDIUM
    assert suggestion.confidence_score == 0.75
    assert suggestion.confidence_method == "heuristic-v0.1"
    assert suggestion.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert suggestion.origin == SuggestionOrigin.MODEL
    assert suggestion.selected_source_path == "/last"
    assert suggestion.selected_source_paths == ("/last",)


@pytest.mark.parametrize(
    ("expression", "paths"),
    [
        (
            {
                "op": "lookup",
                "key": {"op": "get", "path": "/status", "document": "input"},
                "values": {"A": "Active", "I": "Inactive"},
            },
            ("/status",),
        ),
        (
            {
                "op": "concat",
                "operands": [
                    {"op": "get", "path": "/first", "document": "input"},
                    {"op": "get", "path": "/last", "document": "input"},
                ],
                "separator": " ",
            },
            ("/first", "/last"),
        ),
        ({"op": "literal", "value": "US"}, ()),
    ],
    ids=("lookup", "multi-source-concat", "constant"),
)
def test_complex_and_constant_model_expressions_are_unscored_review_drafts(
    expression: object,
    paths: tuple[str, ...],
) -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(package, (_proposal("/value", expression=expression, paths=paths),))

    suggestion = _only(_apply(baseline, source, target, package, response))

    assert suggestion.confidence_band == ConfidenceBand.NONE
    assert suggestion.confidence_score is None
    assert suggestion.confidence_method == "model-proposal-v0.1"
    assert suggestion.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert suggestion.origin == SuggestionOrigin.MODEL
    assert suggestion.selected_source_path == (paths[0] if len(paths) == 1 else None)
    assert suggestion.selected_source_paths == paths


def test_model_array_expression_is_preserved_for_review() -> None:
    source, target = _schemas({"value": {"type": "array", "items": {"type": "string"}}})
    candidates = (_candidate_set("/value", (("/tags", 0.8),)),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={
                    "op": "array",
                    "items": [{"op": "get", "path": "/first", "document": "input"}],
                },
                paths=("/first",),
            ),
        ),
    )

    suggestion = _only(_apply(baseline, source, target, package, response))

    assert suggestion.origin == SuggestionOrigin.MODEL
    assert suggestion.expression is not None
    assert suggestion.expression.op == "array"
    assert suggestion.disposition == SuggestionDisposition.REVIEW_REQUIRED


def test_model_abstention_keeps_baseline_and_appends_bounded_evidence() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            ModelTargetProposal(
                target_path="/value",
                action=ModelProposalAction.ABSTAIN,
                selected_source_paths=(),
                expression=None,
                reason="Insufficient semantic evidence.",
                evidence=("No reliable distinction.",),
            ),
        ),
    )

    suggestion = _only(_apply(baseline, source, target, package, response))

    baseline_suggestion = _only(baseline)
    assert (
        suggestion.model_copy(update={"evidence": baseline_suggestion.evidence})
        == baseline_suggestion
    )
    assert len(suggestion.evidence[-1].detail) <= 300
    assert "abstained" in suggestion.evidence[-1].detail.lower()


def test_invalid_source_authority_leaves_baseline_and_adds_stable_warning() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/outside", "document": "input"},
                paths=("/outside",),
            ),
        ),
    )

    result = _apply(baseline, source, target, package, response)

    assert result.suggestions == baseline.suggestions
    assert any(
        issue.code == IssueCode.PROVIDER_RESPONSE_INVALID and issue.severity.value == "warning"
        for issue in result.issues
    )


def test_static_invalid_expression_leaves_outcome_and_discloses_rejection_issues() -> None:
    source, target = _schemas({"value": {"type": "integer"}})
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/first", "document": "input"},
                paths=("/first",),
            ),
        ),
    )

    result = _apply(baseline, source, target, package, response)

    assert result.suggestions == baseline.suggestions
    assert any(issue.code == IssueCode.TYPE_MISMATCH for issue in result.issues)
    assert any(issue.code == IssueCode.PROVIDER_RESPONSE_INVALID for issue in result.issues)


def test_manual_hint_outcome_is_immutable_under_model_proposal() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    hints = MappingHints(
        hints_version="0.1",
        id="manual",
        constants=(ConstantHint(target="/value", value="manual", reason="Required value."),),
    )
    baseline = _baseline(source, target, candidate_sets=candidates, hints=hints)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/first", "document": "input"},
                paths=("/first",),
            ),
        ),
    )

    result = _apply(baseline, source, target, package, response)

    assert result.suggestions == baseline.suggestions
    assert _only(result).origin == SuggestionOrigin.MANUAL


def test_one_static_invalid_proposal_does_not_discard_valid_proposal_in_same_response() -> None:
    source, target = _schemas({"label": {"type": "string"}, "quantity": {"type": "integer"}})
    candidates = (
        _candidate_set("/label"),
        _candidate_set("/quantity"),
    )
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/label",
                expression={"op": "literal", "value": "approved"},
                paths=(),
            ),
            _proposal(
                "/quantity",
                expression={"op": "get", "path": "/first", "document": "input"},
                paths=("/first",),
            ),
        ),
    )

    result = _apply(baseline, source, target, package, response)

    by_target = {item.target_path: item for item in result.suggestions}
    assert by_target["/label"].origin == SuggestionOrigin.MODEL
    assert by_target["/label"].disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert by_target["/quantity"].expression == baseline.suggestions[1].expression
    assert any(
        issue.code == IssueCode.TYPE_MISMATCH and issue.target_path == "/quantity"
        for issue in result.issues
    )


def test_model_proposal_never_auto_promotes_a_low_deterministic_candidate() -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value", (("/first", 0.2),)),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={"op": "get", "path": "/first", "document": "input"},
                paths=("/first",),
            ),
        ),
    )

    suggestion = _only(_apply(baseline, source, target, package, response))

    assert suggestion.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert suggestion.confidence_band == ConfidenceBand.NONE


@pytest.mark.parametrize(
    ("expression", "selected_source_path", "selected_source_paths"),
    [
        (
            {"op": "get", "path": "/first", "document": "input"},
            "/first",
            (),
        ),
        (
            {
                "op": "concat",
                "operands": [
                    {"op": "get", "path": "/first", "document": "input"},
                    {"op": "get", "path": "/last", "document": "input"},
                ],
                "separator": " ",
            },
            None,
            ("/first",),
        ),
        (
            {"op": "get", "path": "/first", "document": "input"},
            None,
            ("/last",),
        ),
        (
            {"op": "get", "path": "/first", "document": "input"},
            "/first",
            ("/first", "/first"),
        ),
    ],
    ids=("concealed-direct", "concealed-multi", "wrong-path", "duplicate-path"),
)
def test_model_suggestion_requires_exact_declared_input_dependencies(
    expression: object,
    selected_source_path: str | None,
    selected_source_paths: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="input dependencies"):
        MappingSuggestion(
            target_path="/value",
            confidence_band=ConfidenceBand.NONE,
            disposition=SuggestionDisposition.REVIEW_REQUIRED,
            confidence_score=None,
            confidence_method="model-proposal-v0.1",
            selected_source_path=selected_source_path,
            selected_source_paths=selected_source_paths,
            origin=SuggestionOrigin.MODEL,
            expression=expression,
        )


def test_model_constant_may_have_no_selected_source_paths() -> None:
    suggestion = MappingSuggestion(
        target_path="/value",
        confidence_band=ConfidenceBand.NONE,
        disposition=SuggestionDisposition.REVIEW_REQUIRED,
        confidence_score=None,
        confidence_method="model-proposal-v0.1",
        selected_source_path=None,
        selected_source_paths=(),
        origin=SuggestionOrigin.MODEL,
        expression={"op": "literal", "value": "US"},
    )

    assert suggestion.selected_source_paths == ()


def test_forged_serialized_model_suggestion_cannot_reach_accept_selected_review(
    tmp_path: Path,
) -> None:
    source, target = _schemas()
    candidates = (_candidate_set("/value"),)
    baseline = _baseline(source, target, candidate_sets=candidates)
    package = _package(source, target, candidates)
    response = _response(
        package,
        (
            _proposal(
                "/value",
                expression={
                    "op": "concat",
                    "operands": [
                        {"op": "get", "path": "/first", "document": "input"},
                        {"op": "get", "path": "/last", "document": "input"},
                    ],
                    "separator": " ",
                },
                paths=("/first", "/last"),
            ),
        ),
    )
    payload = _apply(baseline, source, target, package, response).model_dump(mode="json")
    payload["suggestions"][0]["selected_source_paths"] = []
    path = tmp_path / "forged-suggestions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="input dependencies"):
        load_suggestion_report(path)
