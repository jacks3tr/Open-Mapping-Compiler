"""The primary map command is local-first with optional model assistance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.integration.cli.conftest import ROOT, CliFiles
from tests.integration.providers.model_transport_support import (
    LocalJsonServer,
    ScriptedResponse,
)
from tests.support.streamlined import local_model_response, write_local_model_config


def _run(
    *args: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "open_mapping.cli.app", *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _model_environment(config: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["OPEN_MAPPING_MODELS_CONFIG"] = str(config)
    environment["OPEN_MAPPING_MODEL"] = "mapper"
    return environment


def test_map_two_schemas_writes_one_structured_reviewable_result(
    cli_files: CliFiles,
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    output = tmp_path / "mapping.json"
    with LocalJsonServer(ScriptedResponse(200, local_model_response("/value"))) as server:
        write_local_model_config(config, server.base_url)
        result = _run(
            "map",
            str(cli_files.source),
            str(cli_files.target),
            "--out",
            str(output),
            environment=_model_environment(config),
        )
        request = server.requests[0].body

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    mapping = json.loads(output.read_text(encoding="utf-8"))
    assert mapping["report_version"] == "0.1"
    assert mapping["suggestions"][0]["target_path"] == "/value"
    assert mapping["suggestions"][0]["origin"] == "model"
    assert mapping["suggestions"][0]["reason"] == "Local model proposal."
    assert mapping["model_run_disclosure"]["model_alias"] == "mapper"
    serialized = output.read_text(encoding="utf-8")
    assert server.base_url not in serialized
    assert "credential" not in serialized.casefold()
    assert '"raw_samples":' not in serialized
    assert mapping["model_run_disclosure"]["raw_samples_included"] is False

    prompt = request["model_prompt"]
    assert isinstance(prompt, dict)
    instruction = prompt["system_instruction"]
    assert isinstance(instruction, str)
    assert "Return exactly one proposal for each requested target" in instruction
    assert "Obey the response schema" in instruction


def test_map_prints_structured_json_when_no_output_path_is_given(
    cli_files: CliFiles,
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    with LocalJsonServer(ScriptedResponse(200, local_model_response("/value"))) as server:
        write_local_model_config(config, server.base_url)
        result = _run(
            "map",
            str(cli_files.source),
            str(cli_files.target),
            environment=_model_environment(config),
        )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["suggestions"][0]["origin"] == "model"
    assert result.stderr == ""


def test_map_defaults_to_local_mapping_without_credentials(
    cli_files: CliFiles,
) -> None:
    environment = os.environ.copy()
    for name in (
        "OPENAI_API_KEY",
        "OPEN_MAPPING_MODEL",
        "OPEN_MAPPING_MODELS_CONFIG",
    ):
        environment.pop(name, None)

    result = _run(
        "map",
        str(cli_files.source),
        str(cli_files.target),
        environment=environment,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["suggestions"][0].get("origin", "deterministic") == "deterministic"
    assert payload.get("model_run_disclosure") is None
    assert result.stderr == ""


def test_root_help_presents_map_as_the_primary_command() -> None:
    result = _run("--help", environment=os.environ.copy())

    assert result.returncode == 0
    assert "Map source data or a schema locally and return structured JSON" in result.stdout
    assert " map " in result.stdout
    assert " build " in result.stdout
    assert " apply " in result.stdout
    for advanced_command in (
        " suggest ",
        " review ",
        " verify ",
        " compile ",
        " benchmark ",
        " models ",
    ):
        assert advanced_command not in result.stdout


def test_map_accepts_json_source_data_without_a_schema(tmp_path: Path) -> None:
    source = tmp_path / "customer.json"
    target = tmp_path / "target.json"
    source.write_text(json.dumps({"name": "Ada"}), encoding="utf-8")
    target.write_text(
        json.dumps(
            {
                "$id": "customer",
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        "map",
        str(source),
        str(target),
        "--source-format",
        "json-data",
        environment=os.environ.copy(),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["suggestions"][0]["selected_source_path"] == "/name"
    assert payload["issues"][0]["code"] == "SOURCE_SCHEMA_INFERRED"


def test_map_rejects_a_selector_for_json_source_data(tmp_path: Path) -> None:
    source = tmp_path / "customer.json"
    target = tmp_path / "target.json"
    source.write_text(json.dumps({"name": "Ada"}), encoding="utf-8")
    target.write_text(
        json.dumps(
            {
                "$id": "customer",
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        "map",
        str(source),
        str(target),
        "--source-format",
        "json-data",
        "--source-selector",
        "component:Customer",
        environment=os.environ.copy(),
    )

    assert result.returncode == 2
    assert "INVALID_INPUT: source selectors are not valid for JSON data" in result.stderr
