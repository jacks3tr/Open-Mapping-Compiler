"""Direct native-model shorthand resolution contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_mapping.errors import OpenMappingError
from open_mapping.model.model_config import ProviderKind
from open_mapping.providers.shorthand import resolve_model_selection


@pytest.mark.parametrize(
    ("selection", "credential", "kind"),
    [
        ("openai:gpt-5-mini", "OPENAI_API_KEY", ProviderKind.OPENAI),
        ("anthropic:claude-sonnet-4", "ANTHROPIC_API_KEY", ProviderKind.ANTHROPIC),
        ("google:gemini-2.5-flash", "GOOGLE_API_KEY", ProviderKind.GOOGLE),
    ],
)
def test_native_shorthand_needs_only_its_standard_environment_key(
    tmp_path: Path, selection: str, credential: str, kind: ProviderKind
) -> None:
    resolved = resolve_model_selection(
        selection,
        explicit_config=None,
        cwd=tmp_path,
        environment={credential: "test-secret"},
    )

    assert resolved.resolved_model.provider.kind is kind
    assert resolved.resolved_model.model.model_id == selection.split(":", 1)[1]
    assert resolved.shorthand
    assert "test-secret" not in resolved.model_dump_json()


def test_shorthand_reports_the_exact_missing_credential_name(tmp_path: Path) -> None:
    with pytest.raises(OpenMappingError, match="OPENAI_API_KEY"):
        resolve_model_selection(
            "openai:gpt-5-mini", explicit_config=None, cwd=tmp_path, environment={}
        )


@pytest.mark.parametrize("value", ["openai-compatible:model", "custom-http:model", "unknown:x"])
def test_endpoint_dependent_or_unknown_kinds_are_not_shorthand(tmp_path: Path, value: str) -> None:
    with pytest.raises(OpenMappingError, match="model selection"):
        resolve_model_selection(value, explicit_config=None, cwd=tmp_path, environment={})


def test_existing_config_alias_takes_precedence_over_shorthand(tmp_path: Path) -> None:
    config = tmp_path / "open-mapping.models.yaml"
    config.write_text(
        """config_version: '0.1'
providers:
  local:
    kind: custom-http
    base_url: http://127.0.0.1:8765
models:
  openai:gpt-5-mini:
    provider: local
    model_id: local-model
""",
        encoding="utf-8",
    )

    resolved = resolve_model_selection(
        "openai:gpt-5-mini", explicit_config=None, cwd=tmp_path, environment={}
    )

    assert not resolved.shorthand
    assert resolved.resolved_model.model.model_id == "local-model"
