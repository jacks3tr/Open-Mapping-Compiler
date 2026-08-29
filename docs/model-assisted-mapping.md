# AI mapping

AI is the recommended path for producing a high-quality first pass across systems that use different names and business language. Select a model explicitly:

```text
open-mapping map source.schema.json target.schema.json --model openai:gpt-5-mini --out mapping.json
```

You can also set `OPEN_MAPPING_MODEL=provider:model-id` so the same `map` command and `map_schemas` function use that model without a per-call flag. Set the matching provider credential in the environment.

Native model names use these environment variables:

- `openai:<model-id>` uses `OPENAI_API_KEY`.
- `anthropic:<model-id>` uses `ANTHROPIC_API_KEY`.
- `google:<model-id>` uses `GOOGLE_API_KEY`.

## What the provider receives

The request contains sanitized schema fields, candidate source paths, allowed mapping operations, and the response schema. Schema descriptions are treated as untrusted data. Raw sample records stay local unless both `--samples` and `--allow-raw-samples` are supplied.

The system prompt requires one structured proposal for each target field. It restricts the model to allowed source paths and mapping operations, asks it to explain each proposal, and tells it to abstain when the schemas do not provide enough information.

## What the command returns

The JSON result records each target field, proposed source paths, transformation expressions, supporting evidence, alternatives, ambiguous or unmapped fields, and sanitized provider metadata. It does not contain credentials or raw provider responses.

Model proposals are not treated as approved business rules. The result is meant for human review or for a tool that applies its own approval policy.

## Deterministic offline fallback

Omit `--model` when a provider is unavailable or the mapping must stay fully offline. The fallback uses the same inputs and returns the same typed result without an API key or mapping pack. It is intentionally conservative and leaves uncertain decisions for review.

## Advanced provider configuration

Use `open-mapping.models.yaml` for OpenAI-compatible services, custom HTTP endpoints, named aliases, or custom model parameters. The files in [`examples/model-assisted`](../examples/model-assisted) show the configuration format.

Provider billing, retention, availability, and model behavior are controlled by the selected provider.
