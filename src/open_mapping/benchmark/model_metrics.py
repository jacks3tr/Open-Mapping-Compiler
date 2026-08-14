"""Truthful model-assisted benchmark measurements and bounded provenance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.model.benchmarks import (
    ModelBatchBenchmarkEvidence,
    ModelBenchmarkMetrics,
    ModelBenchmarkResult,
)
from open_mapping.model.expressions import CoalesceExpression, Expression, GetExpression
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingRule
from open_mapping.model.model_protocol import MappingContextPackage, ModelProposalAction
from open_mapping.model.providers import ModelRunDisclosure
from open_mapping.verification.static import verify_proposed_rule


@dataclass(frozen=True)
class ModelMetricCounts:
    """Observed counts used to calculate one model benchmark result."""

    valid_responses: int = 0
    response_batches: int = 0
    covered_targets: int = 0
    requested_targets: int = 0
    static_valid_proposals: int = 0
    proposed_targets: int = 0
    correct_direct_proposals: int = 0
    direct_proposals: int = 0
    expected_direct_targets: int = 0
    exact_transformations: int = 0
    expected_transformations: int = 0
    ambiguity_abstentions: int = 0
    expected_ambiguity_targets: int = 0
    no_match_abstentions: int = 0
    expected_no_match_targets: int = 0
    complete_mappings: int = 0
    mapping_runs: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    ambiguity_zero_expected: bool = False
    no_match_zero_expected: bool = False


_RATE_FIELDS = (
    ("model_response_validity_rate", "valid_responses", "response_batches", False),
    ("model_target_proposal_coverage", "covered_targets", "requested_targets", False),
    (
        "model_proposal_static_validity_rate",
        "static_valid_proposals",
        "proposed_targets",
        False,
    ),
    ("model_direct_match_precision", "correct_direct_proposals", "direct_proposals", False),
    (
        "model_direct_match_recall",
        "correct_direct_proposals",
        "expected_direct_targets",
        False,
    ),
    (
        "model_transformation_exact_match_rate",
        "exact_transformations",
        "expected_transformations",
        False,
    ),
    (
        "model_expected_ambiguity_abstention",
        "ambiguity_abstentions",
        "expected_ambiguity_targets",
        True,
    ),
    (
        "model_expected_no_match_abstention",
        "no_match_abstentions",
        "expected_no_match_targets",
        True,
    ),
    ("model_full_mapping_completion_rate", "complete_mappings", "mapping_runs", False),
)


def calculate_model_metrics(
    counts: ModelMetricCounts,
) -> tuple[ModelBenchmarkMetrics, dict[str, int], dict[str, int]]:
    """Calculate rates without hiding missing or zero-denominator evidence."""

    numerators: dict[str, int] = {}
    denominators: dict[str, int] = {}
    values: dict[str, object] = {}
    for metric, numerator_name, denominator_name, abstention_zero_case in _RATE_FIELDS:
        numerator = cast(int, getattr(counts, numerator_name))
        denominator = cast(int, getattr(counts, denominator_name))
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError(f"invalid observed counts for {metric}")
        zero_is_perfect = abstention_zero_case and (
            counts.ambiguity_zero_expected
            if metric == "model_expected_ambiguity_abstention"
            else counts.no_match_zero_expected
        )
        numerators[metric] = numerator
        denominators[metric] = denominator
        values[metric] = (
            numerator / denominator if denominator else (1.0 if zero_is_perfect else 0.0)
        )
    values.update(
        {
            "model_input_tokens": counts.input_tokens,
            "model_output_tokens": counts.output_tokens,
            "model_latency_ms": counts.latency_ms,
        }
    )
    return ModelBenchmarkMetrics.model_validate(values), numerators, denominators


def _direct_path(expression: Expression) -> str | None:
    if isinstance(expression, GetExpression) and expression.document == "input":
        return expression.path
    if isinstance(expression, CoalesceExpression) and len(expression.operands) == 1:
        return _direct_path(expression.operands[0])
    return None


def _expression_json(expression: Expression) -> JsonValue:
    return cast(JsonValue, expression.model_dump(mode="json"))


def _known_total(values: Sequence[int | None]) -> int | None:
    return (
        None
        if any(value is None for value in values)
        else sum(cast(int, value) for value in values)
    )


def build_model_benchmark_result(
    *,
    pack: BenchmarkPack,
    packages: Sequence[MappingContextPackage],
    disclosure: ModelRunDisclosure,
) -> ModelBenchmarkResult:
    """Evaluate validated provider responses against pack truth and static verification."""

    truth = {rule.target: rule for rule in pack.expected_mapping.rules}
    direct_truth = {
        target: rule
        for target, rule in truth.items()
        if _direct_path(rule.expression) is not None
        and target not in pack.manifest.expected_ambiguous_targets
    }
    transformation_truth = {
        target: rule for target, rule in truth.items() if _direct_path(rule.expression) is None
    }
    responses = tuple(run.response for run in disclosure.batch_runs if run.response is not None)
    proposals = tuple(proposal for response in responses for proposal in response.proposals)
    proposed = tuple(
        proposal for proposal in proposals if proposal.action is ModelProposalAction.PROPOSE
    )
    abstained = {
        proposal.target_path
        for proposal in proposals
        if proposal.action is ModelProposalAction.ABSTAIN
    }
    static_valid: dict[str, bool] = {}
    for proposal in proposed:
        if proposal.expression is None:
            static_valid[proposal.target_path] = False
            continue
        issues = verify_proposed_rule(
            MappingRule(
                target=proposal.target_path,
                expression=proposal.expression,
                confidence=0.0,
                confidence_method="model-benchmark-v0.1",
            ),
            source_schema=pack.source_schema,
            target_schema=pack.target_schema,
        )
        static_valid[proposal.target_path] = not any(
            issue.severity.value == "error" for issue in issues
        )

    direct_proposals = tuple(
        proposal
        for proposal in proposed
        if proposal.expression is not None and _direct_path(proposal.expression) is not None
    )
    correct_direct = sum(
        proposal.target_path in direct_truth
        and proposal.expression is not None
        and _direct_path(proposal.expression)
        == _direct_path(direct_truth[proposal.target_path].expression)
        for proposal in direct_proposals
    )
    exact_transformations = sum(
        proposal.target_path in transformation_truth
        and proposal.expression is not None
        and _expression_json(proposal.expression)
        == _expression_json(transformation_truth[proposal.target_path].expression)
        for proposal in proposed
    )
    exact_valid_targets = {
        proposal.target_path
        for proposal in proposed
        if proposal.target_path in truth
        and proposal.expression is not None
        and static_valid.get(proposal.target_path, False)
        and _expression_json(proposal.expression)
        == _expression_json(truth[proposal.target_path].expression)
    }
    complete = set(truth).issubset(exact_valid_targets) and set(
        pack.manifest.expected_no_match_targets
    ).issubset(abstained)
    input_usage = tuple(run.usage.input_tokens for run in disclosure.batch_runs)
    output_usage = tuple(run.usage.output_tokens for run in disclosure.batch_runs)
    counts = ModelMetricCounts(
        valid_responses=len(responses),
        response_batches=len(packages),
        covered_targets=len({proposal.target_path for proposal in proposals}),
        requested_targets=sum(len(package.target_requests) for package in packages),
        static_valid_proposals=sum(static_valid.values()),
        proposed_targets=len(proposed),
        correct_direct_proposals=correct_direct,
        direct_proposals=len(direct_proposals),
        expected_direct_targets=len(direct_truth),
        exact_transformations=exact_transformations,
        expected_transformations=len(transformation_truth),
        ambiguity_abstentions=len(abstained.intersection(pack.manifest.expected_ambiguous_targets)),
        expected_ambiguity_targets=len(pack.manifest.expected_ambiguous_targets),
        no_match_abstentions=len(abstained.intersection(pack.manifest.expected_no_match_targets)),
        expected_no_match_targets=len(pack.manifest.expected_no_match_targets),
        complete_mappings=int(complete),
        mapping_runs=1,
        input_tokens=_known_total(input_usage),
        output_tokens=_known_total(output_usage),
        latency_ms=sum(run.latency_ms for run in disclosure.batch_runs),
        ambiguity_zero_expected=(
            pack.manifest.ambiguity_targets_declared
            and not pack.manifest.expected_ambiguous_targets
        ),
        no_match_zero_expected=(
            pack.manifest.no_match_targets_declared and not pack.manifest.expected_no_match_targets
        ),
    )
    metrics, numerators, denominators = calculate_model_metrics(counts)
    return ModelBenchmarkResult(
        model_alias=disclosure.model_alias,
        provider_kind=disclosure.provider_kind,
        model_id=disclosure.model_id,
        prompt_version=disclosure.prompt_version,
        metrics=metrics,
        numerators=numerators,
        denominators=denominators,
        batch_runs=tuple(
            ModelBatchBenchmarkEvidence(
                batch_id=run.batch_id,
                context_sha256=run.context_sha256,
                response_sha256=run.response_sha256,
                input_tokens=run.usage.input_tokens,
                output_tokens=run.usage.output_tokens,
                latency_ms=run.latency_ms,
                response_valid=run.response is not None,
            )
            for run in disclosure.batch_runs
        ),
    )


__all__ = [
    "ModelMetricCounts",
    "build_model_benchmark_result",
    "calculate_model_metrics",
]
