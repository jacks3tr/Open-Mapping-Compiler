"""CRM-to-ERP role-aware matching contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.generate_benchmark_samples import render_samples

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.suggestions import SuggestionDisposition, SuggestionReport

PRIMARY_LEAVES = {
    "/primaryAddress/street",
    "/primaryAddress/city",
    "/primaryAddress/region",
    "/primaryAddress/postalCode",
    "/primaryAddress/country",
}


def test_crm_manifest_uses_leaf_mapping_units_and_role_invariants(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("crm-erp")
    assert set(pack.manifest.expected_ambiguous_targets) == PRIMARY_LEAVES
    assert "/primaryAddress" not in pack.target_units
    assert {invariant.id for invariant in pack.expected_mapping.invariants} == {
        "primary-address-is-ship-to",
        "billing-address-is-bill-to",
        "business-partner-is-customer",
        "payer-business-partner-is-payer",
    }
    assert Path("benchmarks/crm-erp/samples.jsonl").read_text(encoding="utf-8") == render_samples(
        "crm-erp"
    )


def test_crm_parent_roles_disambiguate_only_resolvable_leaves(
    load_pack: Callable[[str], BenchmarkPack],
    suggestion_reports: Callable[[BenchmarkPack], tuple[SuggestionReport, SuggestionReport]],
) -> None:
    pack = load_pack("crm-erp")
    baseline, _ = suggestion_reports(pack)
    by_target = {item.target_path: item for item in baseline.suggestions}
    assert all(
        by_target[target].disposition == SuggestionDisposition.AMBIGUOUS
        for target in PRIMARY_LEAVES
    )
    for suffix in ("street", "city", "region", "postalCode", "country"):
        billing = by_target[f"/billingAddress/{suffix}"]
        assert billing.disposition != SuggestionDisposition.AMBIGUOUS
        assert billing.selected_source_path == f"/billToAddress/{suffix}"
    assert by_target["/businessPartnerId"].selected_source_path == "/customerId"
    assert by_target["/payerBusinessPartnerId"].selected_source_path == "/payerId"
    unrelated = set(by_target).difference(PRIMARY_LEAVES)
    assert not all(
        by_target[target].disposition == SuggestionDisposition.AMBIGUOUS for target in unrelated
    )


def test_crm_benchmark_passes_all_gates_and_invariants(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/crm-erp"), enforce_gates=True, result_dir=tmp_path / "crm-erp"
    )
    assert not run.gate_issues
    assert run.metrics.invariant_pass_rate == 1.0
    assert run.metrics.cross_runtime_equivalence == 1.0
