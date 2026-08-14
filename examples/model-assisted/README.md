# Model-assisted customer mapping

This example maps a customer record into an account record. It includes two manual business rules for target state and source system. A model can draft the remaining account-number rule, but a review file must approve that draft before the mapping is assembled.

For OpenAI, copy `openai.models.example.yaml` to `open-mapping.models.yaml` and set `OPENAI_API_KEY` in your shell. The file already defines `gpt-5` and `gpt-5-mini`. Follow the [OpenAI provider setup](../../docs/openai-provider.md) for the complete commands.

For a local service, copy `open-mapping.models.example.yaml` instead. `local-draft` is for an OpenAI-compatible endpoint on your machine. `native-draft` shows the general native-provider configuration shape.

Follow the [model-assisted mapping guide](../../docs/model-assisted-mapping.md) for the commands, context preview, review file, verification, and compilation steps. The [baseline guide](../../USAGE.md) describes the offline workflow.
