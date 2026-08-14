# Set up the OpenAI provider

This example uses OpenAI's Responses API to draft a mapping for the customer schemas in `examples/model-assisted`. The compiler requests structured output, checks the returned expression, and writes a suggestion report for review.

## Install the command

Install Open Mapping Compiler with model-provider support:

```text
python -m pip install "open-mapping[ai] @ git+https://github.com/jacks3tr/Open-Mapping-Compiler.git"
```

If you are working from a repository checkout, use `uv run open-mapping` in place of `open-mapping` in the commands below.

## Copy the OpenAI configuration

The repository includes a configuration with `gpt-5` and `gpt-5-mini` already named. Copy it to the repository root.

PowerShell:

```powershell
Copy-Item examples/model-assisted/openai.models.example.yaml open-mapping.models.yaml
```

macOS or Linux:

```sh
cp examples/model-assisted/openai.models.example.yaml open-mapping.models.yaml
```

Set your API key in the current shell.

PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
```

macOS or Linux:

```sh
export OPENAI_API_KEY="your-api-key"
```

The YAML contains the environment variable name, not the key itself. Keep the real key out of files, command arguments, and Git.

Validate the file without contacting OpenAI:

```text
open-mapping models validate --config open-mapping.models.yaml
```

## Request a structured draft

Run the compiler from the repository root:

```text
open-mapping suggest examples/model-assisted/source.schema.json examples/model-assisted/target.schema.json --model openai-mini --samples examples/model-assisted/samples.jsonl --hints examples/model-assisted/hints.yaml --suggestions-out suggestions.json --model-run-report-out model-run.json --require-model
```

The command writes:

- `suggestions.json`, which contains the deterministic candidates and model draft;
- `model-run.json`, which contains sanitized hashes, usage metadata when available, and provider issues.

No mapping is approved yet. Open `suggestions.json` and find `suggestion_report_sha256`. Create `review.yaml` with that hash:

```yaml
review_version: "0.1"
suggestion_report_sha256: "copy this value from suggestions.json"
mapping_id: customer-to-account
decisions:
  - target_path: /account_number
    action: accept_selected
    reason: The proposed source field was reviewed and approved.
```

The example hints already define `/state` and `/source_system`, so the review only covers `/account_number`.

Create the mapping:

```text
open-mapping review suggestions.json --decisions review.yaml --source examples/model-assisted/source.schema.json --target examples/model-assisted/target.schema.json --out mapping.yaml --require-complete-review
```

Verify it against the schemas and example samples:

```text
open-mapping verify mapping.yaml --source examples/model-assisted/source.schema.json --target examples/model-assisted/target.schema.json --samples examples/model-assisted/samples.jsonl
```

`mapping.yaml` is now ready to run or compile. The [model-assisted mapping guide](model-assisted-mapping.md) covers context previews, provider failure behavior, raw-sample controls, and compilation.
