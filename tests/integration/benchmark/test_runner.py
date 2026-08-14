"""Truthful two-phase benchmark runner integration tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import load_json_schema
from open_mapping.benchmark.loader import load_benchmark_pack
from open_mapping.benchmark.runner import (
    _invariant_counts,
    _stable_error,
    run_benchmark_pack,
    target_schema_observation_counts,
)
from open_mapping.cli.benchmark import benchmark_command
from open_mapping.model.benchmarks import BenchmarkSample, RuntimeObservation
from open_mapping.model.issues import IssueCode


def test_manifest_is_fully_validated_before_a_run(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(Path("benchmarks/erp-mes"), pack)
    (pack / "samples.jsonl").write_text(
        '{"id":"duplicate","input":{},"expected":{}}\n'
        '{"id":"duplicate","input":{},"expected":{}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate sample ID"):
        load_benchmark_pack(pack)


def test_cli_persists_invalid_pack_report_and_fails_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "crm-erp"
    shutil.copytree(Path("benchmarks/crm-erp"), pack)
    manifest = (pack / "manifest.yaml").read_text(encoding="utf-8")
    (pack / "manifest.yaml").write_text(
        manifest.replace("  - /primaryAddress/street", "  - /primaryAddress", 1),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert benchmark_command([pack], True, None, False) == 7
    report = json.loads(
        (tmp_path / "results" / "crm-erp" / "benchmark.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "invalid"
    assert "not a mapping unit" in report["message"]


def test_runner_records_baseline_assisted_review_and_runtime_evidence(tmp_path: Path) -> None:
    result_dir = tmp_path / "results" / "erp-mes"
    run = run_benchmark_pack(Path("benchmarks/erp-mes"), enforce_gates=False, result_dir=result_dir)

    assert run.baseline_confidence_counts != run.assisted_confidence_counts
    assert run.baseline_disposition_counts != run.assisted_disposition_counts
    assert run.assembled_mapping_sha256 is not None
    assert run.denominators["cross_runtime_equivalence"] == 100
    assert len(run.runtime_observations) == 300
    assert {item.runtime for item in run.runtime_observations} == {
        "interpreter",
        "python",
        "typescript",
    }
    assert all(item.sample_id and item.success for item in run.runtime_observations)
    assert run.json_report_path == result_dir / "benchmark.json"
    assert run.markdown_report_path == result_dir / "benchmark.md"
    assert run.json_report_path.is_file()
    assert run.markdown_report_path.is_file()
    assert "—" not in run.markdown_report_path.read_text(encoding="utf-8")

    report = json.loads(run.json_report_path.read_text(encoding="utf-8"))
    assert report["metrics"] == run.metrics.model_dump(mode="json")
    assert report["denominators"] == run.denominators
    assert report["gate_thresholds"]
    assert "baseline_confidence_counts" in report
    assert "assisted_disposition_counts" in report


def test_runner_executes_review_assembled_mapping_not_ground_truth(tmp_path: Path) -> None:
    pack = tmp_path / "erp-mes"
    shutil.copytree(Path("benchmarks/erp-mes"), pack)
    expected = (pack / "expected.mapping.yaml").read_text(encoding="utf-8")
    (pack / "expected.mapping.yaml").write_text(
        expected.replace("path: /manufacturingOrder", "path: /workCenter", 1),
        encoding="utf-8",
    )

    run = run_benchmark_pack(pack, enforce_gates=False, result_dir=tmp_path / "results")

    assert run.metrics.direct_match_precision < 1.0
    interpreter = next(
        item
        for item in run.runtime_observations
        if item.sample_id == "erp-mes-001" and item.runtime == "interpreter"
    )
    assert interpreter.success
    assert interpreter.output is not None
    assert isinstance(interpreter.output, dict)
    assert interpreter.output["jobNumber"] == "MO-00001"


def test_corrected_review_assembles_and_all_runtimes_are_observed(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/account-segments"),
        enforce_gates=False,
        result_dir=tmp_path / "results",
    )

    assert run.assembled_mapping_sha256 is not None
    assert not any(issue.code == IssueCode.STALE_SUGGESTION_REPORT for issue in run.issues)
    assert run.metrics.compile_success_rate == 1.0
    assert run.denominators["compile_success_rate"] == 2
    assert len(run.runtime_observations) == 246
    assert run.metrics.cross_runtime_equivalence == 1.0


def test_generated_runtime_error_extracts_the_stable_code_from_traceback() -> None:
    code, summary = _stable_error(
        RuntimeError("Traceback: generated.py failed: TYPE_MISMATCH: cast rejected")
    )
    assert code == "TYPE_MISMATCH"
    assert summary == "TYPE_MISMATCH"


def test_target_schema_rate_counts_every_positive_runtime_outcome() -> None:
    schema = load_json_schema(Path("benchmarks/erp-mes/target.schema.json"), schema_id=None)
    sample = BenchmarkSample.model_validate(
        {"id": "positive", "input": {}, "expected": {"jobNumber": "expected"}}
    )
    observations = (
        RuntimeObservation(
            runtime="interpreter",
            sample_id="positive",
            success=True,
            output={"jobNumber": "only-one-field"},
        ),
        RuntimeObservation(
            runtime="python",
            sample_id="positive",
            success=False,
            error_code="TYPE_MISMATCH",
        ),
        RuntimeObservation(
            runtime="typescript",
            sample_id="positive",
            success=False,
            error_code="TYPE_MISMATCH",
        ),
    )
    passed, total, issues = target_schema_observation_counts(schema, (sample,), observations)
    assert passed == 0
    assert total == 3
    assert len(issues) == 1
    assert issues[0].code == IssueCode.TARGET_SCHEMA_VALIDATION


def test_invariant_failures_reduce_metric_and_create_an_issue() -> None:
    loaded = load_benchmark_pack(Path("benchmarks/order-fulfillment"))
    pack = replace(loaded, samples=loaded.samples[:1])
    observation = RuntimeObservation(
        runtime="interpreter",
        sample_id=pack.samples[0].id,
        success=True,
        output={"lines": [{"lineNumber": 1}, {"lineNumber": 1}]},
    )
    passed, total, issues = _invariant_counts(pack, (observation,))
    assert passed == 0
    assert total == 1
    assert len(issues) == 1
    assert issues[0].code == IssueCode.INVARIANT_FAILED


def test_interpreter_failure_counts_against_applicable_invariants() -> None:
    loaded = load_benchmark_pack(Path("benchmarks/order-fulfillment"))
    pack = replace(loaded, samples=loaded.samples[:2])
    observations = (
        RuntimeObservation(
            runtime="interpreter",
            sample_id=pack.samples[0].id,
            success=True,
            output={"lines": [{"lineNumber": 1}, {"lineNumber": 2}]},
        ),
        RuntimeObservation(
            runtime="interpreter",
            sample_id=pack.samples[1].id,
            success=False,
            error_code="TYPE_MISMATCH",
        ),
    )
    passed, total, issues = _invariant_counts(pack, observations)
    assert passed == 1
    assert total == 2
    assert len(issues) == 1
    assert issues[0].sample_id == pack.samples[1].id
