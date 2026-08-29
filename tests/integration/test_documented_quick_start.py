"""The README presents AI mapping as the primary workflow."""

from __future__ import annotations

from pathlib import Path

from open_mapping.model.model_config import ProviderKind
from open_mapping.providers.config import load_model_provider_config

ROOT = Path(__file__).resolve().parents[2]

AI_FIRST_GUIDES = (
    "README.md",
    "USAGE.md",
    "docs/bundles.md",
    "docs/model-assisted-mapping.md",
    "docs/openai-provider.md",
    "docs/quick-start.md",
    "docs/sdk.md",
    "docs/server.md",
    "docs/workflow-integration.md",
    "examples/model-assisted/README.md",
    "benchmarks/blind-multi-industry-v1/README.md",
    "benchmarks/field-name-challenge/README.md",
)

PUBLIC_GUIDES = (*AI_FIRST_GUIDES, "examples/erp-mes/README.md")


def test_readme_presents_ai_mapping_as_the_primary_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [line for line in readme.splitlines() if line.startswith("## ")]

    assert "Seven-command quick start" not in readme
    assert headings == [
        "## What it is",
        "## Use it with AI",
        "## Install",
        "## Map source data",
        "## Deterministic offline fallback",
        "## Build executable output",
        "## Tested across seven industries",
    ]
    assert len(readme.splitlines()) <= 85
    assert readme.count("```") <= 8
    assert (
        'python -m pip install "open-mapping @ '
        'https://github.com/jacks3tr/Open-Mapping-Compiler/archive/refs/heads/main.zip"' in readme
    )
    assert "open-mapping[ai]" not in readme
    assert "open-mapping map input.json target.schema.json --source-format json-data" in readme
    assert "--model openai:<model-id>" in readme
    assert "--out mapping.json" in readme
    assert readme.index("## Use it with AI") < readme.index("## Map source data")
    assert readme.index("## Map source data") < readme.index("## Deterministic offline fallback")
    assert "Optional model help" not in readme
    assert "examples/model-assisted/README.md" in readme
    assert "OPEN_MAPPING_MODEL" in readme
    assert "deterministic offline fallback" in readme
    assert "63/63 (100%)" in readme
    assert "7/7 (100%)" in readme
    assert "105/105 (100%)" in readme
    assert "The offline deterministic fallback scored 45.7% across the same tests." in readme
    assert "offline replay" not in readme.lower()


def test_public_guides_keep_ai_primary_and_local_as_the_fallback() -> None:
    stale_local_first_language = (
        "## Local",
        "## Add a model",
        "Local deterministic mapping is the default",
        "The default is fully local",
    )

    for relative_path in PUBLIC_GUIDES:
        guide = (ROOT / relative_path).read_text(encoding="utf-8")
        assert all(stale not in guide for stale in stale_local_first_language), relative_path

    for relative_path in AI_FIRST_GUIDES:
        guide = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "AI" in guide, relative_path
        if "offline fallback" in guide.lower():
            assert guide.index("AI") < guide.lower().index("offline fallback"), relative_path


def test_model_assisted_example_has_a_runnable_input() -> None:
    example_input = ROOT / "examples/model-assisted/input.json"

    assert example_input.is_file()
    assert example_input.read_text(encoding="utf-8") == (
        '{"customer_id":"C-1001","status":"ACTIVE"}\n'
    )


def test_tracked_openai_example_is_ready_for_an_environment_key() -> None:
    config = load_model_provider_config(ROOT / "examples/model-assisted/openai.models.example.yaml")

    provider = config.providers["openai"]
    assert provider.kind is ProviderKind.OPENAI
    assert provider.api_key_env == "OPENAI_API_KEY"
    assert config.models["openai"].model_id == "gpt-5"
    assert config.models["openai-mini"].model_id == "gpt-5-mini"
