"""Machine-readable build lifecycle and installed-demo behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_mapping import Compiler
from open_mapping.cli.app import app


def _schemas(tmp_path: Path, *, review: bool) -> tuple[Path, Path]:
    raw = {
        "$id": "customer",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "description": "Canonical name"}},
    }
    source, target = tmp_path / "source.json", tmp_path / "target.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    if review:
        del raw["properties"]["name"]["description"]  # type: ignore[index]
    target.write_text(json.dumps(raw), encoding="utf-8")
    return source, target


@pytest.mark.parametrize("review", [False, True])
def test_build_json_has_one_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, review: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    source, target = _schemas(tmp_path, review=review)
    result = CliRunner().invoke(
        app, ["build", str(source), str(target), "--offline", "--report-format", "json"]
    )
    assert result.exit_code == (8 if review else 0), result.output
    body = json.loads(result.stdout)
    assert body["status"] == ("needs_review" if review else "ready")
    assert set(body) == {"status", "mapping_id", "issues", "artifact_paths", "verification"}
    assert Path(body["artifact_paths"]["draft"]).is_file()


def test_build_failure_is_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "build",
            str(tmp_path / "missing.json"),
            str(tmp_path / "absent.json"),
            "--report-format",
            "json",
        ],
    )
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["status"] == "failed" and body["issues"]
    assert body["artifact_paths"] == {}


def test_resume_uses_saved_samples_without_suggest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source, target = _schemas(tmp_path, review=True)
    samples = tmp_path / "samples.jsonl"
    samples.write_text('{"id":"one","input":{"name":"Ada"}}\n', encoding="utf-8")
    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "build",
            str(source),
            str(target),
            "--offline",
            "--samples",
            str(samples),
            "--require-samples",
            "--report-format",
            "json",
        ],
    )
    assert first.exit_code == 8, first.output
    paths = json.loads(first.stdout)["artifact_paths"]
    import yaml

    review_path = Path(paths["review"])
    review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    for decision in review["decisions"]:
        decision.update(action="accept_selected", reason="Checked against the contract.")
    review_path.write_text(yaml.safe_dump(review), encoding="utf-8")
    samples.unlink()
    source.unlink()
    target.unlink()

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("resume attempted inference")

    monkeypatch.setattr(Compiler, "suggest", forbidden)
    second = runner.invoke(
        app,
        [
            "resume",
            paths["draft"],
            "--review",
            str(review_path),
            "--out",
            str(tmp_path / "ready.omc"),
            "--report-format",
            "json",
        ],
        catch_exceptions=False,
    )
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["verification"]["sample_count"] == 1


def test_demo_exports_a_complete_working_example(tmp_path: Path) -> None:
    runner = CliRunner()
    exported = tmp_path / "example"
    result = runner.invoke(app, ["demo", "--out-dir", str(exported)])
    assert result.exit_code == 0, result.output
    expected = json.loads((exported / "expected.json").read_text(encoding="utf-8"))
    transformed = runner.invoke(
        app,
        [
            "apply",
            str(exported / "mapping.omc"),
            "--input",
            str(exported / "input.json"),
        ],
    )
    assert transformed.exit_code == 0, transformed.output
    assert json.loads(transformed.stdout) == expected
    again = runner.invoke(app, ["demo", "--out-dir", str(exported)])
    assert again.exit_code == 2


def test_build_does_not_overwrite_a_schema_with_generated_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source, target = _schemas(tmp_path, review=True)
    collision = tmp_path / "customer.review.yaml"
    source.rename(collision)
    original = collision.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("output collisions must fail before inference")

    monkeypatch.setattr(Compiler, "suggest", forbidden)
    result = CliRunner().invoke(
        app,
        [
            "build",
            str(collision),
            str(target),
            "--mapping-id",
            "customer",
            "--force",
            "--report-format",
            "json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["status"] == "failed"
    assert collision.read_bytes() == original


def test_keyless_demo_ignores_environment_and_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_MAPPING_MODEL", "invalid:model")
    result = CliRunner().invoke(app, ["demo"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["status"] == "ready" and body["output"] == body["expected"]
