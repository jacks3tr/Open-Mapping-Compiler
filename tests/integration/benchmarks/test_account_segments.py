"""Account-segment fixture and string-semantics contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.generate_benchmark_samples import render_samples

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.issues import IssueCode
from open_mapping.runtime import run_mapping


def test_account_negative_fixtures_lengths_and_generator_bytes(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("account-segments")
    assert Path("benchmarks/account-segments/samples.jsonl").read_text(
        encoding="utf-8"
    ) == render_samples("account-segments")
    errors = {sample.id: sample.expected_error for sample in pack.samples if sample.expected_error}
    assert errors == {
        "account-segments-missing-segment": IssueCode.SOURCE_SCHEMA_VALIDATION.value,
        "account-segments-malformed-length": IssueCode.SOURCE_SCHEMA_VALIDATION.value,
    }
    assert {invariant.id for invariant in pack.expected_mapping.invariants} == {
        "company-length",
        "cost-center-length",
        "account-length",
    }


def test_account_leading_zeroes_remain_strings_without_numeric_cast(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("account-segments")
    sample = next(sample for sample in pack.samples if sample.id == "account-segments-leading-zero")
    output = run_mapping(
        pack.expected_mapping,
        source_schema=pack.source_schema,
        target_schema=pack.target_schema,
        source=sample.input,
    )
    assert output == sample.expected
    assert isinstance(output, dict)
    assert output["company"] == "000001"
    assert output["costCenter"] == "000004-000005"
    assert output["account"] == "000007000008000009"
    assert all(isinstance(output[key], str) for key in ("company", "costCenter", "account"))


def test_account_benchmark_passes_all_gates_and_negative_contracts(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/account-segments"),
        enforce_gates=True,
        result_dir=tmp_path / "account-segments",
    )
    assert not run.gate_issues
    negatives = [
        item
        for item in run.runtime_observations
        if "missing-segment" in item.sample_id or "malformed-length" in item.sample_id
    ]
    assert len(negatives) == 6
    assert {item.error_code for item in negatives} == {IssueCode.SOURCE_SCHEMA_VALIDATION.value}
    positives = [item for item in run.runtime_observations if item not in negatives]
    assert len(positives) == 240
    assert all(item.success and item.output is not None for item in positives)
    assert run.metrics.cross_runtime_equivalence == 1.0
