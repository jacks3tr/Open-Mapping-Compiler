"""Strict models for configured model providers and aliases."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Self, TypeAlias
from urllib.parse import urlparse

from pydantic import Field, StringConstraints, field_validator, model_validator

from open_mapping.model.json_types import OpenMappingModel

_ENVIRONMENT_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_NATIVE_PROVIDER_KINDS = frozenset(("openai", "anthropic", "google"))
_BASE_URL_PROVIDER_KINDS = frozenset(("openai-compatible", "custom-http"))
_LITERAL_CREDENTIAL_FIELDS = frozenset(("api_key", "token", "authorization", "secret"))

NonEmptyText: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProviderKind(StrEnum):
    """Provider transport families supported by the model configuration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI_COMPATIBLE = "openai-compatible"
    CUSTOM_HTTP = "custom-http"


class StructuredOutputMode(StrEnum):
    """Requested structured-output mechanism for a configured model."""

    AUTO = "auto"
    JSON_SCHEMA = "json-schema"
    TOOL = "tool"
    JSON = "json"


class ContextMode(StrEnum):
    """Requested source-schema context packing strategy."""

    AUTO = "auto"
    FULL = "full"
    TARGETED = "targeted"


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_environment_variable_name(value: str) -> str:
    if not _ENVIRONMENT_VARIABLE_NAME.fullmatch(value):
        raise ValueError("must be an environment variable name")
    return value


def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("base_url must include a valid port") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(
            "base_url must not contain a query string or fragment, including a credential query parameter"
        )
    if parsed.hostname is None:
        raise ValueError("base_url must include a host")
    if port == 0:
        raise ValueError("base_url must not use port 0")
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and _is_loopback(parsed.hostname):
        return value
    raise ValueError("base_url must use HTTPS or loopback HTTP")


def _reject_literal_credential_fields(value: object, *, inspect_keys: bool = True) -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if (
                inspect_keys
                and isinstance(key, str)
                and key.casefold() in _LITERAL_CREDENTIAL_FIELDS
            ):
                raise ValueError(
                    f"literal credential field {key!r} is not allowed; use an environment variable name"
                )
            nested_keys_are_fields = key not in {"providers", "models", "headers_from_env"}
            _reject_literal_credential_fields(nested_value, inspect_keys=nested_keys_are_fields)
    elif isinstance(value, list):
        for item in value:
            _reject_literal_credential_fields(item, inspect_keys=inspect_keys)


class ProviderDefinition(OpenMappingModel):
    """One named connection to a model provider."""

    kind: ProviderKind
    base_url: NonEmptyText | None = None
    api_key_env: NonEmptyText | None = None
    headers_from_env: dict[NonEmptyText, NonEmptyText] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=1, ge=0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_base_url(value)

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_environment_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_environment_variable_name(value)

    @field_validator("headers_from_env")
    @classmethod
    def validate_header_environment_names(cls, value: dict[str, str]) -> dict[str, str]:
        for header_name, environment_name in value.items():
            if "\r" in header_name or "\n" in header_name:
                raise ValueError("header names must not contain line breaks")
            _validate_environment_variable_name(environment_name)
        return value

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> Self:
        if self.kind.value in _NATIVE_PROVIDER_KINDS and self.api_key_env is None:
            raise ValueError(
                f"api_key_env is required for native provider kind {self.kind.value!r}"
            )
        if self.kind.value in _BASE_URL_PROVIDER_KINDS and self.base_url is None:
            raise ValueError(f"base_url is required for provider kind {self.kind.value!r}")
        return self


class ModelParameters(OpenMappingModel):
    """Optional provider-neutral model sampling parameters."""

    temperature: float | None = Field(default=None, allow_inf_nan=False)
    top_p: float | None = Field(default=None, allow_inf_nan=False)
    seed: int | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


class ModelDefinition(OpenMappingModel):
    """A named model alias and its provider-neutral invocation settings."""

    provider: NonEmptyText
    model_id: NonEmptyText
    structured_output: StructuredOutputMode = StructuredOutputMode.AUTO
    context_mode: ContextMode = ContextMode.AUTO
    input_token_budget: int = Field(default=64000, gt=0)
    max_output_tokens: int = Field(default=12000, gt=0)
    target_batch_size: int = Field(default=25, gt=0)
    candidate_limit_per_target: int = Field(default=20, gt=0)
    parameters: ModelParameters = Field(default_factory=ModelParameters)


class ModelProviderConfig(OpenMappingModel):
    """The complete versioned provider and model-alias configuration."""

    config_version: Literal["0.1"]
    providers: dict[NonEmptyText, ProviderDefinition]
    models: dict[NonEmptyText, ModelDefinition]

    @model_validator(mode="before")
    @classmethod
    def reject_literal_credentials(cls, value: object) -> object:
        _reject_literal_credential_fields(value)
        return value

    @model_validator(mode="after")
    def validate_model_provider_references(self) -> Self:
        for alias, model in self.models.items():
            if model.provider not in self.providers:
                raise ValueError(
                    f"model alias {alias!r} references unknown provider {model.provider!r}"
                )
        return self


class ResolvedModel(OpenMappingModel):
    """A selected model alias without any resolved credential value."""

    alias: NonEmptyText
    provider_name: NonEmptyText
    provider: ProviderDefinition
    model: ModelDefinition
