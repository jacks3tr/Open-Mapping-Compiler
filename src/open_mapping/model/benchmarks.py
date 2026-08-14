"""Benchmark manifest and metrics models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from open_mapping.model.issues import Issue
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.model.model_config import ProviderKind


class BenchmarkGate(OpenMappingModel):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def _validate_thresholds(self) -> BenchmarkGate:
        if self.minimum is None and self.maximum is None:
            raise ValueError("benchmark gate requires minimum or maximum")
        for value in (self.minimum, self.maximum):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("benchmark gate thresholds must be between 0 and 1")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("benchmark gate minimum cannot exceed maximum")
        return self


class BenchmarkManifest(OpenMappingModel):
    benchmark_version: Literal["0.1"]
    id: str
    description: str = ""
    source_schema: str
    target_schema: str
    samples: str
    expected_mapping: str | None = None
    hints: str | None = None
    review: str | None = None
    expected_ambiguous_targets: tuple[str, ...] = ()
    expected_no_match_targets: tuple[str, ...] = ()
    release_gates: dict[str, BenchmarkGate] = {}

    @property
    def ambiguity_targets_declared(self) -> bool:
        return "expected_ambiguous_targets" in self.model_fields_set

    @property
    def no_match_targets_declared(self) -> bool:
        return "expected_no_match_targets" in self.model_fields_set


class BenchmarkMetrics(OpenMappingModel):
    target_outcome_coverage: float = 0.0
    direct_match_precision: float = 0.0
    direct_match_recall: float = 0.0
    transformation_exact_match_rate: float = 0.0
    high_confidence_false_positive_rate: float = 0.0
    high_confidence_precision: float = 0.0
    medium_confidence_precision: float = 0.0
    low_confidence_precision: float = 0.0
    ambiguity_precision: float = 0.0
    expected_ambiguity_detection: float = 0.0
    no_match_precision: float = 0.0
    no_match_recall: float = 0.0
    expected_no_match_detection: float = 0.0
    review_application_correctness: float = 0.0
    required_target_coverage: float = 0.0
    compile_success_rate: float = 0.0
    target_schema_pass_rate: float = 0.0
    invariant_pass_rate: float = 0.0
    cross_runtime_equivalence: float = 0.0
    invalid_source_path_rejection: float = 0.0
    duplicate_target_rejection: float = 0.0


class ModelBenchmarkMetrics(OpenMappingModel):
    model_response_validity_rate: float = 0.0
    model_target_proposal_coverage: float = 0.0
    model_proposal_static_validity_rate: float = 0.0
    model_direct_match_precision: float = 0.0
    model_direct_match_recall: float = 0.0
    model_transformation_exact_match_rate: float = 0.0
    model_expected_ambiguity_abstention: float = 0.0
    model_expected_no_match_abstention: float = 0.0
    model_full_mapping_completion_rate: float = 0.0
    model_input_tokens: int | None = None
    model_output_tokens: int | None = None
    model_latency_ms: int = 0


class ModelBatchBenchmarkEvidence(OpenMappingModel):
    """Persistable model evidence without prompts, samples, or response bodies."""

    batch_id: str
    context_sha256: str
    response_sha256: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    response_valid: bool


class ModelBenchmarkResult(OpenMappingModel):
    model_alias: str
    provider_kind: ProviderKind
    model_id: str
    prompt_version: str
    metrics: ModelBenchmarkMetrics
    numerators: dict[str, int]
    denominators: dict[str, int]
    batch_runs: tuple[ModelBatchBenchmarkEvidence, ...]

    @property
    def comparison_key(self) -> str:
        return "|".join(
            (self.model_alias, self.provider_kind.value, self.model_id, self.prompt_version)
        )


class BenchmarkSample(OpenMappingModel):
    id: str
    input: JsonValue
    expected: JsonValue | None = None
    expected_error: str | None = None
    has_expected: bool = False

    @model_validator(mode="before")
    @classmethod
    def _record_expected_presence(cls, value: object) -> object:
        if isinstance(value, dict):
            result = dict(value)
            result["has_expected"] = "expected" in result
            return result
        return value

    @model_validator(mode="after")
    def _validate_expectation(self) -> BenchmarkSample:
        if self.has_expected == (self.expected_error is not None):
            raise ValueError("benchmark sample requires exactly one of expected or expected_error")
        return self


class RuntimeObservation(OpenMappingModel):
    runtime: Literal["interpreter", "python", "typescript"]
    sample_id: str
    success: bool
    output: JsonValue | None = None
    error_code: str | None = None
    stderr_summary: str | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> RuntimeObservation:
        if self.success and self.error_code is not None:
            raise ValueError("successful runtime observations cannot have an error code")
        if not self.success and not self.error_code:
            raise ValueError("failed runtime observations require a stable error code")
        return self


class GateResult(OpenMappingModel):
    metric: str
    value: float
    minimum: float | None = None
    maximum: float | None = None
    passed: bool


class BenchmarkReport(OpenMappingModel):
    report_version: Literal["0.1"] = "0.1"
    id: str
    baseline_confidence_counts: dict[str, int]
    baseline_disposition_counts: dict[str, int]
    assisted_confidence_counts: dict[str, int]
    assisted_disposition_counts: dict[str, int]
    metrics: BenchmarkMetrics
    numerators: dict[str, int]
    denominators: dict[str, int]
    gate_thresholds: dict[str, BenchmarkGate]
    gate_results: tuple[GateResult, ...]
    runtime_observations: tuple[RuntimeObservation, ...]
    issues: tuple[Issue, ...]
    model_results: dict[str, ModelBenchmarkResult] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
