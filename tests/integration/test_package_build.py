"""Release archives contain the complete public runtime payload."""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path

from tests.support.package_env import build_release, install_wheel, run_checked

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SCHEMAS = (
    "benchmark-manifest.schema.json",
    "mapping-document.schema.json",
    "mapping-hints.schema.json",
    "suggestion-report.schema.json",
    "suggestion-review.schema.json",
)
REQUIRED_MODEL_ASSISTED_EXAMPLE = (
    "open-mapping.models.example.yaml",
    "openai.models.example.yaml",
    "source.schema.json",
    "target.schema.json",
    "samples.jsonl",
    "hints.yaml",
    "README.md",
)


def test_sdist_and_wheel_contain_runtime_schemas_examples_and_public_docs(tmp_path: Path) -> None:
    wheel, sdist = build_release(ROOT, tmp_path / "dist")
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    for schema_name in REQUIRED_SCHEMAS:
        assert f"open_mapping/schemas/{schema_name}" in wheel_names
    assert "open_mapping/examples/erp-mes/source.schema.json" in wheel_names
    assert "open_mapping/examples/erp-mes/target.schema.json" in wheel_names
    assert "open_mapping/examples/erp-mes/hints.yaml" in wheel_names
    assert "open_mapping/examples/erp-mes/review.yaml" in wheel_names
    for example_file in REQUIRED_MODEL_ASSISTED_EXAMPLE:
        assert f"open_mapping/examples/model-assisted/{example_file}" in wheel_names

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = {name.split("/", 1)[-1] for name in archive.getnames() if "/" in name}
    for schema_name in REQUIRED_SCHEMAS:
        assert f"schemas/{schema_name}" in sdist_names
    for public_file in (
        "README.md",
        "USAGE.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "LICENSE",
        "examples/erp-mes/source.schema.json",
        "examples/model-assisted/open-mapping.models.example.yaml",
        "examples/model-assisted/openai.models.example.yaml",
        "examples/model-assisted/source.schema.json",
        "docs/quick-start.md",
        "docs/model-assisted-mapping.md",
        "docs/openai-provider.md",
    ):
        assert public_file in sdist_names
    assert "Design.md" not in sdist_names
    assert "Agent-Implementation-Plan.md" not in sdist_names
    assert not any("__pycache__" in name or name.endswith("coverage.json") for name in sdist_names)


def test_clean_wheel_install_imports_from_isolated_environment_and_has_help(tmp_path: Path) -> None:
    wheel, _ = build_release(ROOT, tmp_path / "dist")
    python, command = install_wheel(wheel, tmp_path / "venv", root=ROOT)
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    imported = run_checked(
        [python, "-c", "import open_mapping; print(open_mapping.__file__)"],
        cwd=tmp_path,
        environment=environment,
    )
    assert str((tmp_path / "venv").resolve()).lower() in imported.stdout.strip().lower()
    help_result = run_checked([command, "--help"], cwd=tmp_path, environment=environment)
    assert "suggest" in help_result.stdout
    assert "review" in help_result.stdout
