# Model-assisted mapping

Model assistance can add draft suggestions to the deterministic mapper. It is optional. A provider call happens only when you pass `--model`; having a configuration file in the working directory does not make a call.

The model returns a draft. It does not approve a mapping, set its confidence, or verify it. Review the suggestion report, record decisions in a review file, and run verification before using the mapping.

This guide uses the files in [`examples/model-assisted`](../examples/model-assisted). Install the project first as described in the [baseline quick start](quick-start.md). The commands below use the installed `open-mapping` entry point. From a repository checkout, prefix them with `uv run`.

For a shorter OpenAI-specific walkthrough with ready-to-copy `gpt-5` and `gpt-5-mini` aliases, see [Set up the OpenAI provider](openai-provider.md).

## Configuration terms

A provider is the connection type used to call a service. The configuration names each provider and its settings. A model alias is a user-defined name such as `local-draft`; pass that alias to `--model`. A model ID is the identifier understood by the selected provider. You choose the alias, while the provider defines the model ID format.

Keep secrets outside YAML. The configuration stores the name of an environment variable, never its value. The project looks for a configuration supplied through `--models-config`, then `OPEN_MAPPING_MODELS_CONFIG`, then `./open-mapping.models.yaml`.

## Configure the example

Copy the tracked example before editing it. The local-compatible entry has a loopback URL and no credential field. Replace its port and model ID with the values exposed by your local service. The native entry shows the shape for a provider that uses a credential environment variable. Replace its model ID with one issued by that provider.

```text
Copy-Item examples/model-assisted/open-mapping.models.example.yaml open-mapping.models.yaml
```

For the native entry, set the environment variable named by `api_key_env`. This PowerShell example sets a value only in the current shell:

```text
$env:OPEN_MAPPING_NATIVE_PROVIDER_TOKEN = "your-provider-credential"
```

Do not put that value in `open-mapping.models.yaml`, a command argument, or a committed file.

Validate the configuration locally. Validation reads the file but does not contact a provider.

```text
open-mapping models validate --config open-mapping.models.yaml
```

The example has two aliases:

- `local-draft` uses an OpenAI-compatible service on your machine. It is suitable for a local server that accepts Chat Completions requests.
- `native-draft` uses the native OpenAI provider shape and reads `OPEN_MAPPING_NATIVE_PROVIDER_TOKEN` only when it makes a call. The same configuration form supports the other native provider kinds with their own provider-issued model IDs.

## Inspect the model context

Before making a call, write the exact sanitized context package that the selected alias would receive:

```text
open-mapping model-context examples/model-assisted/source.schema.json examples/model-assisted/target.schema.json --models-config open-mapping.models.yaml --model local-draft --samples examples/model-assisted/samples.jsonl --hints examples/model-assisted/hints.yaml --out build/model-assisted/model-context.json
```

Open `build/model-assisted/model-context.json` and confirm that its schema fields, candidate paths, profiles, and business instructions are appropriate for the provider. Raw sample values are omitted by default. Pass `--allow-raw-samples` only when you have confirmed that the provider may receive the data. The command records whether raw samples were included.

Each model can select a context mode in the configuration:

- `auto` starts with full source context and switches to targeted context when the full package does not fit the configured input budget.
- `full` includes all source fields for each target batch.
- `targeted` includes the candidate source fields and related context for each target batch.

Choose the smallest mode that gives the provider enough information. Context mode changes what the model can see, not what the verifier accepts.

## Produce a draft

Run `suggest` with an explicit alias. This is the step that may contact a provider and incur provider charges. The example uses the local-compatible alias after you have pointed it at your local service.

```text
open-mapping suggest examples/model-assisted/source.schema.json examples/model-assisted/target.schema.json --models-config open-mapping.models.yaml --model local-draft --samples examples/model-assisted/samples.jsonl --hints examples/model-assisted/hints.yaml --suggestions-out build/model-assisted/suggestions.json --model-run-report-out build/model-assisted/model-run.json --report-format text
```

Inspect `build/model-assisted/suggestions.json` before approving anything. The report identifies model-originated drafts and records bounded run metadata. `build/model-assisted/model-run.json` records sanitized provenance such as the configuration digest, context hashes, response hashes, and provider usage when it is available.

If a model call fails, `suggest` keeps the deterministic baseline suggestions and emits a warning. Add `--require-model` to the `suggest` command when a failed or invalid model call must stop the command with exit code `5` and avoid a fallback result. A successful model response can still abstain from a target; abstention is not a failure.

The provider adapters use one response contract, and verification is deterministic. Different providers and model IDs can still produce different drafts, costs, latency, and mapping quality.

## Review, verify, and compile

Create `build/model-assisted/review.yaml` after reading the suggestion report. Its hash must match `suggestion_report_sha256` in `suggestions.json`. The two targets covered by `hints.yaml` are manual business rules, so do not include review decisions for them.

```yaml
review_version: "0.1"
suggestion_report_sha256: "copy-the-value-from-suggestions-json"
mapping_id: customer-to-account
decisions:
  - target_path: /account_number
    action: accept_selected
    reason: The reviewed customer identifier is the account number.
```

Apply the review file. The review command rejects stale hashes, invalid decisions, and incomplete non-manual review.

```text
open-mapping review build/model-assisted/suggestions.json --decisions build/model-assisted/review.yaml --source examples/model-assisted/source.schema.json --target examples/model-assisted/target.schema.json --out build/model-assisted/mapping.yaml --review-report-out build/model-assisted/review.json --require-complete-review
```

Verify the approved mapping against the schemas and samples:

```text
open-mapping verify build/model-assisted/mapping.yaml --source examples/model-assisted/source.schema.json --target examples/model-assisted/target.schema.json --samples examples/model-assisted/samples.jsonl --report-format text
```

Compile it for an application after verification succeeds:

```text
open-mapping compile build/model-assisted/mapping.yaml --source examples/model-assisted/source.schema.json --target examples/model-assisted/target.schema.json --target-language python --out build/model-assisted/generated_mapping.py
```

The [baseline guide](../USAGE.md) covers hints, review actions, verification, running a mapping, and TypeScript compilation without provider configuration.
