"""End-to-end model draft review, verification, and compilation."""

from __future__ import annotations

from pathlib import Path

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.codegen.python import generate_python
from open_mapping.matching.proposals import (
    apply_model_mapping_responses,
    build_deterministic_suggestions,
)
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.model_config import ContextMode, ProviderKind
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelCandidateSummary,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelTargetProposal,
    ModelTargetRequest,
    mapping_context_sha256,
)
from open_mapping.model.providers import ModelBatchRun, ModelRunDisclosure, ModelUsage
from open_mapping.model.reviews import (
    AssemblyPolicy,
    ReviewAction,
    SuggestionReviewDecision,
    SuggestionReviewDocument,
)
from open_mapping.model.suggestions import MatchCandidate, TargetCandidateSet
from open_mapping.serialization.mappings import dump_mapping, load_mapping
from open_mapping.serialization.suggestions import suggestion_report_sha256
from open_mapping.verification.dynamic import VerificationSample, verify_samples


def test_accept_model_expression_write_verify_and_compile(tmp_path: Path) -> None:
    source = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "required": ["first", "last"],
            "properties": {
                "first": {"type": "string"},
                "last": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="source",
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["fullName"],
            "properties": {"fullName": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target",
    )
    candidate_set = TargetCandidateSet(
        target_path="/fullName",
        candidates=(
            MatchCandidate(source_path="/first", target_path="/fullName", raw_score=0.7),
            MatchCandidate(source_path="/last", target_path="/fullName", raw_score=0.65),
        ),
    )
    baseline = build_deterministic_suggestions(
        source,
        target,
        candidate_sets=(candidate_set,),
        hints=None,
    )
    package = MappingContextPackage(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        batch_id="batch-001",
        context_mode=ContextMode.TARGETED,
        source_schema_id=source.schema_id,
        source_schema_version=source.schema_version,
        target_schema_id=target.schema_id,
        target_schema_version=target.schema_version,
        source_fields=(
            ModelFieldSummary(pointer="/first", types=("string",), required=True),
            ModelFieldSummary(pointer="/last", types=("string",), required=True),
        ),
        target_requests=(
            ModelTargetRequest(
                target=ModelFieldSummary(pointer="/fullName", types=("string",), required=True),
                candidates=(
                    ModelCandidateSummary(source_path="/first", raw_score=0.7, evidence=()),
                    ModelCandidateSummary(source_path="/last", raw_score=0.65, evidence=()),
                ),
            ),
        ),
        sample_profiles=(),
        business_instructions=(),
        expression_operations=("get", "concat"),
        allowed_source_paths=("/first", "/last"),
        raw_samples=None,
    )
    response = ModelMappingResponse(
        protocol_version="0.1",
        prompt_version="mapping-agent-v1",
        context_sha256=mapping_context_sha256(package),
        batch_id=package.batch_id,
        proposals=(
            ModelTargetProposal.model_validate(
                {
                    "target_path": "/fullName",
                    "action": "propose",
                    "selected_source_paths": ["/first", "/last"],
                    "expression": {
                        "op": "concat",
                        "operands": [
                            {"op": "get", "path": "/first", "document": "input"},
                            {"op": "get", "path": "/last", "document": "input"},
                        ],
                        "separator": " ",
                    },
                    "reason": "Combine the two name components.",
                    "evidence": ["Both source fields are required strings."],
                }
            ),
        ),
    )
    disclosure = ModelRunDisclosure(
        model_alias="mapping-model",
        provider_name="local",
        provider_kind=ProviderKind.CUSTOM_HTTP,
        model_id="model-1",
        prompt_version="mapping-agent-v1",
        config_sha256="a" * 64,
        context_mode=ContextMode.TARGETED,
        raw_samples_included=False,
        redaction_count=0,
        batch_runs=(
            ModelBatchRun(
                batch_id=package.batch_id,
                context_sha256=mapping_context_sha256(package),
                response_sha256="b" * 64,
                response=response,
                issues=(),
                attempts=1,
                format_repairs=0,
                usage=ModelUsage(input_tokens=10, output_tokens=5),
                latency_ms=1,
            ),
        ),
    )
    report = apply_model_mapping_responses(
        baseline,
        source_schema=source,
        target_schema=target,
        packages=(package,),
        responses=(response,),
        disclosure=disclosure,
    )
    review = SuggestionReviewDocument(
        review_version="0.1",
        suggestion_report_sha256=suggestion_report_sha256(report),
        mapping_id="model-reviewed",
        decisions=(
            SuggestionReviewDecision(
                target_path="/fullName",
                action=ReviewAction.ACCEPT_SELECTED,
                reason="Approved after review.",
            ),
        ),
    )

    result = assemble_mapping(
        report,
        mapping_id="model-reviewed",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=True,
    )

    assert result.mapping is not None
    mapping_path = tmp_path / "mapping.json"
    dump_mapping(result.mapping, mapping_path)
    loaded = load_mapping(mapping_path)
    verification = verify_samples(
        loaded,
        source_schema=source,
        target_schema=target,
        samples=(
            VerificationSample(
                id="name",
                input={"first": "Ada", "last": "Lovelace"},
                expected={"fullName": "Ada Lovelace"},
            ),
        ),
    )
    assert verification.static.valid
    assert verification.samples[0].valid
    artifact = generate_python(loaded, source_schema=source, target_schema=target)
    code = compile(artifact.source, "generated_mapping.py", "exec")
    namespace: dict[str, object] = {}
    exec(code, namespace)
    transform = namespace["transform"]
    assert callable(transform)
    assert transform({"first": "Ada", "last": "Lovelace"}) == {"fullName": "Ada Lovelace"}
