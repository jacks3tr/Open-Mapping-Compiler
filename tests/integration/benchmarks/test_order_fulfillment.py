"""Order-fulfillment nested-map and resource contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.generate_benchmark_samples import render_samples

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.issues import IssueCode


def test_order_fixture_line_matrix_units_negatives_and_bytes(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("order-fulfillment")
    assert Path("benchmarks/order-fulfillment/samples.jsonl").read_text(
        encoding="utf-8"
    ) == render_samples("order-fulfillment")
    positives = [sample for sample in pack.samples if sample.expected_error is None]
    positive_items: list[list[object]] = []
    for sample in positives:
        sample_input = sample.input
        assert isinstance(sample_input, dict)
        items = sample_input["items"]
        assert isinstance(items, list)
        positive_items.append(items)
    assert {len(items) for items in positive_items} == set(range(1, 21))
    units: set[object] = set()
    for items in positive_items:
        for line in items:
            assert isinstance(line, dict)
            units.add(line["unit"])
    assert units == {"EA", "DZ"}
    negatives = {sample.id: sample for sample in pack.samples if sample.expected_error}
    limited_input = negatives["order-fulfillment-array-limit"].input
    assert isinstance(limited_input, dict)
    limited_items = limited_input["items"]
    assert isinstance(limited_items, list)
    assert len(limited_items) == 10_001
    assert (
        negatives["order-fulfillment-array-limit"].expected_error
        == IssueCode.EVALUATION_LIMIT_EXCEEDED.value
    )
    assert (
        negatives["order-fulfillment-duplicate-line"].expected_error
        == IssueCode.INVARIANT_FAILED.value
    )


def test_order_uniqueness_invariant_extracts_line_numbers(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("order-fulfillment")
    invariant = next(
        item for item in pack.expected_mapping.invariants if item.id == "unique-line-numbers"
    )
    assert invariant.assertion.op == "unique"
    value = invariant.assertion.value.model_dump(mode="json")
    assert value == {
        "op": "map",
        "collection": {"op": "get", "path": "/lines", "document": "output"},
        "expression": {"op": "get", "path": "/lineNumber", "document": "current"},
    }


def test_order_benchmark_passes_all_gates_and_negative_contracts(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/order-fulfillment"),
        enforce_gates=True,
        result_dir=tmp_path / "order-fulfillment",
    )
    assert not run.gate_issues
    limit = [
        item
        for item in run.runtime_observations
        if item.sample_id == "order-fulfillment-array-limit"
    ]
    duplicate = [
        item
        for item in run.runtime_observations
        if item.sample_id == "order-fulfillment-duplicate-line"
    ]
    assert {item.error_code for item in limit} == {IssueCode.EVALUATION_LIMIT_EXCEEDED.value}
    assert {item.error_code for item in duplicate} == {IssueCode.INVARIANT_FAILED.value}
    positives = [item for item in run.runtime_observations if item not in limit + duplicate]
    assert len(positives) == 210
    assert all(item.success and item.output is not None for item in positives)
    assert run.metrics.invariant_pass_rate == 1.0
    assert run.metrics.cross_runtime_equivalence == 1.0
