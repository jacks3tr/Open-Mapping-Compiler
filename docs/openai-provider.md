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

Set `OPEN_MAPPING_MODEL=openai:<model-id>` when an environment-level selection is more convenient. The compiler sends sanitized schema context, constrains the model to known source paths and operations, and statically verifies the returned proposals.

The repository includes [`examples/model-assisted`](../examples/model-assisted/README.md) with two schemas you can map. The included `openai.models.example.yaml` file is for named aliases and custom model parameters; the normal `map` command does not require it.

See [AI mapping](model-assisted-mapping.md) for the request contents, structured response, privacy behavior, and advanced endpoints.

For a deterministic offline fallback, omit `--model`. The command returns the same typed result without calling a provider.
