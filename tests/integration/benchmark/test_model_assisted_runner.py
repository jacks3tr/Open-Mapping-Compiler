"""Offline end-to-end model comparison benchmark coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from open_mapping.benchmark.loader import load_benchmark_pack
from open_mapping.benchmark.runner import persist_model_comparison, run_benchmark_pack
from open_mapping.cli.models import CliModelSelection, model_config_sha256
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ModelProviderConfig, ProviderKind
from open_mapping.model.model_protocol import MappingContextPackage, mapping_context_sha256
from open_mapping.providers.config import resolve_model
from open_mapping.providers.protocol import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResult,
)
from open_mapping.providers.transports.base import normalized_model_payload
from open_mapping.serialization.canonical_json import canonical_json_bytes


class _ShapeFakeTransport:
    """Normalize three provider envelopes without network or credentials."""

    def __init__(self, shape: str, truth: dict[str, JsonValue]) -> None:
        self.shape = shape
        self.truth = truth

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        package = MappingContextPackage.model_validate_json(request.prompt.user_payload_json)
        proposals = [
            {
                "target_path": item.target.pointer,
                "action": "propose",
                "selected_source_paths": _input_paths(self.truth[item.target.pointer]),
                "expression": self.truth[item.target.pointer],
                "reason": "Deterministic benchmark fake.",
                "evidence": ["fixture truth"],
            }
            for item in package.target_requests
        ]
        payload: JsonValue = {
            "protocol_version": "0.1",
            "prompt_version": package.prompt_version,
            "context_sha256": mapping_context_sha256(package),
            "batch_id": package.batch_id,
            "proposals": proposals,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        if self.shape == "openai":
            envelope: object = {
                "output": [{"content": [{"type": "output_text", "text": serialized}]}]
            }
            raw = cast(dict[str, object], envelope)["output"]
            text = cast(list[dict[str, object]], raw)[0]["content"]
            normalized = normalized_model_payload(
                cast(list[dict[str, object]], text)[0]["text"], component="tests.fake.openai"
            )
        elif self.shape == "anthropic":
            envelope = {
                "content": [
                    {"type": "tool_use", "name": "submit_mapping_response", "input": payload}
                ]
            }
            raw = cast(dict[str, object], envelope)["content"]
            normalized = normalized_model_payload(
                cast(list[dict[str, object]], raw)[0]["input"], component="tests.fake.anthropic"
            )
        else:
            envelope = {"candidates": [{"content": {"parts": [{"text": serialized}]}}]}
            raw = cast(dict[str, object], envelope)["candidates"]
            content = cast(dict[str, object], cast(list[dict[str, object]], raw)[0]["content"])
            normalized = normalized_model_payload(
                cast(list[dict[str, object]], content["parts"])[0]["text"],
                component="tests.fake.google",
            )
        import hashlib

        return ModelTransportResult(
            payload=normalized,
            provider_request_id=None,
            usage={"input_tokens": 11, "output_tokens": 7},
            latency_ms=13,
            response_sha256=hashlib.sha256(canonical_json_bytes(normalized)).hexdigest(),
        )


def _input_paths(value: JsonValue) -> list[str]:
    paths: set[str] = set()
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("op") == "get" and item.get("document", "input") == "input":
                paths.add(cast(str, item["path"]))
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return sorted(paths)


def _selection(kind: ProviderKind) -> CliModelSelection:
    provider: dict[str, object] = {"kind": kind.value}
    if kind in {ProviderKind.OPENAI, ProviderKind.ANTHROPIC, ProviderKind.GOOGLE}:
        provider["api_key_env"] = "UNUSED_BENCHMARK_FAKE_KEY"
    else:
        provider["base_url"] = "http://127.0.0.1:9"
    config = ModelProviderConfig.model_validate(
        {
            "config_version": "0.1",
            "providers": {"offline": provider},
            "models": {
                "mapper": {
                    "provider": "offline",
                    "model_id": "deterministic-fake",
                    "context_mode": "full",
                    "target_batch_size": 25,
                }
            },
        }
    )
    return CliModelSelection(
        config=config,
        resolved_model=resolve_model(config, "mapper"),
        config_sha256=model_config_sha256(config),
    )


@pytest.mark.parametrize(
    ("shape", "kind"),
    (
        ("openai", ProviderKind.OPENAI),
        ("anthropic", ProviderKind.ANTHROPIC),
        ("google", ProviderKind.GOOGLE),
    ),
)
def test_runner_compares_same_proposals_from_three_provider_shapes(
    tmp_path: Path, shape: str, kind: ProviderKind
) -> None:
    pack_path = Path("benchmarks/account-segments")
    pack = load_benchmark_pack(pack_path)
    truth = {
        rule.target: cast(JsonValue, rule.expression.model_dump(mode="json"))
        for rule in pack.expected_mapping.rules
    }
    selection = _selection(kind)

    def factory(_resolved: object) -> ModelTransport:
        return _ShapeFakeTransport(shape, truth)

    result_dir = tmp_path / shape
    run = run_benchmark_pack(
        pack_path,
        enforce_gates=True,
        result_dir=result_dir,
        model_selection=selection,
        model_registry={kind: factory},
    )

    assert not run.gate_issues
    assert len(run.model_results) == 1
    model_result = next(iter(run.model_results.values()))
    assert model_result.metrics.model_response_validity_rate == 1.0
    assert model_result.metrics.model_proposal_static_validity_rate == 1.0
    assert model_result.metrics.model_direct_match_precision == 1.0
    assert model_result.metrics.model_direct_match_recall == 1.0
    assert model_result.metrics.model_transformation_exact_match_rate == 1.0
    assert model_result.metrics.model_full_mapping_completion_rate == 1.0
    assert model_result.metrics.model_input_tokens == 11
    assert model_result.metrics.model_output_tokens == 7
    assert model_result.metrics.model_latency_ms == 13
    assert len(model_result.batch_runs[0].context_sha256) == 64
    assert model_result.batch_runs[0].response_sha256

    serialized = (result_dir / "benchmark.json").read_text(encoding="utf-8")
    markdown = (result_dir / "benchmark.md").read_text(encoding="utf-8")
    assert "raw_samples" not in serialized
    assert "proposals" not in serialized
    assert "provider response" not in serialized.lower()
    assert "## Model comparison" in markdown
    assert "descriptive" in markdown.lower()

    comparison_dir = tmp_path / "saved-comparison"
    persist_model_comparison((run,), comparison_dir)
    second = model_result.model_copy(update={"model_alias": "second-alias"})
    run.model_results = {second.comparison_key: second}
    comparison_json, comparison_markdown = persist_model_comparison((run,), comparison_dir)
    comparison = json.loads(comparison_json.read_text(encoding="utf-8"))
    assert len(comparison["packs"][run.id]) == 2
    assert "statistical generalization" in comparison["scope_statement"]
    assert "statistical generalization" in comparison_markdown.read_text(encoding="utf-8")


def test_model_options_do_not_change_baseline_gates(tmp_path: Path) -> None:
    pack_path = Path("benchmarks/account-segments")
    baseline = run_benchmark_pack(pack_path, enforce_gates=True, result_dir=tmp_path / "baseline")
    pack = load_benchmark_pack(pack_path)
    truth = {
        rule.target: cast(JsonValue, rule.expression.model_dump(mode="json"))
        for rule in pack.expected_mapping.rules
    }
    selection = _selection(ProviderKind.OPENAI)

    def factory(_resolved: object) -> ModelTransport:
        return _ShapeFakeTransport("openai", truth)

    modeled = run_benchmark_pack(
        pack_path,
        enforce_gates=True,
        result_dir=tmp_path / "modeled",
        model_selection=selection,
        model_registry={ProviderKind.OPENAI: factory},
    )

    assert modeled.metrics == baseline.metrics
    assert modeled.gate_issues == baseline.gate_issues
    assert modeled.numerators == baseline.numerators
    assert modeled.denominators == baseline.denominators
