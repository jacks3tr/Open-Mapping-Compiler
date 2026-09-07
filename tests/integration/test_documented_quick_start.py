"""Onboarding proves a keyless first success without obscuring the AI workflow."""

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
    assert headings[:3] == [
        "## First success, without an API key",
        "## Choose your integration path",
        "## Add AI when evaluating mapping quality",
    ]
    first_success = readme.split("## First success, without an API key", 1)[1].split(
        "## Choose your integration path", 1
    )[0]
    assert len(first_success.splitlines()) <= 20
    assert "python -m pip install ." in first_success
    assert "open-mapping demo --out-dir example" in first_success
    assert "open-mapping apply example/mapping.omc --input example/input.json" in first_success
    assert "open-mapping review-draft work/customer/draft.json" in readme
    assert "open-mapping resume work/customer/draft.json" in readme
    assert "--require-model" in readme
    assert "OPEN_MAPPING_MODEL" in readme
    assert "OPENAI_API_KEY" in readme
    assert "ANTHROPIC_API_KEY" in readme
    assert "GOOGLE_API_KEY" in readme
    assert "Mapper.load" in readme
    assert "makes zero model calls" in readme
    assert "**after a successful registry release**" in readme
    assert "100% on synthetic benchmark v1" in readme
    assert "not a production-accuracy estimate" in readme
    assert "not equivalent runtime schema and invariant validation" in readme
    assert "open-mapping[ai]" not in readme
    assert "examples/model-assisted/README.md" not in first_success


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
