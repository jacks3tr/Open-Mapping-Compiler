# Open Mapping Compiler

Open Mapping Compiler turns source and target schemas, sample data, and business rules into portable mappings that can be reviewed, verified, run, and compiled. The default workflow is deterministic and offline.

It supports JSON Schema Draft 2020-12 and OpenAPI 3.1, nested objects and arrays, enum translation, unit conversion, date normalization, bounded expressions, and Python or TypeScript output. Model assistance is optional.

## Install

You need Python 3.12 or later. Install the command and its model-provider support directly from GitHub:

```text
python -m pip install "open-mapping[ai] @ git+https://github.com/jacks3tr/Open-Mapping-Compiler.git"
```

Check the installation:

```text
open-mapping --help
```

## Set up OpenAI

Create `open-mapping.models.yaml` in the directory where you will run the compiler:

```yaml
config_version: "0.1"

providers:
  openai:
    kind: openai
    api_key_env: OPENAI_API_KEY

models:
  openai:
    provider: openai
    model_id: gpt-5
  openai-mini:
    provider: openai
    model_id: gpt-5-mini
```

The same ready-to-copy configuration is stored at [`examples/model-assisted/openai.models.example.yaml`](examples/model-assisted/openai.models.example.yaml). The model IDs link to OpenAI's [GPT-5](https://developers.openai.com/api/docs/models/gpt-5) and [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini) documentation.

Set your API key in the shell. Do not put the key in YAML.

PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
```

macOS or Linux:

```sh
export OPENAI_API_KEY="your-api-key"
```

Check the configuration without making a provider call:

```text
open-mapping models validate --config open-mapping.models.yaml
```

See [Set up the OpenAI provider](docs/openai-provider.md) for a complete example using the files in this repository.

## Get a structured mapping draft

Run `suggest` with your source schema, target schema, and model alias:

```text
open-mapping suggest source.schema.json target.schema.json --model openai-mini --suggestions-out suggestions.json --model-run-report-out model-run.json --require-model
```

This makes one or more schema-constrained provider calls and writes the result to `suggestions.json`. Add `--samples samples.jsonl` or `--hints hints.yaml` when you have those files.

The model returns a draft, not an approved mapping. Open `suggestions.json`, review each proposed target, and copy its `suggestion_report_sha256` into `review.yaml`:

```yaml
review_version: "0.1"
suggestion_report_sha256: "copy this value from suggestions.json"
mapping_id: my-mapping
decisions:
  - target_path: /targetField
    action: accept_selected
    reason: Reviewed and approved.
```

Create the mapping:

```text
open-mapping review suggestions.json --decisions review.yaml --source source.schema.json --target target.schema.json --out mapping.yaml --require-complete-review
```

`mapping.yaml` is the portable mapping file. Verify it before using it:

```text
open-mapping verify mapping.yaml --source source.schema.json --target target.schema.json
```

## Use it without a model

Leave out `--model` and the compiler uses its local matcher. This needs no provider configuration, API key, or network connection:

```text
open-mapping suggest source.schema.json target.schema.json --suggestions-out suggestions.json
```

Review the suggestions and create `mapping.yaml` with the same `review` command shown above. You can also write a mapping directly and run `open-mapping verify` against it. See [USAGE.md](USAGE.md) for mapping expressions, hints, samples, running mappings, and code generation.

## What gets sent to a model

The provider receives bounded schema context, candidate paths, optional instructions, and sample profiles. Raw sample values stay local unless you pass `--allow-raw-samples`.

Provider output is untrusted. A model cannot approve its own mapping, set confidence, override manual hints, or mark a mapping as verified. The review and verification steps stay local and deterministic.

## More documentation

- [OpenAI provider setup](docs/openai-provider.md)
- [Model-assisted mapping](docs/model-assisted-mapping.md)
- [Manual workflow](USAGE.md)
- [Examples](examples)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Apache License 2.0](LICENSE)
