"""Public in-process schema mapping API."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.providers.model_transport_support import LocalJsonServer, ScriptedResponse
from tests.support.streamlined import (
    local_model_response,
    source_schema,
    target_schema,
    write_local_model_config,
)


def test_map_schemas_returns_the_same_structured_result_used_by_the_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from open_mapping import map_schemas

    monkeypatch.delenv("OPEN_MAPPING_MODEL", raising=False)
    local_result = map_schemas(source_schema(), target_schema())
    config = tmp_path / "models.yaml"
    with LocalJsonServer(ScriptedResponse(200, local_model_response("/name"))) as server:
        write_local_model_config(config, server.base_url)
        result = map_schemas(
            source_schema(),
            target_schema(),
            model="mapper",
            models_config=config,
        )

    assert result.report_version == "0.1"
    assert type(result) is type(local_result)
    assert [item.target_path for item in result.suggestions] == [
        item.target_path for item in local_result.suggestions
    ]
    assert result.suggestions[0].origin.value == "model"
    assert result.model_run_disclosure is not None
    assert result.model_run_disclosure.model_alias == "mapper"


def test_map_schemas_defaults_to_deterministic_local_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from open_mapping import map_schemas
    from open_mapping.model.suggestions import SuggestionOrigin

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_MAPPING_MODEL", raising=False)
    monkeypatch.delenv("OPEN_MAPPING_MODELS_CONFIG", raising=False)

    result = map_schemas(source_schema(), target_schema())

    assert result.suggestions[0].origin is SuggestionOrigin.DETERMINISTIC
    assert result.model_run_disclosure is None


def test_map_schemas_uses_the_explicit_environment_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from open_mapping import map_schemas

    config = tmp_path / "models.yaml"
    with LocalJsonServer(ScriptedResponse(200, local_model_response("/name"))) as server:
        write_local_model_config(config, server.base_url)
        monkeypatch.setenv("OPEN_MAPPING_MODEL", "mapper")
        monkeypatch.setenv("OPEN_MAPPING_MODELS_CONFIG", str(config))
        result = map_schemas(source_schema(), target_schema())

    assert result.model_run_disclosure is not None
    assert result.model_run_disclosure.model_alias == "mapper"


def test_map_schemas_accepts_openapi_32_component_selections(tmp_path: Path) -> None:
    from open_mapping import map_schemas

    source = tmp_path / "source.openapi.yaml"
    target = tmp_path / "target.openapi.yaml"
    source.write_text(
        """openapi: 3.2.0
info: {title: source, version: "1"}
components:
  schemas:
    Source:
      $id: source
      type: object
      required: [readingId]
      properties:
        readingId: {type: string, description: Stable reading identifier}
""",
        encoding="utf-8",
    )
    target.write_text(
        """openapi: 3.2.0
info: {title: target, version: "1"}
components:
  schemas:
    Target:
      $id: target
      type: object
      required: [readingId]
      properties:
        readingId: {type: string, description: Stable reading identifier}
""",
        encoding="utf-8",
    )

    result = map_schemas(
        source,
        target,
        source_format="openapi",
        source_selector="component:Source",
        target_format="openapi",
        target_selector="component:Target",
    )

    assert result.suggestions[0].target_path == "/readingId"
    assert result.suggestions[0].selected_source_path == "/readingId"


def test_map_schemas_infers_a_reviewable_schema_from_json_data() -> None:
    from open_mapping import map_schemas
    from open_mapping.model.issues import IssueCode

    result = map_schemas(
        {"name": "Ada"},
        target_schema(),
        source_format="json-data",
    )

    assert result.suggestions[0].selected_source_path == "/name"
    assert result.suggestions[0].confidence_score == 0.95
    assert result.source_schema_id.startswith("urn:open-mapping:inferred-source:")
    assert [issue.code for issue in result.issues] == [IssueCode.SOURCE_SCHEMA_INFERRED]


def test_json_source_data_stays_local_during_default_model_assistance(tmp_path: Path) -> None:
    from open_mapping import map_schemas

    config = tmp_path / "models.yaml"
    with LocalJsonServer(ScriptedResponse(200, local_model_response("/name"))) as server:
        write_local_model_config(config, server.base_url)
        result = map_schemas(
            {"name": "Ada-private-value"},
            target_schema(),
            source_format="json-data",
            model="mapper",
            models_config=config,
        )
        request = server.requests[0].body

    assert result.model_run_disclosure is not None
    assert result.model_run_disclosure.raw_samples_included is False
    assert "Ada-private-value" not in str(request)
