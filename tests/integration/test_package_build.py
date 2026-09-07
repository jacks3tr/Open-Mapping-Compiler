"""Release archives contain the complete public runtime payload."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

from open_mapping.schema_targets import SCHEMA_TARGETS
from tests.support.package_env import build_release, install_wheel, run_checked

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SCHEMAS = tuple(target.filename for target in SCHEMA_TARGETS)
REQUIRED_MODEL_ASSISTED_EXAMPLE = (
    "open-mapping.models.example.yaml",
    "openai.models.example.yaml",
    "input.json",
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
        metadata_name = next(name for name in wheel_names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    assert "Requires-Dist: httpx>=0.27" in metadata.splitlines()
    for schema_name in REQUIRED_SCHEMAS:
        assert f"open_mapping/schemas/{schema_name}" in wheel_names
    assert "open_mapping/demo.json" in wheel_names
    assert "open_mapping/examples/conformance/identity.json" in wheel_names
    assert "open_mapping/examples/typescript/open_mapping_client.ts" in wheel_names
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
        "examples/model-assisted/input.json",
        "examples/model-assisted/source.schema.json",
        "examples/quick-start/source.schema.json",
        "examples/sdk/app.py",
        "examples/pipeline/input.jsonl",
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
        [python, "-c", "import httpx, open_mapping; print(open_mapping.__file__)"],
        cwd=tmp_path,
        environment=environment,
    )
    assert str((tmp_path / "venv").resolve()).lower() in imported.stdout.strip().lower()
    help_result = run_checked([command, "--help"], cwd=tmp_path, environment=environment)
    assert "map" in help_result.stdout
    assert "| suggest" not in help_result.stdout
    assert "| review " not in help_result.stdout
    for visible_command in ("demo", "resume", "review-draft", "impact", "serve"):
        assert visible_command in help_result.stdout
    missing_server_extra = subprocess.run(
        [command, "serve", "missing.omc"],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert missing_server_extra.returncode == 2
    assert "open-mapping[server]" in missing_server_extra.stderr

    bundle = tmp_path / "customer.omc"
    run_checked(
        [
            command,
            "build",
            ROOT / "examples/quick-start/input.json",
            ROOT / "examples/quick-start/target.schema.json",
            "--source-format",
            "json-data",
            "--hints",
            ROOT / "examples/quick-start/hints.yaml",
            "--work-dir",
            tmp_path / "audit",
            "--out",
            bundle,
        ],
        cwd=tmp_path,
        environment=environment,
    )
    applied = run_checked(
        [command, "apply", bundle, "--input", ROOT / "examples/quick-start/input.json"],
        cwd=tmp_path,
        environment=environment,
    )
    assert json.loads(applied.stdout) == {
        "accountName": "Ada Lovelace",
        "customerId": "C-1001",
    }
    sdk = run_checked(
        [
            python,
            "-c",
            (
                "from open_mapping import Mapper; "
                f"print(Mapper.load(r'{bundle}').transform("
                "{'customerId':'C-1001','fullName':'Ada Lovelace'}))"
            ),
        ],
        cwd=tmp_path,
        environment=environment,
    )
    assert "Ada Lovelace" in sdk.stdout


def test_clean_wheel_server_extra_is_installable(tmp_path: Path) -> None:
    wheel, _ = build_release(ROOT, tmp_path / "dist")
    python, command = install_wheel(wheel, tmp_path / "venv", root=ROOT)
    run_checked(
        ["uv", "pip", "install", "--python", python, f"{wheel}[server]"],
        cwd=ROOT,
    )
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    run_checked(
        [python, "-c", "import fastapi, uvicorn, open_mapping.server.app"],
        cwd=tmp_path,
        environment=environment,
    )
    help_result = run_checked([command, "serve", "--help"], cwd=tmp_path, environment=environment)
    assert "--allow-remote" in help_result.stdout
