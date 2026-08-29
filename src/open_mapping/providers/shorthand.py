"""Resolve configured aliases and native provider:model shorthand."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.model_config import (
    ModelDefinition,
    ProviderDefinition,
    ProviderKind,
    ResolvedModel,
)
from open_mapping.providers.config import load_model_provider_config, resolve_model
from open_mapping.serialization.canonical_json import canonical_json_bytes

_CREDENTIALS = {
    ProviderKind.OPENAI: "OPENAI_API_KEY",
    ProviderKind.ANTHROPIC: "ANTHROPIC_API_KEY",
    ProviderKind.GOOGLE: "GOOGLE_API_KEY",
}


class ResolvedModelSelection(OpenMappingModel):
    resolved_model: ResolvedModel
    config_sha256: str
    shorthand: bool


def _error(message: str, correction: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.INVALID_INPUT,
                severity=Severity.ERROR,
                component="providers.shorthand",
                message=message,
                correction=correction,
            ),
        )
    )


def _provider_error(message: str, correction: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.PROVIDER_FAILURE,
                severity=Severity.ERROR,
                component="providers.shorthand",
                message=message,
                correction=correction,
            ),
        )
    )


def _user_config(environment: Mapping[str, str]) -> Path | None:
    appdata = environment.get("APPDATA")
    if appdata:
        return Path(appdata) / "open-mapping" / "models.yaml"
    xdg = environment.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "open-mapping" / "models.yaml"
    home = environment.get("HOME") or environment.get("USERPROFILE")
    return None if not home else Path(home) / ".config" / "open-mapping" / "models.yaml"


def _config_paths(
    explicit_config: Path | None,
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> tuple[Path, ...]:
    if explicit_config is not None:
        return (explicit_config,)
    configured = environment.get("OPEN_MAPPING_MODELS_CONFIG")
    if configured:
        return (Path(configured),)
    project = cwd / "open-mapping.models.yaml"
    if project.is_file():
        return (project,)
    user = _user_config(environment)
    return (user,) if user is not None and user.is_file() else ()


def _require_credential(model: ResolvedModel, environment: Mapping[str, str]) -> None:
    credential = model.provider.api_key_env
    if credential is not None and not environment.get(credential):
        raise _provider_error(
            f"required credential environment variable {credential} is not set",
            f"Set {credential} in the process environment and retry.",
        )


def resolve_model_selection(
    value: str,
    *,
    explicit_config: Path | None,
    cwd: Path,
    environment: Mapping[str, str],
) -> ResolvedModelSelection:
    paths = _config_paths(explicit_config, cwd=cwd, environment=environment)
    if paths:
        path = paths[0]
        try:
            config = load_model_provider_config(path)
        except (OSError, UnicodeError, ValueError) as error:
            raise _error(
                f"could not load model configuration {path.name!r}",
                "Provide a readable, valid model configuration file.",
            ) from error
        if value in config.models:
            resolved = resolve_model(config, value)
            _require_credential(resolved, environment)
            return ResolvedModelSelection(
                resolved_model=resolved,
                config_sha256=hashlib.sha256(
                    canonical_json_bytes(config.model_dump(mode="json"))
                ).hexdigest(),
                shorthand=False,
            )

    provider_text, separator, model_id = value.partition(":")
    try:
        kind = ProviderKind(provider_text)
    except ValueError as error:
        raise _error(
            f"model selection {value!r} is neither a configured alias nor native shorthand",
            "Use a configured alias or openai:, anthropic:, or google: followed by a model ID.",
        ) from error
    if not separator or not model_id.strip() or kind not in _CREDENTIALS:
        raise _error(
            f"model selection {value!r} is not supported shorthand",
            "Use openai:, anthropic:, or google: shorthand; configure endpoint-based providers explicitly.",
        )
    credential = _CREDENTIALS[kind]
    provider_name = f"builtin-{kind.value}"
    model = ResolvedModel(
        alias=value,
        provider_name=provider_name,
        provider=ProviderDefinition(kind=kind, api_key_env=credential),
        model=ModelDefinition(provider=provider_name, model_id=model_id.strip()),
    )
    _require_credential(model, environment)
    digest_payload: dict[str, object] = {
        "kind": kind.value,
        "model_id": model_id.strip(),
        "credential_env": credential,
    }
    return ResolvedModelSelection(
        resolved_model=model,
        config_sha256=hashlib.sha256(canonical_json_bytes(digest_payload)).hexdigest(),
        shorthand=True,
    )


__all__ = ["ResolvedModelSelection", "resolve_model_selection"]
