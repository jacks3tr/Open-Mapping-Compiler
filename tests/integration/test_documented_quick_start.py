"""The README presents model assistance before the local workflow."""

from __future__ import annotations

from pathlib import Path

from open_mapping.model.model_config import ProviderKind
from open_mapping.providers.config import load_model_provider_config

ROOT = Path(__file__).resolve().parents[2]


def test_readme_presents_model_assistance_before_the_local_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [line for line in readme.splitlines() if line.startswith("## ")]

    assert "Seven-command quick start" not in readme
    assert headings == [
        "## What it is",
        "## Add a model",
        "## Local",
        "## Install",
        "## Map source data",
        "## Build executable output",
    ]
    assert len(readme.splitlines()) <= 70
    assert readme.count("```") <= 8
    assert (
        'python -m pip install "open-mapping @ '
        'https://github.com/jacks3tr/Open-Mapping-Compiler/archive/refs/heads/main.zip"' in readme
    )
    assert "open-mapping[ai]" not in readme
    assert "open-mapping map input.json target.schema.json --source-format json-data" in readme
    assert "--out mapping.json" in readme
    assert readme.index("## Add a model") < readme.index("## Local")
    assert readme.index("## Local") < readme.index("## Map source data")
    assert "Optional model help" not in readme
    assert "examples/model-assisted/README.md" in readme
    assert "OPEN_MAPPING_MODEL" in readme
    assert "No API key" in readme


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
