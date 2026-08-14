"""Provider-kind registry for provider-neutral model transports."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.model_config import ProviderKind, ResolvedModel
from open_mapping.providers.transports.anthropic import AnthropicTransport
from open_mapping.providers.transports.base import TransportFactory
from open_mapping.providers.transports.custom_http import CustomHttpTransport
from open_mapping.providers.transports.google import GoogleTransport
from open_mapping.providers.transports.openai import OpenAITransport
from open_mapping.providers.transports.openai_compatible import OpenAICompatibleTransport


def _require_kind(resolved_model: ResolvedModel, provider_kind: ProviderKind) -> None:
    if resolved_model.provider.kind is not provider_kind:
        raise OpenMappingError(
            (
                Issue(
                    code=IssueCode.PROVIDER_FAILURE,
                    severity=Severity.ERROR,
                    component="providers.registry",
                    message="configured provider kind does not match the selected transport factory",
                    correction="Select the factory registered for the configured provider kind.",
                ),
            )
        )


def _openai_factory(resolved_model: ResolvedModel) -> OpenAITransport:
    _require_kind(resolved_model, ProviderKind.OPENAI)
    return OpenAITransport(resolved_model)


def _anthropic_factory(resolved_model: ResolvedModel) -> AnthropicTransport:
    _require_kind(resolved_model, ProviderKind.ANTHROPIC)
    return AnthropicTransport(resolved_model)


def _google_factory(resolved_model: ResolvedModel) -> GoogleTransport:
    _require_kind(resolved_model, ProviderKind.GOOGLE)
    return GoogleTransport(resolved_model)


def _openai_compatible_factory(resolved_model: ResolvedModel) -> OpenAICompatibleTransport:
    _require_kind(resolved_model, ProviderKind.OPENAI_COMPATIBLE)
    return OpenAICompatibleTransport(resolved_model)


def _custom_http_factory(resolved_model: ResolvedModel) -> CustomHttpTransport:
    _require_kind(resolved_model, ProviderKind.CUSTOM_HTTP)
    return CustomHttpTransport(resolved_model)


def build_transport_registry() -> Mapping[ProviderKind, TransportFactory]:
    """Return exactly one provider-neutral transport factory for each provider kind."""

    return MappingProxyType(
        {
            ProviderKind.OPENAI: _openai_factory,
            ProviderKind.ANTHROPIC: _anthropic_factory,
            ProviderKind.GOOGLE: _google_factory,
            ProviderKind.OPENAI_COMPATIBLE: _openai_compatible_factory,
            ProviderKind.CUSTOM_HTTP: _custom_http_factory,
        }
    )


__all__ = ["build_transport_registry"]
