"""Deterministic suggestion proposal assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter

from open_mapping.matching.ambiguity import detect_ambiguity
from open_mapping.matching.candidates import (
    TargetCandidateSet,
    iter_target_mapping_units,
    validate_suggestion_coverage,
)
from open_mapping.matching.confidence import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    ConfidenceThresholds,
    classify_confidence,
)
from open_mapping.matching.hints import hint_to_rule
from open_mapping.model.expressions import Expression, GetExpression
from open_mapping.model.hints import MappingHints
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.mappings import Evidence, EvidenceKind, MappingRule
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelMappingResponse,
    ModelProposalAction,
    ModelTargetProposal,
    validate_model_mapping_response,
)
from open_mapping.model.providers import ModelRunDisclosure
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    MatchCandidate,
    SuggestionDisposition,
    SuggestionOrigin,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.pointers import split_pointer
from open_mapping.providers.protocol import ProviderResponse, provider_expression_input_paths
from open_mapping.verification.static import verify_proposed_rule


def _direct_rule(source_path: str, target_path: str, source_schema: SchemaDocument) -> MappingRule:
    source_field = source_schema.field(source_path)
    expression: object
    if source_field is not None and not source_field.required:
        expression = {
            "op": "coalesce",
            "operands": [{"op": "get", "path": source_path, "document": "input"}],
        }
    else:
        expression = GetExpression(op="get", path=source_path, document="input")
    return MappingRule(
        target=target_path,
        expression=TypeAdapter(Expression).validate_python(expression),
        confidence=0.0,
        confidence_method="heuristic-v0.1",
    )


def _build_suggestion(
    target: str,
    *,
    candidate_set: TargetCandidateSet,
    thresholds: ConfidenceThresholds,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> MappingSuggestion:
    eligible: list[tuple[MatchCandidate, MappingRule, tuple[Issue, ...]]] = []
    for candidate in candidate_set.candidates:
        rule = _direct_rule(candidate.source_path, target, source_schema)
        issues = verify_proposed_rule(
            rule, source_schema=source_schema, target_schema=target_schema
        )
        if not any(issue.severity.value == "error" for issue in issues):
            eligible.append((candidate, rule, issues))
    eligible.sort(key=lambda item: (-item[0].raw_score, item[0].source_path))
    if not eligible:
        return MappingSuggestion(
            target_path=target,
            confidence_band=ConfidenceBand.NONE,
            disposition=SuggestionDisposition.NO_MATCH,
            confidence_score=None,
            confidence_method="heuristic-v0.1",
            selected_source_path=None,
            expression=None,
            candidates=candidate_set.candidates,
            evidence=(),
            issues=(),
            reason="No static-valid source candidate is available.",
        )
    best_candidate, best_rule, best_issues = eligible[0]
    best_score = best_candidate.raw_score
    band = classify_confidence(best_score, thresholds=thresholds)
    eligible_candidates = TargetCandidateSet(
        target_path=candidate_set.target_path,
        candidates=tuple(item[0] for item in eligible),
    )
    ambiguous = detect_ambiguity(eligible_candidates, thresholds=thresholds)
    margin = 1.0 if len(eligible) == 1 else best_score - eligible[1][0].raw_score
    if best_score < thresholds.low_minimum:
        disposition = SuggestionDisposition.NO_MATCH
    elif ambiguous:
        disposition = SuggestionDisposition.AMBIGUOUS
    elif band == ConfidenceBand.HIGH and margin >= thresholds.auto_suggest_margin:
        disposition = SuggestionDisposition.SUGGESTED
    elif band in {ConfidenceBand.MEDIUM, ConfidenceBand.LOW} or (
        band == ConfidenceBand.HIGH and margin > thresholds.ambiguity_margin
    ):
        disposition = SuggestionDisposition.REVIEW_REQUIRED
    else:
        disposition = SuggestionDisposition.NO_MATCH
    if disposition in {SuggestionDisposition.SUGGESTED, SuggestionDisposition.REVIEW_REQUIRED}:
        expression = best_rule.expression
        selected = best_candidate.source_path
        evidence = tuple(best_candidate.evidence) + (
            Evidence(kind=EvidenceKind.VERIFIER_RESULT, detail="Static verification passed."),
        )
        score: float | None = best_score
        method = "heuristic-v0.1"
    else:
        expression = None
        selected = None
        evidence = tuple(best_candidate.evidence)
        score = best_score if band != ConfidenceBand.NONE else None
        method = "heuristic-v0.1"
    return MappingSuggestion(
        target_path=target,
        confidence_band=band,
        disposition=disposition,
        confidence_score=score,
        confidence_method=method,
        selected_source_path=selected,
        expression=expression,
        candidates=candidate_set.candidates,
        evidence=evidence,
        issues=tuple(best_issues),
        reason=(
            "Two or more plausible source paths remain within ambiguity tolerance."
            if ambiguous
            else "No viable source concept exists."
            if disposition == SuggestionDisposition.NO_MATCH
            else "Candidate meets the deterministic confidence policy."
        ),
    )


def build_deterministic_suggestions(
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    *,
    candidate_sets: Sequence[TargetCandidateSet],
    hints: MappingHints | None,
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
) -> SuggestionReport:
    sets_by_target = {item.target_path: item for item in candidate_sets}
    suggestions: list[MappingSuggestion] = []
    for target_unit in iter_target_mapping_units(target_schema):
        target = target_unit.pointer
        candidate_set = sets_by_target.get(
            target, TargetCandidateSet(target_path=target, candidates=())
        )
        manual: MappingSuggestion | None = None
        if hints is not None:
            for hint in (
                *hints.direct,
                *hints.lookups,
                *hints.unit_conversions,
                *hints.dates,
                *hints.constants,
                *hints.expressions,
            ):
                if getattr(hint, "target", None) == target:
                    rule = hint_to_rule(hint, target_schema.schema_id, target_schema.schema_version)
                    issues = verify_proposed_rule(
                        rule, source_schema=source_schema, target_schema=target_schema
                    )
                    if not any(issue.severity.value == "error" for issue in issues):
                        manual = MappingSuggestion(
                            target_path=target,
                            confidence_band=ConfidenceBand.NONE,
                            disposition=SuggestionDisposition.MANUAL,
                            confidence_score=None,
                            confidence_method="business-instruction-v0.1",
                            selected_source_path=getattr(hint, "source", None),
                            origin=SuggestionOrigin.MANUAL,
                            expression=rule.expression,
                            candidates=candidate_set.candidates,
                            evidence=rule.evidence,
                            issues=tuple(issues),
                            reason=str(getattr(hint, "reason", "Explicit business instruction.")),
                        )
                        break
        suggestions.append(
            manual
            if manual is not None
            else _build_suggestion(
                target,
                candidate_set=candidate_set,
                thresholds=thresholds,
                source_schema=source_schema,
                target_schema=target_schema,
            )
        )
    suggestions.sort(key=lambda suggestion: split_pointer(suggestion.target_path))
    report = SuggestionReport(
        report_version="0.1",
        source_schema_id=source_schema.schema_id,
        source_schema_version=source_schema.schema_version,
        target_schema_id=target_schema.schema_id,
        target_schema_version=target_schema.schema_version,
        suggestions=tuple(suggestions),
        summary=summarize_suggestions(suggestions),
    )
    coverage_issues = validate_suggestion_coverage(report, target_schema)
    return report.model_copy(update={"issues": tuple(coverage_issues)})


def summarize_suggestions(suggestions: Sequence[MappingSuggestion]) -> SuggestionSummary:
    high = 0
    medium = 0
    low = 0
    none = 0
    suggested = 0
    review_required = 0
    ambiguous = 0
    no_match = 0
    manual = 0
    for suggestion in suggestions:
        band = suggestion.confidence_band
        if band == ConfidenceBand.HIGH:
            high += 1
        elif band == ConfidenceBand.MEDIUM:
            medium += 1
        elif band == ConfidenceBand.LOW:
            low += 1
        else:
            none += 1
        disposition = suggestion.disposition
        if disposition == SuggestionDisposition.SUGGESTED:
            suggested += 1
        elif disposition == SuggestionDisposition.REVIEW_REQUIRED:
            review_required += 1
        elif disposition == SuggestionDisposition.AMBIGUOUS:
            ambiguous += 1
        elif disposition == SuggestionDisposition.NO_MATCH:
            no_match += 1
        else:
            manual += 1
    return SuggestionSummary(
        total_targets=len(suggestions),
        high=high,
        medium=medium,
        low=low,
        none=none,
        suggested=suggested,
        review_required=review_required,
        ambiguous=ambiguous,
        no_match=no_match,
        manual=manual,
    )


def _provider_warning(target: str, message: str) -> Issue:
    return Issue(
        code=IssueCode.PROVIDER_RESPONSE_INVALID,
        severity=Severity.WARNING,
        component="matching.proposals",
        message=message,
        correction="Retain the deterministic outcome and correct the provider response.",
        target_path=target,
    )


def _provider_evidence(reason: str, *, complex_expression: bool = False) -> Evidence:
    detail = "Provider expression was statically valid and recorded for review."
    if not complex_expression:
        detail = "Provider nominated an existing bounded candidate for review."
    if reason:
        detail = f"{detail} Reason: {reason}"
    return Evidence(kind=EvidenceKind.MODEL_RERANK, detail=detail)


def apply_provider_assistance(
    baseline: SuggestionReport,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    responses: Mapping[str, ProviderResponse],
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
) -> SuggestionReport:
    """Apply bounded provider evidence without granting provider policy authority."""
    updated: list[MappingSuggestion] = []
    issues = list(baseline.issues)
    known_targets = {suggestion.target_path for suggestion in baseline.suggestions}
    for response_target in sorted(set(responses).difference(known_targets), key=split_pointer):
        issues.append(
            _provider_warning(response_target, "provider response targets an unknown field")
        )

    for suggestion in baseline.suggestions:
        response = responses.get(suggestion.target_path)
        if (
            response is None
            or not response.proposals
            or suggestion.disposition == SuggestionDisposition.MANUAL
        ):
            updated.append(suggestion)
            continue
        if len(response.proposals) != 1:
            issues.append(
                _provider_warning(
                    suggestion.target_path, "provider returned multiple target proposals"
                )
            )
            updated.append(suggestion)
            continue
        proposal = response.proposals[0]
        candidate_by_path = {
            candidate.source_path: candidate for candidate in suggestion.candidates
        }
        selected_paths = set(proposal.selected_source_paths)
        if proposal.target_path != suggestion.target_path:
            issues.append(
                _provider_warning(
                    suggestion.target_path, "provider proposal targets a different field"
                )
            )
            updated.append(suggestion)
            continue
        if proposal.abstain:
            updated.append(suggestion)
            continue
        if not selected_paths.issubset(candidate_by_path):
            issues.append(
                _provider_warning(
                    suggestion.target_path, "provider selected a path outside the candidates"
                )
            )
            updated.append(suggestion)
            continue

        expression = proposal.expression
        if expression is not None and not provider_expression_input_paths(
            expression.model_dump(mode="json")
        ).issubset(candidate_by_path):
            issues.append(
                _provider_warning(
                    suggestion.target_path,
                    "provider expression reads a path outside the candidates",
                )
            )
            updated.append(suggestion)
            continue
        if expression is None and len(proposal.selected_source_paths) == 1:
            expression = _direct_rule(
                proposal.selected_source_paths[0], suggestion.target_path, source_schema
            ).expression
        if expression is None:
            issues.append(
                _provider_warning(suggestion.target_path, "provider proposal has no expression")
            )
            updated.append(suggestion)
            continue
        rule = MappingRule(
            target=suggestion.target_path,
            expression=expression,
            confidence=0.0,
            confidence_method="provider-evidence-v0.1",
        )
        static_issues = verify_proposed_rule(
            rule, source_schema=source_schema, target_schema=target_schema
        )
        if any(issue.severity == Severity.ERROR for issue in static_issues):
            issues.append(
                _provider_warning(
                    suggestion.target_path, "provider expression failed static verification"
                )
            )
            updated.append(suggestion)
            continue

        is_direct = (
            len(proposal.selected_source_paths) == 1
            and isinstance(expression, GetExpression)
            and expression.document == "input"
            and expression.path == proposal.selected_source_paths[0]
        )
        if not is_direct:
            updated.append(
                suggestion.model_copy(
                    update={
                        "evidence": suggestion.evidence
                        + (_provider_evidence(proposal.reason, complex_expression=True),)
                    }
                )
            )
            continue

        source_path = proposal.selected_source_paths[0]
        candidate = candidate_by_path[source_path]
        band = classify_confidence(candidate.raw_score, thresholds=thresholds)
        if band == ConfidenceBand.NONE:
            issues.append(
                _provider_warning(
                    suggestion.target_path,
                    "provider nominated a candidate below the deterministic low threshold",
                )
            )
            updated.append(suggestion)
            continue
        if suggestion.selected_source_path == source_path:
            updated.append(
                suggestion.model_copy(
                    update={
                        "evidence": suggestion.evidence + (_provider_evidence(proposal.reason),)
                    }
                )
            )
            continue
        updated.append(
            MappingSuggestion(
                target_path=suggestion.target_path,
                confidence_band=band,
                disposition=SuggestionDisposition.REVIEW_REQUIRED,
                confidence_score=candidate.raw_score,
                confidence_method="heuristic-v0.1",
                selected_source_path=source_path,
                expression=expression,
                candidates=suggestion.candidates,
                evidence=tuple(candidate.evidence)
                + (
                    _provider_evidence(proposal.reason),
                    Evidence(
                        kind=EvidenceKind.VERIFIER_RESULT,
                        detail="Static verification passed.",
                    ),
                ),
                issues=static_issues,
                reason="Provider nominated an existing candidate; explicit review remains required.",
            )
        )
    updated.sort(key=lambda item: split_pointer(item.target_path))
    return baseline.model_copy(
        update={
            "suggestions": tuple(updated),
            "summary": summarize_suggestions(updated),
            "issues": tuple(issues),
        }
    )


def _model_warning(target: str, message: str) -> Issue:
    return Issue(
        code=IssueCode.PROVIDER_RESPONSE_INVALID,
        severity=Severity.WARNING,
        component="matching.proposals",
        message=message,
        correction="Retain the deterministic outcome and correct the model response.",
        target_path=target,
    )


def _bounded_model_detail(prefix: str, proposal: ModelTargetProposal) -> str:
    detail = prefix
    if proposal.reason:
        detail += f" Reason: {proposal.reason}"
    if proposal.evidence:
        detail += f" Evidence: {'; '.join(proposal.evidence)}"
    return detail[:300]


def _model_evidence(proposal: ModelTargetProposal, *, abstained: bool = False) -> Evidence:
    prefix = (
        "Model abstained; the deterministic outcome was retained."
        if abstained
        else "Model proposal was statically verified."
    )
    return Evidence(
        kind=EvidenceKind.MODEL_RERANK,
        detail=_bounded_model_detail(prefix, proposal),
    )


def _response_packages(
    packages: Sequence[MappingContextPackage],
    responses: Sequence[ModelMappingResponse],
) -> tuple[dict[str, MappingContextPackage], dict[str, ModelMappingResponse], list[Issue]]:
    issues: list[Issue] = []
    packages_by_batch: dict[str, MappingContextPackage] = {}
    for package in packages:
        if package.batch_id in packages_by_batch:
            issues.append(_model_warning("", f"duplicate model package {package.batch_id!r}"))
        else:
            packages_by_batch[package.batch_id] = package
    responses_by_batch: dict[str, ModelMappingResponse] = {}
    for response in responses:
        matched_package = packages_by_batch.get(response.batch_id)
        if matched_package is None:
            issues.append(
                _model_warning("", f"model response has unknown batch {response.batch_id!r}")
            )
            continue
        if response.batch_id in responses_by_batch:
            issues.append(_model_warning("", f"duplicate model response {response.batch_id!r}"))
            continue
        response_issues = validate_model_mapping_response(response, package=matched_package)
        coverage_messages = {
            "response protocol_version does not match the request",
            "response prompt_version does not match the request",
            "response batch_id does not match the request",
            "response context_sha256 does not match the request",
            "unknown target proposal",
            "duplicate target proposal",
            "missing requested target proposal",
            "target proposals are not in request order",
        }
        coverage_issues = tuple(
            issue for issue in response_issues if issue.message in coverage_messages
        )
        if coverage_issues:
            target = response.proposals[0].target_path if response.proposals else ""
            issues.append(
                _model_warning(
                    target,
                    f"model response {response.batch_id!r} failed response coverage validation",
                )
            )
            continue
        responses_by_batch[response.batch_id] = response
    return packages_by_batch, responses_by_batch, issues


def _candidate_direct_expression(
    proposal: ModelTargetProposal,
) -> str | None:
    expression = proposal.expression
    if (
        len(proposal.selected_source_paths) == 1
        and isinstance(expression, GetExpression)
        and expression.document == "input"
        and expression.path == proposal.selected_source_paths[0]
    ):
        return proposal.selected_source_paths[0]
    return None


def apply_model_mapping_responses(
    baseline: SuggestionReport,
    *,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    packages: Sequence[MappingContextPackage],
    responses: Sequence[ModelMappingResponse],
    disclosure: ModelRunDisclosure,
) -> SuggestionReport:
    """Reconcile statically verified model drafts without granting policy authority."""

    packages_by_batch, responses_by_batch, issues = _response_packages(packages, responses)
    proposals_by_target: dict[str, ModelTargetProposal] = {}
    authority_issues_by_target: dict[str, tuple[Issue, ...]] = {}
    static_issues_by_target: dict[str, tuple[Issue, ...]] = {}
    duplicate_targets: set[str] = set()
    for batch_id in sorted(responses_by_batch):
        response = responses_by_batch[batch_id]
        package = packages_by_batch[batch_id]
        semantic_issues = validate_model_mapping_response(response, package=package)
        for proposal in response.proposals:
            if proposal.target_path in duplicate_targets:
                continue
            if proposal.target_path in proposals_by_target:
                issues.append(
                    _model_warning(
                        proposal.target_path,
                        "model responses contain duplicate target proposals across batches",
                    )
                )
                duplicate_targets.add(proposal.target_path)
                proposals_by_target.pop(proposal.target_path, None)
                continue
            proposals_by_target[proposal.target_path] = proposal
            authority_issues_by_target[proposal.target_path] = tuple(
                issue for issue in semantic_issues if issue.target_path == proposal.target_path
            )
            if proposal.expression is not None:
                static_issues_by_target[proposal.target_path] = verify_proposed_rule(
                    MappingRule(
                        target=proposal.target_path,
                        expression=proposal.expression,
                        confidence=0.0,
                        confidence_method="model-proposal-v0.1",
                    ),
                    source_schema=source_schema,
                    target_schema=target_schema,
                )

    baseline_targets = {suggestion.target_path for suggestion in baseline.suggestions}
    for target in sorted(set(proposals_by_target).difference(baseline_targets), key=split_pointer):
        issues.append(_model_warning(target, "model response targets an unknown field"))

    updated: list[MappingSuggestion] = []
    for suggestion in baseline.suggestions:
        current_proposal = proposals_by_target.get(suggestion.target_path)
        if current_proposal is None or suggestion.disposition == SuggestionDisposition.MANUAL:
            updated.append(suggestion)
            continue
        proposal = current_proposal
        if proposal.action is ModelProposalAction.ABSTAIN:
            updated.append(
                suggestion.model_copy(
                    update={
                        "evidence": suggestion.evidence
                        + (_model_evidence(proposal, abstained=True),)
                    }
                )
            )
            continue
        if authority_issues_by_target.get(suggestion.target_path):
            issues.append(
                _model_warning(
                    suggestion.target_path,
                    "model proposal exceeds its package authority",
                )
            )
            updated.append(suggestion)
            continue
        expression = proposal.expression
        if expression is None:
            issues.append(
                _model_warning(suggestion.target_path, "model proposal has no expression")
            )
            updated.append(suggestion)
            continue
        static_issues = static_issues_by_target.get(suggestion.target_path, ())
        if any(issue.severity == Severity.ERROR for issue in static_issues):
            issues.append(
                _model_warning(
                    suggestion.target_path,
                    (f"model proposal failed static verification; reason: {proposal.reason[:200]}"),
                )
            )
            issues.extend(
                issue.model_copy(
                    update={
                        "severity": Severity.WARNING,
                        "component": "matching.proposals",
                        "correction": "Correct the model expression before review.",
                    }
                )
                for issue in static_issues
            )
            updated.append(suggestion)
            continue

        exact_agreement = (
            expression == suggestion.expression
            and proposal.selected_source_paths
            == (
                (suggestion.selected_source_path,)
                if suggestion.selected_source_path is not None
                else suggestion.selected_source_paths
            )
        )
        if exact_agreement:
            updated.append(
                suggestion.model_copy(
                    update={
                        "selected_source_paths": proposal.selected_source_paths,
                        "evidence": suggestion.evidence + (_model_evidence(proposal),),
                        "reason": proposal.reason,
                    }
                )
            )
            continue

        direct_path = _candidate_direct_expression(proposal)
        candidate_by_path = {
            candidate.source_path: candidate for candidate in suggestion.candidates
        }
        if direct_path is not None and direct_path in candidate_by_path:
            candidate = candidate_by_path[direct_path]
            band = classify_confidence(
                candidate.raw_score, thresholds=DEFAULT_CONFIDENCE_THRESHOLDS
            )
            updated.append(
                MappingSuggestion(
                    target_path=suggestion.target_path,
                    confidence_band=band,
                    disposition=SuggestionDisposition.REVIEW_REQUIRED,
                    confidence_score=(
                        candidate.raw_score if band is not ConfidenceBand.NONE else None
                    ),
                    confidence_method="heuristic-v0.1",
                    selected_source_path=direct_path,
                    selected_source_paths=(direct_path,),
                    origin=SuggestionOrigin.MODEL,
                    expression=expression,
                    candidates=suggestion.candidates,
                    evidence=tuple(candidate.evidence)
                    + (
                        _model_evidence(proposal),
                        Evidence(
                            kind=EvidenceKind.VERIFIER_RESULT,
                            detail="Static verification passed.",
                        ),
                    ),
                    issues=static_issues,
                    reason=proposal.reason,
                )
            )
            continue

        selected_paths = proposal.selected_source_paths
        updated.append(
            MappingSuggestion(
                target_path=suggestion.target_path,
                confidence_band=ConfidenceBand.NONE,
                disposition=SuggestionDisposition.REVIEW_REQUIRED,
                confidence_score=None,
                confidence_method="model-proposal-v0.1",
                selected_source_path=selected_paths[0] if len(selected_paths) == 1 else None,
                selected_source_paths=selected_paths,
                origin=SuggestionOrigin.MODEL,
                expression=expression,
                candidates=suggestion.candidates,
                evidence=suggestion.evidence
                + (
                    _model_evidence(proposal),
                    Evidence(
                        kind=EvidenceKind.VERIFIER_RESULT,
                        detail="Static verification passed.",
                    ),
                ),
                issues=static_issues,
                reason=proposal.reason,
            )
        )

    updated.sort(key=lambda item: split_pointer(item.target_path))
    return baseline.model_copy(
        update={
            "suggestions": tuple(updated),
            "summary": summarize_suggestions(updated),
            "issues": sort_issues((*baseline.issues, *issues)),
            "model_run_disclosure": disclosure,
        }
    )
