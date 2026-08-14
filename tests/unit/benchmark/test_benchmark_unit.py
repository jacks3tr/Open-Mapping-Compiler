"""Benchmark loader and metrics tests."""

from __future__ import annotations

from pathlib import Path

from open_mapping.benchmark.loader import find_benchmark_packs, load_benchmark_manifest
from open_mapping.benchmark.metrics import false_positive_rate, make_metrics, precision, recall


def test_manifest_load() -> None:
    path = Path("benchmarks/erp-mes/manifest.yaml")
    manifest = load_benchmark_manifest(path)
    assert manifest.id == "erp-mes"
    assert find_benchmark_packs(Path("benchmarks"))[0].name == "account-segments"


def test_metrics_helpers() -> None:
    assert precision(3, 3) == 1.0
    assert recall(3, 4) == 0.75
    assert false_positive_rate(0, 0) == 0.0
    metrics = make_metrics(target_outcome_coverage=1.0)
    assert metrics.target_outcome_coverage == 1.0
