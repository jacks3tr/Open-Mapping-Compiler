"""Model configuration validation, listing, and CLI selection helpers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

import typer

from open_mapping.cli.common import (
    CliInputError,
    run_public_command,
    validate_input_files,
)
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ModelProviderConfig, ResolvedModel
from open_mapping.providers.config import (
    load_model_provider_config,
    resolve_model,
    resolve_models_config_path,
)
from open_mapping.serialization.canonical_json import canonical_json, canonical_json_bytes

_MODELS_HELP = """Validate and inspect named model configurations without making a model call.

Cost: these commands never contact a provider. Privacy: connection and credential fields are not
printed. Review: model proposals are drafts and still require normal mapping review.
"""

models_app = typer.Typer(help=_MODELS_HELP, add_completion=False)


@dataclass(frozen=True)
class CliModelSelection:
    """One validated CLI model selection and its non-secret configuration digest."""

    config: ModelProviderConfig
    resolved_model: ResolvedModel
    config_sha256: str


def model_config_sha256(config: ModelProviderConfig) -> str:
    """Hash the canonical validated configuration without resolving credential values."""

    payload = cast(JsonValue, config.model_dump(mode="json"))
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _load_config(path: Path) -> ModelProviderConfig:
    validate_input_files({"model configuration": path})
    return load_model_provider_config(path)


def load_cli_model_selection(
    explicit_config: Path | None,
    alias: str,
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> CliModelSelection:
    """Resolve and validate a selected alias before schemas or providers are touched."""

    resolved_path = resolve_models_config_path(
        explicit_config,
        cwd=Path.cwd() if cwd is None else cwd,
        environment=os.environ if environment is None else environment,
    )
    if resolved_path is None:
        raise CliInputError(
            "--model requires --models-config, OPEN_MAPPING_MODELS_CONFIG, "
            "or ./open-mapping.models.yaml"
        )
    config = _load_config(resolved_path)
    try:
        resolved_model = resolve_model(config, alias)
    except KeyError as exc:
        message = (
            exc.args[0] if exc.args and isinstance(exc.args[0], str) else "unknown model alias"
        )
        raise CliInputError(message) from exc
    return CliModelSelection(
        config=config,
        resolved_model=resolved_model,
        config_sha256=model_config_sha256(config),
    )


def models_validate_command(config_path: Path) -> str:
    """Validate one configuration and return a sanitized JSON summary."""

    config = _load_config(config_path)
    payload: JsonValue = {
        "config_sha256": model_config_sha256(config),
        "config_version": config.config_version,
        "model_count": len(config.models),
        "provider_count": len(config.providers),
        "valid": True,
    }
    return canonical_json(payload) + "\n"


def models_list_command(config_path: Path) -> str:
    """List configured aliases without disclosing endpoints or credential names."""

    config = _load_config(config_path)
    models: list[JsonValue] = []
    for alias in sorted(config.models):
        model = config.models[alias]
        provider = config.providers[model.provider]
        models.append(
            {
                "alias": alias,
                "context_mode": model.context_mode.value,
                "model_id": model.model_id,
                "provider_kind": provider.kind.value,
                "provider_name": model.provider,
            }
        )
    payload: JsonValue = {
        "config_sha256": model_config_sha256(config),
        "models": models,
    }
    return canonical_json(payload) + "\n"


def _exit_with_output(operation: Callable[[], str]) -> None:
    def run() -> int:
        typer.echo(operation(), nl=False)
        return 0

    raise typer.Exit(run_public_command(run))


@models_app.command("validate")
def validate_models(
    config: Annotated[Path, typer.Option("--config", help="Provider/model configuration file.")],
) -> None:
    """Validate configuration locally without contacting a provider."""

    _exit_with_output(lambda: models_validate_command(config))


@models_app.command("list")
def list_models(
    config: Annotated[Path, typer.Option("--config", help="Provider/model configuration file.")],
) -> None:
    """List safe model alias metadata without endpoints or credentials."""

    _exit_with_output(lambda: models_list_command(config))


__all__ = [
    "CliModelSelection",
    "load_cli_model_selection",
    "model_config_sha256",
    "models_app",
    "models_list_command",
    "models_validate_command",
]
