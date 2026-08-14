"""Adversarial configuration and credential-boundary tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ModelProviderConfig
from open_mapping.providers.config import load_model_provider_config, resolve_model
from open_mapping.providers.transports.base import resolve_transport_credentials
from open_mapping.serialization.canonical_json import canonical_json_bytes


def _config() -> dict[str, Any]:
    return {
        "config_version": "0.1",
        "providers": {
            "local": {
                "kind": "openai-compatible",
                "base_url": "http://127.0.0.1:8080/v1",
                "headers_from_env": {"Authorization": "LOCAL_AUTHORIZATION"},
            }
        },
        "models": {
            "mapper": {
                "provider": "local",
                "model_id": "local-model",
            }
        },
    }


@pytest.mark.adversarial
@pytest.mark.parametrize("field_name", ("api_key", "token", "authorization", "secret"))
def test_literal_credentials_are_rejected_but_header_environment_names_are_allowed(
    field_name: str,
) -> None:
    raw = _config()
    raw["providers"]["local"][field_name] = "Bearer literal-secret"

    with pytest.raises(ValidationError, match="literal credential field"):
        ModelProviderConfig.model_validate(raw)

    config = ModelProviderConfig.model_validate(_config())
    assert config.providers["local"].headers_from_env == {"Authorization": "LOCAL_AUTHORIZATION"}


@pytest.mark.adversarial
def test_missing_credential_environment_variables_fail_before_transport_use() -> None:
    resolved = resolve_model(ModelProviderConfig.model_validate(_config()), "mapper")

    with pytest.raises(OpenMappingError) as captured:
        resolve_transport_credentials(resolved, environment={})

    assert [issue.message for issue in captured.value.issues] == [
        "environment variable 'LOCAL_AUTHORIZATION' is not set"
    ]
    assert "literal-secret" not in str(captured.value.issues)


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "url",
    (
        "http://provider.example/v1",
        "http://127.0.0.1.evil.example/v1",
        "http://localhost.evil.example/v1",
        "http://2130706433/v1",
        "http://0x7f000001/v1",
        "http://user:password@127.0.0.1:8080/v1",
        "http://127.0.0.1:8080/v1?authorization=Bearer%20secret",
    ),
)
def test_crafted_non_loopback_plaintext_and_embedded_credentials_are_rejected(
    url: str,
) -> None:
    raw = _config()
    raw["providers"]["local"]["base_url"] = url

    with pytest.raises(ValidationError, match="base_url|HTTPS|loopback|credentials"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "provider_kind",
    ("openai", "anthropic", "google", "openai-compatible", "custom-http"),
)
@pytest.mark.parametrize("suffix", ("?trace=true", "#response-fragment"))
def test_every_provider_base_url_rejects_query_strings_and_fragments(
    provider_kind: str,
    suffix: str,
) -> None:
    raw = _config()
    provider = raw["providers"]["local"]
    provider["kind"] = provider_kind
    provider["base_url"] = f"https://provider.example/v1{suffix}"
    if provider_kind in {"openai", "anthropic", "google"}:
        provider["api_key_env"] = "PROVIDER_API_KEY"

    with pytest.raises(
        ValidationError,
        match="base_url must not contain a query string or fragment",
    ):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.adversarial
def test_duplicate_and_unknown_configuration_fields_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        """config_version: '0.1'
providers:
  local:
    kind: openai-compatible
    base_url: http://127.0.0.1:8080/v1
    base_url: http://127.0.0.1:8081/v1
models: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConstructorError, match="duplicate key"):
        load_model_provider_config(duplicate)

    raw = _config()
    raw["models"]["mapper"]["untrusted_extension"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelProviderConfig.model_validate(raw)


@pytest.mark.adversarial
@pytest.mark.parametrize("special_key", ("__proto__", "constructor", "toString"))
def test_special_mapping_keys_remain_ordinary_deterministic_names(special_key: str) -> None:
    raw = _config()
    provider = raw["providers"].pop("local")
    model = raw["models"].pop("mapper")
    model["provider"] = special_key
    raw["providers"][special_key] = provider
    raw["models"][special_key] = model

    first = ModelProviderConfig.model_validate(raw)
    second = ModelProviderConfig.model_validate(
        {
            "models": raw["models"],
            "providers": raw["providers"],
            "config_version": "0.1",
        }
    )

    assert resolve_model(first, special_key).provider_name == special_key
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )


@pytest.mark.adversarial
@pytest.mark.parametrize("nonfinite", (float("nan"), float("inf"), float("-inf")))
def test_nonfinite_configuration_numbers_are_rejected(nonfinite: float) -> None:
    timeout_config = _config()
    timeout_config["providers"]["local"]["timeout_seconds"] = nonfinite
    with pytest.raises(ValidationError):
        ModelProviderConfig.model_validate(timeout_config)

    parameter_config = _config()
    parameter_config["models"]["mapper"]["parameters"] = {
        "temperature": nonfinite,
        "top_p": nonfinite,
    }
    with pytest.raises(ValidationError):
        ModelProviderConfig.model_validate(parameter_config)


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "yaml_value",
    (
        "2026-08-13",
        ".inf",
        "!!set {value: null}",
    ),
)
def test_non_json_yaml_values_cannot_enter_the_configuration(
    tmp_path: Path,
    yaml_value: str,
) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        f"""config_version: '0.1'
providers:
  local:
    kind: openai-compatible
    base_url: http://127.0.0.1:8080/v1
models:
  mapper:
    provider: local
    model_id: {yaml_value}
""",
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError, ValidationError)):
        load_model_provider_config(path)


@pytest.mark.adversarial
def test_invalid_utf8_configuration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_bytes(b"config_version: '0.1'\nmodel_id: \xff\n")

    with pytest.raises(UnicodeError):
        load_model_provider_config(path)
