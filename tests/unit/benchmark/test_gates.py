"""Benchmark release-gate tests."""

from __future__ import annotations

from open_mapping.benchmark.gates import check_gates
from open_mapping.model.benchmarks import BenchmarkManifest, BenchmarkMetrics


def _manifest() -> BenchmarkManifest:
    return BenchmarkManifest(
        benchmark_version="0.1",
        id="observed",
        source_schema="source.json",
        target_schema="target.json",
        samples="samples.jsonl",
        release_gates={
            "direct_match_precision": {"minimum": 0.8},
            "high_confidence_false_positive_rate": {"maximum": 0.02},
        },
    )


def test_gates_fail_below_and_above_manifest_thresholds() -> None:
    metrics = BenchmarkMetrics(
        direct_match_precision=0.79,
        high_confidence_false_positive_rate=0.03,
    )
    issues = check_gates(_manifest(), metrics)
    assert len(issues) == 2
    assert "0.79 < 0.8" in issues[0].message
    assert "0.03 > 0.02" in issues[1].message


def test_gates_report_observed_values_and_pass_at_boundaries() -> None:
    metrics = BenchmarkMetrics(
        direct_match_precision=0.8,
        high_confidence_false_positive_rate=0.02,
    )
    assert check_gates(_manifest(), metrics) == ()
