# Use OpenAI to map schemas

Install model support and set your key:

```text
pip install open-mapping
```

Set `OPENAI_API_KEY` in the process environment. Do not put the key in YAML, command arguments, or Git.

Then map two schemas:

```text
open-mapping map source.schema.json target.schema.json --model openai:gpt-5-mini --out mapping.json
```

Omit `--model` for local deterministic mapping. Set `OPEN_MAPPING_MODEL=openai:<model-id>` when an environment-level default is more convenient.

The repository includes [`examples/model-assisted`](../examples/model-assisted/README.md) with two schemas you can map. The included `openai.models.example.yaml` file is for named aliases and custom model parameters; the normal `map` command does not require it.

See [model-assisted mapping](model-assisted-mapping.md) for the request contents, structured response, privacy behavior, and advanced endpoints.
