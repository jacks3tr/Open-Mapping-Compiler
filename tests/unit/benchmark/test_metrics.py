"""Hand-calculated benchmark metric tests."""

from __future__ import annotations

import pytest

from open_mapping.benchmark.metrics import (
    MetricEvidence,
    calculate_metrics,
    measured_rate,
)
from open_mapping.model.benchmarks import BenchmarkManifest, BenchmarkMetrics


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    ((3, 4, 0.75), (0, 4, 0.0), (4, 4, 1.0)),
)
def test_measured_rate_uses_observed_counts(
    numerator: int, denominator: int, expected: float
) -> None:
    measurement = measured_rate("direct_match_precision", numerator, denominator)
    assert measurement.value == expected
    assert measurement.numerator == numerator
    assert measurement.denominator == denominator
    assert not measurement.issues


def test_zero_denominator_is_not_automatically_perfect() -> None:
    measurement = measured_rate("direct_match_precision", 0, 0)
    assert measurement.value == 0.0
    assert measurement.denominator == 0
    assert len(measurement.issues) == 1
    assert measurement.issues[0].severity.value == "warning"


def test_explicit_zero_expectation_can_be_perfect() -> None:
    measurement = measured_rate("expected_ambiguity_detection", 0, 0, explicitly_expects_zero=True)
    assert measurement.value == 1.0
    assert not measurement.issues


def test_absence_of_failure_has_explicit_zero_semantics() -> None:
    measurement = measured_rate(
        "high_confidence_false_positive_rate", 0, 0, absence_of_failure=True
    )
    assert measurement.value == 0.0
    assert not measurement.issues


def test_invalid_observed_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        measured_rate("direct_match_recall", 2, 1)


def _manifest(**values: object) -> BenchmarkManifest:
    return BenchmarkManifest.model_validate(
        {
            "benchmark_version": "0.1",
            "id": "presence",
            "source_schema": "source.json",
            "target_schema": "target.json",
            "samples": "samples.jsonl",
            **values,
        }
    )


def test_omitted_zero_case_labels_are_not_explicit_expectations() -> None:
    manifest = _manifest()
    assert manifest.expected_ambiguous_targets == ()
    assert manifest.expected_no_match_targets == ()
    assert not manifest.ambiguity_targets_declared
    assert not manifest.no_match_targets_declared


def test_explicit_empty_zero_case_labels_are_explicit_expectations() -> None:
    manifest = _manifest(expected_ambiguous_targets=[], expected_no_match_targets=[])
    assert manifest.expected_ambiguous_targets == ()
    assert manifest.expected_no_match_targets == ()
    assert manifest.ambiguity_targets_declared
    assert manifest.no_match_targets_declared


def test_omitted_vs_explicit_empty_changes_zero_denominator_metrics() -> None:
    omitted = _manifest()
    explicit = _manifest(expected_ambiguous_targets=[], expected_no_match_targets=[])
    names = tuple(BenchmarkMetrics.model_fields)

    def evidence(manifest: BenchmarkManifest) -> dict[str, MetricEvidence]:
        result = {name: MetricEvidence(1, 1) for name in names}
        ambiguity_zero = manifest.ambiguity_targets_declared
        no_match_zero = manifest.no_match_targets_declared
        result["ambiguity_precision"] = MetricEvidence(0, 0, explicitly_expects_zero=ambiguity_zero)
        result["expected_ambiguity_detection"] = MetricEvidence(
            0, 0, explicitly_expects_zero=ambiguity_zero
        )
        result["no_match_precision"] = MetricEvidence(0, 0, explicitly_expects_zero=no_match_zero)
        result["no_match_recall"] = MetricEvidence(0, 0, explicitly_expects_zero=no_match_zero)
        result["expected_no_match_detection"] = MetricEvidence(
            0, 0, explicitly_expects_zero=no_match_zero
        )
        return result

    omitted_metrics, _, omitted_issues = calculate_metrics(evidence(omitted))
    explicit_metrics, _, explicit_issues = calculate_metrics(evidence(explicit))
    for name in (
        "ambiguity_precision",
        "expected_ambiguity_detection",
        "no_match_precision",
        "no_match_recall",
        "expected_no_match_detection",
    ):
        assert getattr(omitted_metrics, name) == 0.0
        assert getattr(explicit_metrics, name) == 1.0
    assert len(omitted_issues) == 5
    assert not explicit_issues


def test_every_runner_metric_changes_when_its_observed_evidence_changes() -> None:
    names = tuple(BenchmarkMetrics.model_fields)
    baseline_evidence = {name: MetricEvidence(1, 2) for name in names}
    baseline_metrics, baseline_measurements, baseline_issues = calculate_metrics(baseline_evidence)
    assert not baseline_issues

    for name in names:
        assert baseline_measurements[name].numerator == 1
        assert baseline_measurements[name].denominator == 2
        perturbed = dict(baseline_evidence)
        perturbed[name] = MetricEvidence(2, 2)
        changed_metrics, changed_measurements, changed_issues = calculate_metrics(perturbed)
        assert not changed_issues
        assert changed_measurements[name].numerator == 2
        assert changed_measurements[name].denominator == 2
        assert getattr(changed_metrics, name) != getattr(baseline_metrics, name), name
        for unchanged in set(names).difference({name}):
            assert getattr(changed_metrics, unchanged) == getattr(baseline_metrics, unchanged)
