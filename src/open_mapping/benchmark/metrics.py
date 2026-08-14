"""Benchmark metric helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from open_mapping.model.benchmarks import BenchmarkMetrics
from open_mapping.model.issues import Issue, IssueCode, Severity


@dataclass(frozen=True)
class MetricMeasurement:
    value: float
    numerator: int
    denominator: int
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class MetricEvidence:
    numerator: int
    denominator: int
    explicitly_expects_zero: bool = False
    absence_of_failure: bool = False


def calculate_metrics(
    evidence: Mapping[str, MetricEvidence],
) -> tuple[BenchmarkMetrics, dict[str, MetricMeasurement], tuple[Issue, ...]]:
    expected = set(BenchmarkMetrics.model_fields)
    actual = set(evidence)
    if actual != expected:
        raise ValueError(
            f"metric evidence does not reconcile: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    measurements = {
        name: measured_rate(
            name,
            item.numerator,
            item.denominator,
            explicitly_expects_zero=item.explicitly_expects_zero,
            absence_of_failure=item.absence_of_failure,
        )
        for name, item in evidence.items()
    }
    metrics = BenchmarkMetrics.model_validate(
        {name: measurement.value for name, measurement in measurements.items()}
    )
    issues = tuple(issue for measurement in measurements.values() for issue in measurement.issues)
    return metrics, measurements, issues


def measured_rate(
    name: str,
    numerator: int,
    denominator: int,
    *,
    explicitly_expects_zero: bool = False,
    absence_of_failure: bool = False,
) -> MetricMeasurement:
    if numerator < 0 or denominator < 0:
        raise ValueError("observed metric counts must be non-negative")
    if numerator > denominator:
        raise ValueError("observed metric numerator cannot exceed denominator")
    if denominator:
        return MetricMeasurement(numerator / denominator, numerator, denominator)
    if explicitly_expects_zero:
        return MetricMeasurement(1.0, numerator, denominator)
    if absence_of_failure:
        return MetricMeasurement(0.0, numerator, denominator)
    warning = Issue(
        code=IssueCode.INVALID_INPUT,
        severity=Severity.WARNING,
        component="benchmark.metrics",
        message=f"metric {name!r} has no observed cases",
        correction="Declare an explicit zero expectation or add benchmark cases.",
    )
    return MetricMeasurement(0.0, numerator, denominator, (warning,))


def _rate(valid: int, total: int) -> float:
    return measured_rate("legacy_rate", valid, total).value


def precision(true_positive: int, predicted: int) -> float:
    return _rate(true_positive, predicted)


def recall(true_positive: int, actual: int) -> float:
    return _rate(true_positive, actual)


def false_positive_rate(false_positive: int, predicted: int) -> float:
    return measured_rate(
        "legacy_false_positive_rate",
        false_positive,
        predicted,
        absence_of_failure=True,
    ).value


def make_metrics(*, target_outcome_coverage: float = 1.0, **values: float) -> BenchmarkMetrics:
    return BenchmarkMetrics.model_validate(
        {"target_outcome_coverage": target_outcome_coverage, **values}
    )
