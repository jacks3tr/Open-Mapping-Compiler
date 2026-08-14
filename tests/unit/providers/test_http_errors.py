"""HTTP provider error handling tests."""

from __future__ import annotations

from typing import Any

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.schema import JsonType, SchemaField
from open_mapping.providers.http import _validate_response, call_http_provider
from open_mapping.providers.protocol import (
    ProviderProposal,
    ProviderRequest,
    ProviderResponse,
)


def _request() -> ProviderRequest:
    return ProviderRequest(
        protocol_version="0.1",
        task="rerank-and-propose",
        source_schema_id="s",
        target_schema_id="t",
        target_path="/a",
        candidates=(),
        source_field_metadata=(),
        target_field_metadata=SchemaField(
            pointer="/a", types=frozenset({JsonType.STRING}), required=True
        ),
        sample_profiles=(),
    )


def test_validate_response_rejects_expression_path() -> None:
    request = _request()
    response = ProviderResponse(
        protocol_version="0.1",
        proposals=(
            ProviderProposal(
                target_path="/a",
                abstain=False,
                expression={"op": "get", "path": "/outside"},
            ),
        ),
    )
    with pytest.raises(OpenMappingError):
        _validate_response(response, request)


def test_http_provider_missing_token() -> None:
    with pytest.raises(OpenMappingError):
        call_http_provider(
            "https://example.com",
            token_env="OPEN_MAPPING_DOES_NOT_EXIST_TOKEN",
            request=_request(),
            allow_raw_samples=False,
        )


def test_http_provider_oversized_body(monkeypatch: Any) -> None:
    monkeypatch.setattr("open_mapping.providers.http._MAX_BODY", 1)
    with pytest.raises(OpenMappingError):
        call_http_provider(
            "https://example.com",
            token_env=None,
            request=_request(),
            allow_raw_samples=False,
        )
