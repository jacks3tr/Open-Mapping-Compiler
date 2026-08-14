"""Compatibility transport that adapts the guarded legacy custom HTTP protocol."""

from __future__ import annotations

import hashlib
from time import monotonic
from typing import cast

from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ResolvedModel
from open_mapping.model.model_protocol import (
    MappingContextPackage,
    ModelFieldSummary,
    ModelMappingResponse,
    ModelProposalAction,
    ModelTargetProposal,
    mapping_context_sha256,
)
from open_mapping.model.schema import SchemaField
from open_mapping.model.suggestions import MatchCandidate
from open_mapping.providers.http import call_http_provider
from open_mapping.providers.protocol import (
    ModelTransportRequest,
    ModelTransportResult,
    ModelUsage,
    ProviderProposal,
    ProviderRequest,
)
from open_mapping.providers.transports.base import (
    bounded_retry_count,
    provider_timeout_seconds,
    resolve_transport_credentials,
)
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _transport_error(message: str, correction: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.PROVIDER_RESPONSE_INVALID,
                severity=Severity.ERROR,
                component="providers.transports.custom_http",
                message=message,
                correction=correction,
            ),
        )
    )


def _context_package(request: ModelTransportRequest) -> MappingContextPackage:
    try:
        return MappingContextPackage.model_validate_json(request.prompt.user_payload_json)
    except (ValidationError, ValueError) as exc:
        raise _transport_error(
            "custom HTTP model prompt contains an invalid context package",
            "Build the prompt from a valid mapping context package.",
        ) from exc


def _schema_field(summary: ModelFieldSummary) -> SchemaField:
    try:
        summary_payload = cast(dict[str, object], summary.model_dump(mode="json"))
        constraints = summary_payload.pop("constraints", {})
        if not isinstance(constraints, dict):
            raise TypeError("constraints must be an object")
        summary_payload.update(constraints)
        return SchemaField.model_validate(summary_payload)
    except (TypeError, ValidationError) as exc:
        raise _transport_error(
            "custom HTTP model context contains an invalid field summary",
            "Build the prompt from a valid mapping context package.",
        ) from exc


def _legacy_request(
    request: ModelTransportRequest,
    package: MappingContextPackage,
    target_index: int,
) -> ProviderRequest:
    target_request = package.target_requests[target_index]
    target_path = target_request.target.pointer
    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id=package.source_schema_id,
        target_schema_id=package.target_schema_id,
        target_path=target_path,
        candidates=tuple(
            MatchCandidate(
                source_path=candidate.source_path,
                target_path=target_path,
                raw_score=candidate.raw_score,
            )
            for candidate in target_request.candidates
        ),
        source_field_metadata=tuple(_schema_field(summary) for summary in package.source_fields),
        target_field_metadata=_schema_field(target_request.target),
        sample_profiles=package.sample_profiles,
        instruction_text=request.prompt.system_instruction,
        raw_samples=package.raw_samples,
        model_prompt=request.prompt,
    )


def _translate_proposal(proposal: ProviderProposal) -> ModelTargetProposal:
    return ModelTargetProposal(
        target_path=proposal.target_path,
        action=ModelProposalAction.ABSTAIN if proposal.abstain else ModelProposalAction.PROPOSE,
        selected_source_paths=proposal.selected_source_paths,
        expression=proposal.expression,
        reason=proposal.reason,
        evidence=tuple(item.detail[:300] for item in proposal.evidence[:8]),
    )


class CustomHttpTransport:
    """Bridge new model prompts through the existing bounded custom HTTP protocol."""

    def __init__(self, resolved_model: ResolvedModel) -> None:
        self._resolved_model = resolved_model

    def invoke(self, request: ModelTransportRequest) -> ModelTransportResult:
        """Translate each context target to one guarded legacy provider request."""

        if request.resolved_model != self._resolved_model:
            raise _transport_error(
                "custom HTTP model transport request does not match the configured model",
                "Build the transport from the same resolved model passed to invoke.",
            )
        provider = request.resolved_model.provider
        if provider.base_url is None:
            raise _transport_error(
                "custom HTTP model transport has no endpoint URL",
                "Configure a base_url for the custom HTTP provider.",
            )
        credentials = resolve_transport_credentials(request.resolved_model)
        package = _context_package(request)
        started = monotonic()
        proposals: list[ModelTargetProposal] = []
        for target_index in range(len(package.target_requests)):
            legacy_result = call_http_provider(
                provider.base_url,
                token_env=provider.api_key_env,
                request=_legacy_request(request, package, target_index),
                allow_raw_samples=package.raw_samples_included,
                headers=credentials.headers,
                timeout_seconds=provider_timeout_seconds(request.resolved_model),
                max_retries=bounded_retry_count(request.resolved_model),
            )
            if len(legacy_result.response.proposals) != 1:
                raise _transport_error(
                    "custom HTTP provider must return one proposal for each requested target",
                    "Return exactly one bounded proposal for the requested target.",
                )
            try:
                proposals.append(_translate_proposal(legacy_result.response.proposals[0]))
            except ValidationError as exc:
                raise _transport_error(
                    "custom HTTP provider returned an incompatible proposal",
                    "Return a proposal compatible with the shared model response schema.",
                ) from exc
        response = ModelMappingResponse(
            protocol_version=package.protocol_version,
            prompt_version=package.prompt_version,
            context_sha256=mapping_context_sha256(package),
            batch_id=package.batch_id,
            proposals=tuple(proposals),
        )
        payload = cast(JsonValue, response.model_dump(mode="json"))
        return ModelTransportResult(
            payload=payload,
            provider_request_id=None,
            usage=ModelUsage(input_tokens=None, output_tokens=None),
            latency_ms=max(0, round((monotonic() - started) * 1000)),
            response_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        )


__all__ = ["CustomHttpTransport"]
