"""One-command build contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from open_mapping import Mapper
from open_mapping.cli.app import app
from open_mapping.serialization.bundles import load_bundle


def test_build_creates_a_ready_bundle(tmp_path: Path) -> None:
    schema = {
        "$id": "customer",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "description": "Canonical name"}},
    }
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    bundle = tmp_path / "mapping.omc"
    source.write_text(json.dumps(schema), encoding="utf-8")
    target.write_text(json.dumps(schema), encoding="utf-8")

    result = CliRunner().invoke(app, ["build", str(source), str(target), "--out", str(bundle)])

    assert result.exit_code == 0, result.output
    assert bundle.is_file()
    assert result.output.startswith("READY")
    assert "static verification only" in result.stdout
    assert result.stderr == ""


def test_build_records_sample_verification_and_requires_samples_when_requested(
    tmp_path: Path,
) -> None:
    schema = {
        "$id": "customer",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "description": "Canonical name"}},
    }
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    samples = tmp_path / "samples.jsonl"
    bundle = tmp_path / "mapping.omc"
    source.write_text(json.dumps(schema), encoding="utf-8")
    target.write_text(json.dumps(schema), encoding="utf-8")
    samples.write_text('{"id":"one","input":{"name":"Ada"}}\n', encoding="utf-8")
    runner = CliRunner()

    missing = runner.invoke(
        app,
        [
            "build",
            str(source),
            str(target),
            "--require-samples",
            "--out",
            str(bundle),
        ],
    )
    assert missing.exit_code == 2
    assert not bundle.exists()

    result = runner.invoke(
        app,
        [
            "build",
            str(source),
            str(target),
            "--samples",
            str(samples),
            "--out",
            str(bundle),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "1 samples passed" in result.stdout
    assert load_bundle(bundle).verification.level.value == "samples"
    assert Mapper.load(bundle).transform({"name": "Ada"}) == {"name": "Ada"}


def test_build_infers_source_schema_and_samples_from_json_data(tmp_path: Path) -> None:
    source = tmp_path / "customers.json"
    target = tmp_path / "target.json"
    bundle = tmp_path / "mapping.omc"
    source.write_text(json.dumps([{"name": "Ada"}, {"name": "Grace"}]), encoding="utf-8")
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

    result = CliRunner().invoke(
        app,
        [
            "build",
            str(source),
            str(target),
            "--source-format",
            "json-data",
            "--require-samples",
            "--out",
            str(bundle),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "2 samples passed" in result.stdout
    built = load_bundle(bundle)
    assert built.source_schema.schema_id.startswith("urn:open-mapping:inferred-source:")
    assert Mapper.load(bundle).transform({"name": "Katherine"}) == {"name": "Katherine"}


def test_build_refuses_overwrite_without_force_and_replaces_with_force(tmp_path: Path) -> None:
    schema = {
        "$id": "customer",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "description": "Canonical name"}},
    }
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    bundle = tmp_path / "mapping.omc"
    source.write_text(json.dumps(schema), encoding="utf-8")
    target.write_text(json.dumps(schema), encoding="utf-8")
    bundle.write_text("keep", encoding="utf-8")
    runner = CliRunner()

    refused = runner.invoke(app, ["build", str(source), str(target), "--out", str(bundle)])
    assert refused.exit_code == 2
    assert bundle.read_text(encoding="utf-8") == "keep"

    replaced = runner.invoke(
        app, ["build", str(source), str(target), "--out", str(bundle), "--force"]
    )
    assert replaced.exit_code == 0, replaced.output
    assert load_bundle(bundle).mapping.id == "source-to-target"


def test_build_generates_review_and_reruns_without_manual_hash_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_schema = {
        "$id": "source",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "description": "Source label"}},
    }
    target_schema = {
        "$id": "target",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    work = tmp_path / "audit"
    bundle = tmp_path / "mapping.omc"
    source.write_text(json.dumps(source_schema), encoding="utf-8")
    target.write_text(json.dumps(target_schema), encoding="utf-8")
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(
        app,
        [
            "build",
            str(source),
            str(target),
            "--mapping-id",
            "customer",
            "--work-dir",
            str(work),
            "--out",
            str(bundle),
        ],
        catch_exceptions=False,
    )

    assert first.exit_code == 8, first.output
    review_path = tmp_path / "customer.review.yaml"
    try:
        review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
        assert review["suggestion_report_sha256"]
        review["decisions"][0]["action"] = "accept_selected"
        review["decisions"][0]["reason"] = "The source field is authoritative."
        review_path.write_text(yaml.safe_dump(review, sort_keys=True), encoding="utf-8")

        second = runner.invoke(
            app,
            [
                "build",
                str(source),
                str(target),
                "--mapping-id",
                "customer",
                "--work-dir",
                str(work),
                "--review",
                str(review_path),
                "--out",
                str(bundle),
            ],
            catch_exceptions=False,
        )

        assert second.exit_code == 0, second.output
        assert bundle.is_file()
    finally:
        review_path.unlink(missing_ok=True)
