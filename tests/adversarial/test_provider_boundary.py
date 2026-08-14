"""Adversarial bounded provider-assistance and CLI failure tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.cli.app import app
from open_mapping.matching import proposals
from open_mapping.model.hints import DirectHint, MappingHints
from open_mapping.model.issues import Severity
from open_mapping.model.providers import ProviderDisclosure
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    MatchCandidate,
    SuggestionDisposition,
    SuggestionReport,
    TargetCandidateSet,
)
from open_mapping.providers.protocol import (
    ProviderCallResult,
    ProviderProposal,
    ProviderRequest,
    ProviderResponse,
)


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["alpha", "beta", "manual"],
            "properties": {
                "alpha": {"type": "string"},
                "beta": {"type": "string"},
                "manual": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["result", "manual", "missing"],
            "properties": {
                "result": {"type": "string"},
                "manual": {"type": "string"},
                "missing": {"type": "integer"},
            },
        },
        schema_id=None,
        source_uri="target",
    )
    return source, target


def _baseline() -> tuple[SchemaDocument, SchemaDocument, SuggestionReport]:
    source, target = _schemas()
    sets = (
        TargetCandidateSet(
            target_path="/result",
            candidates=(
                MatchCandidate(source_path="/alpha", target_path="/result", raw_score=0.91),
                MatchCandidate(source_path="/beta", target_path="/result", raw_score=0.75),
            ),
        ),
        TargetCandidateSet(
            target_path="/manual",
            candidates=(
                MatchCandidate(source_path="/manual", target_path="/manual", raw_score=1.0),
            ),
        ),
        TargetCandidateSet(target_path="/missing", candidates=()),
    )
    hints = MappingHints(
        hints_version="0.1",
        id="manual-authority",
        direct=(DirectHint(target="/manual", source="/manual", reason="authority"),),
    )
    report = proposals.build_deterministic_suggestions(
        source, target, candidate_sets=sets, hints=hints
    )
    return source, target, report


def test_useful_existing_candidate_nomination_reranks_without_editing_score() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/beta",),
                expression={"op": "get", "path": "/beta"},
                reason="semantic role",
            ),
        ),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    result = next(item for item in assisted.suggestions if item.target_path == "/result")
    assert result.selected_source_path == "/beta"
    assert result.confidence_score == 0.75
    assert result.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert [candidate.raw_score for candidate in result.candidates] == [0.91, 0.75]


def test_abstention_partial_output_and_missing_response_preserve_all_baselines() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(ProviderProposal(target_path="/result", abstain=True),),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    assert len(assisted.suggestions) == len(baseline.suggestions) == 3
    assert assisted.summary.no_match == 1
    assert assisted.summary.manual == 1
    assert assisted.suggestions == baseline.suggestions


def test_provider_cannot_override_manual_hint() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/manual",
                abstain=False,
                selected_source_paths=("/alpha",),
                expression={"op": "get", "path": "/alpha"},
            ),
        ),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/manual": response}
    )
    manual = next(item for item in assisted.suggestions if item.target_path == "/manual")
    assert manual.disposition == SuggestionDisposition.MANUAL
    assert manual.selected_source_path == "/manual"


def test_invalid_static_expression_falls_back_with_warning() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/alpha",),
                expression={"op": "literal", "value": 123},
            ),
        ),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    assert assisted.suggestions == baseline.suggestions
    assert assisted.issues[-1].severity == Severity.WARNING


def test_in_set_selection_with_out_of_set_get_path_is_rejected_by_library() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/alpha",),
                expression={"op": "get", "path": "/manual"},
            ),
        ),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    assert assisted.suggestions == baseline.suggestions
    assert assisted.issues[-1].severity == Severity.WARNING


def test_complex_expression_is_recorded_but_never_autoassembled() -> None:
    source, target, baseline = _baseline()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/alpha", "/beta"),
                expression={
                    "op": "concat",
                    "operands": [
                        {"op": "get", "path": "/alpha"},
                        {"op": "get", "path": "/beta"},
                    ],
                },
                reason="combine",
            ),
        ),
    )
    assisted = proposals.apply_provider_assistance(
        baseline, source_schema=source, target_schema=target, responses={"/result": response}
    )
    item = next(value for value in assisted.suggestions if value.target_path == "/result")
    original = next(value for value in baseline.suggestions if value.target_path == "/result")
    assert item.expression == original.expression
    assert any(evidence.kind.value == "model_rerank" for evidence in item.evidence)


def _write_cli_inputs(tmp_path: Path, *, valid_sample: bool = True) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    samples = tmp_path / "samples.jsonl"
    source.write_text(
        json.dumps(
            {
                "$id": "source",
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    target.write_text(
        json.dumps(
            {
                "$id": "target",
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    sample_value: object = "ok" if valid_sample else 42
    samples.write_text(
        json.dumps({"id": "one", "input": {"value": sample_value}}) + "\n",
        encoding="utf-8",
    )
    return source, target, samples


def test_samples_are_validated_before_any_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, samples = _write_cli_inputs(tmp_path, valid_sample=False)
    called = False

    def forbidden_call(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("open_mapping.providers.http.call_http_provider", forbidden_call)
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(source),
            str(target),
            "--samples",
            str(samples),
            "--provider-url",
            "http://127.0.0.1:9",
        ],
    )
    assert result.exit_code == 2
    assert not called
    assert "SOURCE_SCHEMA_VALIDATION" in result.output
    assert "Traceback" not in result.output


def test_valid_samples_are_profiled_and_disclosed_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, samples = _write_cli_inputs(tmp_path)
    captured: list[ProviderRequest] = []

    def abstaining_call(
        url: str,
        *,
        token_env: str | None,
        request: ProviderRequest,
        allow_raw_samples: bool,
    ) -> ProviderCallResult:
        captured.append(request)
        return ProviderCallResult(
            response=ProviderResponse(
                protocol_version="0.1",
                proposals=(ProviderProposal(target_path=request.target_path, abstain=True),),
            ),
            disclosure=ProviderDisclosure(
                endpoint_origin="127.0.0.1:9",
                raw_samples_included=False,
                source_field_count=1,
                candidate_count=1,
                sample_profile_count=1,
                redaction_count=0,
                request_sha256="unused",
            ),
        )

    monkeypatch.setattr("open_mapping.providers.http.call_http_provider", abstaining_call)
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(source),
            str(target),
            "--samples",
            str(samples),
            "--provider-url",
            "http://127.0.0.1:9",
            "--report-format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured[0].sample_profiles[0].pattern_classes == ("lowercase-word",)
    assert "ok" not in str(captured[0].sample_profiles)
    disclosure = json.loads(result.output)["provider_disclosure"]
    assert disclosure["source_field_count"] == 1
    assert disclosure["candidate_count"] == 1
    assert disclosure["sample_profile_count"] == 1


def test_optional_failure_warns_and_writes_baseline_artifact(tmp_path: Path) -> None:
    source, target, samples = _write_cli_inputs(tmp_path)
    suggestions = tmp_path / "suggestions.json"
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(source),
            str(target),
            "--samples",
            str(samples),
            "--provider-url",
            "http://127.0.0.1:9",
            "--suggestions-out",
            str(suggestions),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "warning: PROVIDER_FAILURE" in result.output
    assert suggestions.exists()


def test_required_failure_is_error_exit_five_and_writes_no_artifacts(tmp_path: Path) -> None:
    source, target, samples = _write_cli_inputs(tmp_path)
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "mapping.yaml"
    result = CliRunner().invoke(
        app,
        [
            "suggest",
            str(source),
            str(target),
            "--samples",
            str(samples),
            "--provider-url",
            "http://127.0.0.1:9",
            "--require-provider",
            "--suggestions-out",
            str(suggestions),
            "--mapping-out",
            str(mapping),
            "--mapping-id",
            "blocked",
        ],
    )
    assert result.exit_code == 5
    assert "error: PROVIDER_FAILURE" in result.output
    assert not suggestions.exists()
    assert not mapping.exists()
