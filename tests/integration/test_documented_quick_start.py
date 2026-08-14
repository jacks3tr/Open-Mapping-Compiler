"""The README keeps model and manual setup short and points to tested examples."""

from __future__ import annotations

from pathlib import Path

from open_mapping.model.model_config import ProviderKind
from open_mapping.providers.config import load_model_provider_config

ROOT = Path(__file__).resolve().parents[2]


def test_readme_leads_with_short_model_and_manual_workflows() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Seven-command quick start" not in readme
    assert "## Install" in readme
    assert "## Set up OpenAI" in readme
    assert "## Get a structured mapping draft" in readme
    assert "## Use it without a model" in readme
    assert "examples/model-assisted/openai.models.example.yaml" in readme
    assert "docs/openai-provider.md" in readme
    assert "--model openai-mini" in readme
    assert "--out mapping.yaml" in readme


def test_tracked_openai_example_is_ready_for_an_environment_key() -> None:
    config = load_model_provider_config(ROOT / "examples/model-assisted/openai.models.example.yaml")

    provider = config.providers["openai"]
    assert provider.kind is ProviderKind.OPENAI
    assert provider.api_key_env == "OPENAI_API_KEY"
    assert config.models["openai"].model_id == "gpt-5"
    assert config.models["openai-mini"].model_id == "gpt-5-mini"
