# Quick start

AI generates proposals; the compiler verifies them; the runtime executes an approved bundle. Start by proving installation and execution without credentials.

## Run the installed example

From a checkout, install with `python -m pip install .`, then:

```text
open-mapping demo --out-dir example
open-mapping apply example/mapping.omc --input example/input.json
```

Expected output is `{"customerId":"C-100","displayName":"Ada"}`. The exported directory contains source and target schemas, input, expected output, verification samples, and the bundle. The demo runs outside a repository checkout and never invokes a model.

Rebuild it explicitly:

```text
open-mapping build example/source.json example/target.json --offline --samples example/samples.jsonl --require-samples --mapping-id customer --work-dir work/customer --out customer.omc --report-format json
```

For AI-assisted suggestions, configure your provider credential and replace `--offline` with `--model provider:model-id --require-model`. See the [provider example](../examples/model-assisted/README.md). Do not use an offline identity/rename example as evidence of general model-assisted accuracy.

## Resolve a review-required result

Exit `8` means judgment is required, not that the proposal disappeared. The JSON result identifies the saved draft and generated review. A focused terminal interface uses that same draft:

```text
open-mapping review-draft work/customer/draft.json --interactive --out approved.review.yaml
open-mapping resume work/customer/draft.json --review approved.review.yaml --out customer.omc --report-format json
```

The interface shows unresolved required targets, confidence, context, alternatives, and expressions. Use `--all-targets` to inspect every non-manual decision. Sample previews require `--show-sample-values` because they can expose saved customer data. Manual business hints must be changed through a new build, not overridden by review.

Resume uses the original report, contracts, samples, and verification policy, with no new inference. It does not require the original source files or provider key. A review can still leave required decisions unresolved; the result remains `needs_review`. Never blindly accept every suggestion to obtain a green result.

Changing schemas, hints, instructions, or verification samples requires a new build. Use a new work directory or deliberately replace artifacts with `--force`. Saved drafts contain sample data; keep them under your application's access controls.

## Execute and embed

```python
from open_mapping import Mapper

mapper = Mapper.load("example/mapping.omc")
assert mapper.transform({"customer_id": "C-100", "name": "Ada"}) == {
    "customerId": "C-100", "displayName": "Ada"
}
```

Use [JSONL](workflow-integration.md) for streams, the [sidecar](server.md) for other languages, and [schema impact](sdk.md#schema-inference-and-maintenance) before changing an existing integration.
