"""Discovery, loading, and alias resolution for model provider configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from open_mapping.model.model_config import ModelProviderConfig, ResolvedModel
from open_mapping.serialization.yaml_loader import load_safe_yaml

_CONFIG_ENVIRONMENT_VARIABLE = "OPEN_MAPPING_MODELS_CONFIG"
_DEFAULT_CONFIG_FILE = "open-mapping.models.yaml"


def resolve_models_config_path(
    explicit: Path | None,
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> Path | None:
    """Resolve the optional configuration path using the documented precedence."""

    if explicit is not None:
        return explicit
    configured_path = environment.get(_CONFIG_ENVIRONMENT_VARIABLE)
    if configured_path:
        return Path(configured_path)
    default_path = cwd / _DEFAULT_CONFIG_FILE
    return default_path if default_path.is_file() else None


def load_model_provider_config(path: Path) -> ModelProviderConfig:
    """Load one duplicate-safe YAML configuration file into its strict model."""

    return ModelProviderConfig.model_validate(load_safe_yaml(path.read_text(encoding="utf-8")))


def resolve_model(config: ModelProviderConfig, alias: str) -> ResolvedModel:
    """Resolve one configured model alias without resolving any credentials."""

    try:
        model = config.models[alias]
    except KeyError as exc:
        raise KeyError(f"unknown model alias {alias!r}") from exc
    return ResolvedModel(
        alias=alias,
        provider_name=model.provider,
        provider=config.providers[model.provider],
        model=model,
    )
