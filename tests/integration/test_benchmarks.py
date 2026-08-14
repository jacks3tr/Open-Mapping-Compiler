"""Benchmark and CLI smoke tests."""

from __future__ import annotations

from pathlib import Path

from open_mapping.benchmark.gates import check_gates
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.benchmarks import BenchmarkManifest, BenchmarkMetrics


def test_gates() -> None:
    manifest = BenchmarkManifest(
        benchmark_version="0.1",
        id="b",
        source_schema="s",
        target_schema="t",
        samples="samples.jsonl",
        release_gates={"target_outcome_coverage": {"minimum": 1.0}},
    )
    metrics = BenchmarkMetrics(target_outcome_coverage=0.5)
    assert check_gates(manifest, metrics)


def test_benchmark_packs_run() -> None:
    expected_failed_gates: dict[str, set[str]] = {
        "erp-mes": set(),
        "material-part": set(),
        "crm-erp": set(),
        "account-segments": set(),
        "order-fulfillment": set(),
    }
    for name, expected in expected_failed_gates.items():
        result = run_benchmark_pack(Path("benchmarks") / name, enforce_gates=False)
        assert result.metrics.target_outcome_coverage == 1.0
        assert {
            issue.message.split(" gate ", 1)[1].split(" failed", 1)[0].strip("'")
            for issue in result.gate_issues
        } == expected
        assert result.json_report_path is not None and result.json_report_path.is_file()
        assert result.markdown_report_path is not None and result.markdown_report_path.is_file()
