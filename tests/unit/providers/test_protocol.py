"""Typed provider protocol and disclosure tests."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from open_mapping.matching.profiles import FieldProfile
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.model.suggestions import MatchCandidate
from open_mapping.providers import protocol
from open_mapping.providers.protocol import ProviderProposal, ProviderRequest, ProviderResponse
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _request(target: str = "/result") -> ProviderRequest:
    candidates = (
        MatchCandidate(source_path="/first", target_path=target, raw_score=0.8),
        MatchCandidate(source_path="/second", target_path=target, raw_score=0.7),
    )
    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="source",
        target_schema_id="target",
        target_path=target,
        candidates=candidates,
        source_field_metadata=(),
        target_field_metadata=SchemaField(
            pointer=target, types=frozenset({JsonType.STRING}), required=True
        ),
        sample_profiles=(),
    )


def test_protocol_accepts_abstention() -> None:
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(ProviderProposal(target_path="/result", abstain=True, reason="unclear"),),
    )
    protocol.validate_provider_response(response, _request())


def test_protocol_rejects_abstention_with_selection() -> None:
    with pytest.raises(ValidationError, match="abstain"):
        ProviderProposal(
            target_path="/result",
            abstain=True,
            selected_source_paths=("/first",),
            expression={"op": "get", "path": "/first"},
        )


@pytest.mark.parametrize(
    "proposal, message",
    [
        (ProviderProposal(target_path="/wrong", abstain=True), "different target"),
        (
            ProviderProposal(
                target_path="/result", abstain=False, selected_source_paths=("/outside",)
            ),
            "outside the candidate set",
        ),
        (
            ProviderProposal(
                target_path="/result",
                abstain=False,
                selected_source_paths=("/first",),
                expression={"op": "get", "path": "/outside"},
            ),
            "outside the candidate set",
        ),
    ],
)
def test_protocol_rejects_unbounded_proposals(proposal: ProviderProposal, message: str) -> None:
    response = ProviderResponse(protocol_version="0.1", proposals=(proposal,))
    with pytest.raises(Exception, match=message):
        protocol.validate_provider_response(response, _request())


def test_protocol_rejects_unknown_operation_and_authority_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderResponse.model_validate(
            {
                "protocol_version": "0.1",
                "proposals": [
                    {
                        "target_path": "/result",
                        "abstain": False,
                        "expression": {"op": "shell", "command": "whoami"},
                        "confidence_band": "high",
                        "disposition": "suggested",
                        "review_state": "accepted",
                        "verified": True,
                    }
                ],
            }
        )


def test_code_like_literal_remains_inert_data() -> None:
    value = "__import__('os').system('whoami'); DROP TABLE mappings;"
    proposal = ProviderProposal(
        target_path="/result",
        abstain=False,
        expression={"op": "literal", "value": value},
        reason="literal",
    )
    assert proposal.expression is not None
    assert proposal.expression.model_dump(mode="json") == {"op": "literal", "value": value}


def test_aggregate_disclosure_is_sorted_deterministic_and_additive() -> None:
    profile = FieldProfile(
        pointer="/first",
        observed_types=frozenset({JsonType.STRING}),
        sample_count=1,
        missing_count=0,
        null_count=0,
        distinct_count=1,
    )
    first = _request("/z").model_copy(update={"sample_profiles": (profile,)})
    second = _request("/a").model_copy(update={"sample_profiles": (profile,)})
    disclosure = protocol.aggregate_provider_disclosure(
        endpoint_origin="provider.example",
        raw_samples_included=False,
        requests=((first, 2), (second, 3)),
    )
    bundle: list[object] = [second.model_dump(mode="json"), first.model_dump(mode="json")]
    assert disclosure.source_field_count == 0
    assert disclosure.candidate_count == 4
    assert disclosure.sample_profile_count == 2
    assert disclosure.redaction_count == 5
    assert disclosure.request_sha256 == hashlib.sha256(canonical_json_bytes(bundle)).hexdigest()
