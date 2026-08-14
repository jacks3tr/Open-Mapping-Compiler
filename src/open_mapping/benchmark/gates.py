"""Benchmark release gate enforcement."""

from __future__ import annotations

from open_mapping.model.benchmarks import BenchmarkManifest, BenchmarkMetrics
from open_mapping.model.issues import Issue, IssueCode, Severity


def check_gates(manifest: BenchmarkManifest, metrics: BenchmarkMetrics) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    data = metrics.model_dump()
    for name, gate in manifest.release_gates.items():
        value = float(data.get(name, 0.0))
        if gate.minimum is not None and value < gate.minimum:
            issues.append(
                Issue(
                    code=IssueCode.BENCHMARK_GATE_FAILED,
                    severity=Severity.ERROR,
                    component="benchmark.gates",
                    message=f"benchmark {manifest.id!r} gate {name!r} failed: {value} < {gate.minimum}",
                    correction="Improve mapping behavior or adjust the fixture contract.",
                )
            )
        if gate.maximum is not None and value > gate.maximum:
            issues.append(
                Issue(
                    code=IssueCode.BENCHMARK_GATE_FAILED,
                    severity=Severity.ERROR,
                    component="benchmark.gates",
                    message=f"benchmark {manifest.id!r} gate {name!r} failed: {value} > {gate.maximum}",
                    correction="Improve mapping behavior or adjust the fixture contract.",
                )
            )
    return tuple(issues)
