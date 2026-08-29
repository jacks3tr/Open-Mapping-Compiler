# Model-assisted schema mapping

This folder contains a source customer schema and a target account schema.

Install `open-mapping`, set `OPENAI_API_KEY`, then run this command from the repository root:

```text
open-mapping map examples/model-assisted/source.schema.json examples/model-assisted/target.schema.json --model openai:gpt-5-mini --out mapping.json
```

Open `mapping.json` to review the proposed field mappings and transformations. An application can read the same file as JSON.

The native OpenAI shorthand needs no configuration file. `openai.models.example.yaml` is only needed when you want named aliases or custom model parameters.
