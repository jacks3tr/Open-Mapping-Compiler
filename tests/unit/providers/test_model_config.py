"""Tests for the provider and model configuration contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from yaml.constructor import ConstructorError

from open_mapping.model.model_config import (
    ContextMode,
    ModelProviderConfig,
    StructuredOutputMode,
)
from open_mapping.providers.config import (
    load_model_provider_config,
    resolve_model,
    resolve_models_config_path,
)

_GOLDEN_CONFIG = Path("tests/golden/model_protocol/open-mapping.models.yaml")


def _valid_config() -> dict[str, Any]:
    return {
        "config_version": "0.1",
        "providers": {
            "native": {
                "kind": "openai",
                "api_key_env": "OPEN_MAPPING_NATIVE_API_KEY",
            },
            "local": {
                "kind": "custom-http",
                "base_url": "http://127.0.0.1:8080/v1",
            },
        },
        "models": {
            "accurate-mapper": {
                "provider": "native",
                "model_id": "synthetic-accurate-mapper",
            },
            "local-mapper": {
                "provider": "local",
                "model_id": "synthetic-local-mapper",
                "parameters": {"temperature": 0.25, "reasoning_effort": "high"},
            },
        },
    }


def test_loads_multi_provider_golden_config_with_contract_defaults() -> None:
    config = load_model_provider_config(_GOLDEN_CONFIG)

    assert tuple(config.providers) == ("native", "local")
    assert tuple(config.models) == ("accurate-mapper", "local-mapper")
    assert config.providers["native"].timeout_seconds == 120
    assert config.providers["native"].max_retries == 1
    assert config.models["accurate-mapper"].structured_output is StructuredOutputMode.AUTO
    assert config.models["accurate-mapper"].context_mode is ContextMode.AUTO
    assert config.models["accurate-mapper"].input_token_budget == 64000
    assert config.models["accurate-mapper"].max_output_tokens == 12000
    assert config.models["accurate-mapper"].target_batch_size == 25
    assert config.models["accurate-mapper"].candidate_limit_per_target == 20


def test_resolve_model_is_deterministic_and_never_reads_credential_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ModelProviderConfig.model_validate(_valid_config())
    monkeypatch.setenv("OPEN_MAPPING_NATIVE_API_KEY", "credential-value-must-not-appear")

    resolved = resolve_model(config, "accurate-mapper")

    assert resolved.alias == "accurate-mapper"
    assert resolved.provider_name == "native"
    assert resolved.provider is config.providers["native"]
    assert resolved.model is config.models["accurate-mapper"]
    assert "credential-value-must-not-appear" not in resolved.model_dump_json()


def test_resolve_model_rejects_unknown_alias() -> None:
    config = ModelProviderConfig.model_validate(_valid_config())

    with pytest.raises(KeyError, match="unknown model alias"):
        resolve_model(config, "missing")


def test_rejects_unknown_model_provider_reference() -> None:
    raw = _valid_config()
    raw["models"]["accurate-mapper"]["provider"] = "missing"

    with pytest.raises(ValidationError, match="unknown provider"):
        ModelProviderConfig.model_validate(raw)


def test_load_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        "\n".join(
            (
                'config_version: "0.1"',
                "providers:",
                "  local:",
                "    kind: custom-http",
                "    base_url: http://127.0.0.1:8080",
                "  local:",
                "    kind: custom-http",
                "    base_url: http://127.0.0.1:8081",
                "models: {}",
                "",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConstructorError, match="duplicate key 'local'"):
        load_model_provider_config(path)


def test_rejects_unknown_configuration_properties() -> None:
    raw = _valid_config()
    raw["unexpected"] = True

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("kind", "base_url"),
    (
        ("openai-compatible", None),
        ("custom-http", None),
        ("custom-http", "http://example.invalid/v1"),
        ("custom-http", "ftp://example.invalid/v1"),
        ("custom-http", "https://"),
    ),
)
def test_rejects_missing_or_unsafe_provider_base_urls(kind: str, base_url: str | None) -> None:
    raw = _valid_config()
    raw["providers"]["local"] = {"kind": kind, "base_url": base_url}

    with pytest.raises(ValidationError, match="base_url|HTTPS|loopback"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("timeout_seconds", 0), ("timeout_seconds", -1), ("max_retries", -1)),
)
def test_rejects_invalid_provider_timeout_and_retry_values(field_name: str, value: int) -> None:
    raw = _valid_config()
    raw["providers"]["native"][field_name] = value

    with pytest.raises(ValidationError, match=field_name):
        ModelProviderConfig.model_validate(raw)


def test_rejects_empty_model_id() -> None:
    raw = _valid_config()
    raw["models"]["accurate-mapper"]["model_id"] = "   "

    with pytest.raises(ValidationError, match="model_id"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.parametrize("kind", ("openai", "anthropic", "google"))
def test_requires_native_provider_credential_environment_name(kind: str) -> None:
    raw = _valid_config()
    raw["providers"] = {"native": {"kind": kind}}
    raw["models"] = {"mapper": {"provider": "native", "model_id": "synthetic-mapper"}}

    with pytest.raises(ValidationError, match="api_key_env"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.parametrize("field_name", ("api_key", "token", "authorization", "secret"))
def test_rejects_literal_credential_fields_at_nested_configuration_locations(
    field_name: str,
) -> None:
    raw = _valid_config()
    raw["models"]["accurate-mapper"]["parameters"] = {field_name: "literal-value"}

    with pytest.raises(ValidationError, match="literal credential field"):
        ModelProviderConfig.model_validate(raw)


def test_rejects_literal_secret_header_value() -> None:
    raw = _valid_config()
    raw["providers"]["local"]["headers_from_env"] = {"Authorization": "Bearer literal-secret"}

    with pytest.raises(ValidationError, match="environment variable name"):
        ModelProviderConfig.model_validate(raw)


def test_rejects_literal_credential_query_parameter_in_base_url() -> None:
    raw = _valid_config()
    raw["providers"]["local"]["base_url"] = "https://example.invalid/v1?api_key=literal-secret"

    with pytest.raises(ValidationError, match="credential query parameter"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.parametrize(
    "base_url",
    (
        "https://literal-secret@example.invalid/v1",
        "https://:literal-secret@example.invalid/v1",
    ),
)
def test_rejects_literal_credentials_embedded_in_base_url_userinfo(base_url: str) -> None:
    raw = _valid_config()
    raw["providers"]["local"]["base_url"] = base_url

    with pytest.raises(ValidationError, match="base_url must not contain credentials"):
        ModelProviderConfig.model_validate(raw)


def test_resolves_models_config_path_in_documented_precedence_order(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.yaml"
    configured = tmp_path / "configured.yaml"
    default = tmp_path / "open-mapping.models.yaml"
    default.write_text("config_version: '0.1'\nproviders: {}\nmodels: {}\n", encoding="utf-8")

    assert (
        resolve_models_config_path(
            explicit,
            cwd=tmp_path,
            environment={"OPEN_MAPPING_MODELS_CONFIG": str(configured)},
        )
        == explicit
    )
    assert (
        resolve_models_config_path(
            None,
            cwd=tmp_path,
            environment={"OPEN_MAPPING_MODELS_CONFIG": str(configured)},
        )
        == configured
    )
    assert resolve_models_config_path(None, cwd=tmp_path, environment={}) == default
    assert resolve_models_config_path(None, cwd=tmp_path / "missing", environment={}) is None


def test_committed_model_provider_schema_matches_pydantic_contract() -> None:
    committed = json.loads(
        Path("schemas/model-provider-config.schema.json").read_text(encoding="utf-8")
    )
    generated = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **TypeAdapter(ModelProviderConfig).json_schema(),
    }

    assert committed == generated
