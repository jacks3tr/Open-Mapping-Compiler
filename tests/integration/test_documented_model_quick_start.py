"""The documented model-assisted workflow runs against a local compatible provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, cast

import pytest

from open_mapping.providers.config import load_model_provider_config
from tests.support.package_env import build_release, install_wheel, run_checked

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples/model-assisted"


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _model_response(context: dict[str, object]) -> dict[str, object]:
    proposals: list[dict[str, object]] = []
    target_requests = cast(list[dict[str, object]], context["target_requests"])
    for target_request in target_requests:
        target = cast(dict[str, object], target_request["target"])
        target_path = cast(str, target["pointer"])
        if target_path == "/account_number":
            proposals.append(
                {
                    "target_path": target_path,
                    "action": "propose",
                    "selected_source_paths": ["/customer_id"],
                    "expression": {
                        "op": "get",
                        "path": "/customer_id",
                        "document": "input",
                    },
                    "reason": "Customer identifiers supply account numbers after review.",
                    "evidence": ["The candidate is the customer identifier."],
                }
            )
        else:
            proposals.append(
                {
                    "target_path": target_path,
                    "action": "abstain",
                    "selected_source_paths": [],
                    "expression": None,
                    "reason": "A local fake abstains from this target.",
                    "evidence": [],
                }
            )
    return {
        "protocol_version": context["protocol_version"],
        "prompt_version": context["prompt_version"],
        "context_sha256": _canonical_sha256(context),
        "batch_id": context["batch_id"],
        "proposals": proposals,
    }


class _LocalCompatibleHandler(BaseHTTPRequestHandler):
    fail_requests: ClassVar[bool] = False
    requests: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = cast(dict[str, object], json.loads(self.rfile.read(length)))
        type(self).requests.append(request)
        if type(self).fail_requests:
            self.send_response(503)
            self.end_headers()
            return

        messages = cast(list[dict[str, object]], request["messages"])
        user_message = messages[1]
        context = cast(dict[str, object], json.loads(cast(str, user_message["content"])))
        content = json.dumps(_model_response(context), separators=(",", ":"))
        body = json.dumps(
            {
                "id": "local-compatible-fake",
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 23, "completion_tokens": 17},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def fake_local_provider() -> Generator[str]:
    _LocalCompatibleHandler.fail_requests = False
    _LocalCompatibleHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalCompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _write_local_config(workspace: Path, provider_url: str) -> Path:
    config = (workspace / "examples/model-assisted/open-mapping.models.example.yaml").read_text(
        encoding="utf-8"
    )
    config = config.replace("http://127.0.0.1:8080/v1", provider_url)
    config = config.replace("<local-model-id>", "local-compatible-fake")
    destination = workspace / "open-mapping.models.yaml"
    destination.write_text(config, encoding="utf-8")
    return destination


def _environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment.update({"CI": "true", "NO_COLOR": "1"})
    return environment


def _run(
    command: Path,
    *args: str,
    workspace: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [command, *args],
        cwd=workspace,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _write_review(suggestions: Path, destination: Path) -> None:
    report = cast(dict[str, object], json.loads(suggestions.read_text(encoding="utf-8")))
    report_hash = cast(str, report["suggestion_report_sha256"])
    destination.write_text(
        "\n".join(
            (
                'review_version: "0.1"',
                f'suggestion_report_sha256: "{report_hash}"',
                "mapping_id: customer-to-account",
                "decisions:",
                "  - target_path: /account_number",
                "    action: accept_selected",
                "    reason: Review the customer identifier as the account number.",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_documented_model_quick_start_runs_with_a_local_compatible_provider(
    tmp_path: Path, fake_local_provider: str
) -> None:
    wheel, _ = build_release(ROOT, tmp_path / "dist")
    python, command = install_wheel(wheel, tmp_path / "venv", root=ROOT)
    run_checked(
        ["uv", "pip", "install", "--python", str(python), f"{wheel}[ai]"],
        cwd=ROOT,
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(EXAMPLE, workspace / "examples/model-assisted")
    config = _write_local_config(workspace, fake_local_provider)
    environment = _environment()
    source = "examples/model-assisted/source.schema.json"
    target = "examples/model-assisted/target.schema.json"
    samples = "examples/model-assisted/samples.jsonl"
    hints = "examples/model-assisted/hints.yaml"

    run_checked(
        [command, "models", "validate", "--config", config.name],
        cwd=workspace,
        environment=environment,
    )
    run_checked(
        [
            command,
            "model-context",
            source,
            target,
            "--models-config",
            config.name,
            "--model",
            "local-draft",
            "--samples",
            samples,
            "--hints",
            hints,
            "--out",
            "build/model-assisted/model-context.json",
        ],
        cwd=workspace,
        environment=environment,
    )
    run_checked(
        [
            command,
            "suggest",
            source,
            target,
            "--models-config",
            config.name,
            "--model",
            "local-draft",
            "--samples",
            samples,
            "--hints",
            hints,
            "--suggestions-out",
            "build/model-assisted/suggestions.json",
            "--model-run-report-out",
            "build/model-assisted/model-run.json",
            "--report-format",
            "text",
        ],
        cwd=workspace,
        environment=environment,
    )

    output = workspace / "build/model-assisted"
    suggestions = cast(
        dict[str, object], json.loads((output / "suggestions.json").read_text(encoding="utf-8"))
    )
    suggestions_by_target = {
        cast(str, item["target_path"]): item
        for item in cast(list[dict[str, object]], suggestions["suggestions"])
    }
    assert suggestions_by_target["/account_number"]["origin"] == "model"
    assert suggestions_by_target["/state"]["disposition"] == "manual"
    assert suggestions_by_target["/source_system"]["disposition"] == "manual"
    context = cast(
        dict[str, object], json.loads((output / "model-context.json").read_text(encoding="utf-8"))
    )
    assert context["raw_samples_included"] is False
    assert "C-1001" not in (output / "model-context.json").read_text(encoding="utf-8")
    assert len(_LocalCompatibleHandler.requests) == 1
    assert "C-1001" not in json.dumps(_LocalCompatibleHandler.requests[0], sort_keys=True)

    review = output / "review.yaml"
    _write_review(output / "suggestions.json", review)
    run_checked(
        [
            command,
            "review",
            "build/model-assisted/suggestions.json",
            "--decisions",
            "build/model-assisted/review.yaml",
            "--source",
            source,
            "--target",
            target,
            "--out",
            "build/model-assisted/mapping.yaml",
            "--review-report-out",
            "build/model-assisted/review.json",
            "--require-complete-review",
        ],
        cwd=workspace,
        environment=environment,
    )
    run_checked(
        [
            command,
            "verify",
            "build/model-assisted/mapping.yaml",
            "--source",
            source,
            "--target",
            target,
            "--samples",
            samples,
            "--report-format",
            "text",
        ],
        cwd=workspace,
        environment=environment,
    )
    run_checked(
        [
            command,
            "compile",
            "build/model-assisted/mapping.yaml",
            "--source",
            source,
            "--target",
            target,
            "--target-language",
            "python",
            "--out",
            "build/model-assisted/generated_mapping.py",
        ],
        cwd=workspace,
        environment=environment,
    )
    assert (output / "mapping.yaml").is_file()
    assert (output / "review.json").is_file()
    assert (output / "generated_mapping.py").is_file()

    _LocalCompatibleHandler.fail_requests = True
    fallback = _run(
        command,
        "suggest",
        source,
        target,
        "--models-config",
        config.name,
        "--model",
        "local-draft",
        "--samples",
        samples,
        "--hints",
        hints,
        "--suggestions-out",
        "build/model-assisted/fallback.json",
        "--report-format",
        "json",
        workspace=workspace,
        environment=environment,
    )
    assert fallback.returncode == 0, fallback.stderr
    assert "PROVIDER_FAILURE" in fallback.stderr
    assert (output / "fallback.json").is_file()

    required_output = output / "required.json"
    required = _run(
        command,
        "suggest",
        source,
        target,
        "--models-config",
        config.name,
        "--model",
        "local-draft",
        "--require-model",
        "--samples",
        samples,
        "--hints",
        hints,
        "--suggestions-out",
        "build/model-assisted/required.json",
        "--report-format",
        "json",
        workspace=workspace,
        environment=environment,
    )
    assert required.returncode == 5
    assert "PROVIDER_FAILURE" in required.stderr
    assert not required_output.exists()


def test_model_assisted_example_contains_no_literal_credential_value() -> None:
    configuration = EXAMPLE / "open-mapping.models.example.yaml"
    text = configuration.read_text(encoding="utf-8")
    parsed = load_model_provider_config(configuration)

    assert parsed.providers["local-compatible"].api_key_env is None
    assert parsed.providers["native-provider"].api_key_env == "OPEN_MAPPING_NATIVE_PROVIDER_TOKEN"
    assert "<local-model-id>" in text
    assert "<provider-model-id>" in text
    assert not re.search(r"(?im)^\s*(?:api_key|token|authorization|secret)\s*:", text)
    assert not re.search(r"(?i)(?:sk-|bearer\s+|AIza|github_pat_|ghp_)", text)


def test_local_model_configuration_variants_are_ignored_except_the_example() -> None:
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (
        "**/open-mapping.models.yaml",
        "**/open-mapping.models.yml",
        "**/open-mapping.models.*.yaml",
        "**/open-mapping.models.*.yml",
    ):
        assert pattern in ignore_rules
    assert "!/examples/model-assisted/open-mapping.models.example.yaml" in ignore_rules
