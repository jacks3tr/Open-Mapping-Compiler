# Open Mapping Compiler

Generate reviewable mappings from JSON data, JSON Schema, or selected OpenAPI contracts. Use your model provider or the deterministic offline matcher, resolve uncertain decisions, and compile a verified `.omc` bundle. Load the bundle once and transform records without further model calls.

The library owns mapping, review, verification, and execution. Your product owns business-system connections, authentication, scheduling, retries, storage, and billing. No database, workflow service, model account, or frontend framework is required.

## First success, without an API key

From a checkout:

```text
git clone https://github.com/jacks3tr/Open-Mapping-Compiler.git
cd Open-Mapping-Compiler
python -m pip install .
open-mapping demo --out-dir example
open-mapping apply example/mapping.omc --input example/input.json
```

The demo is included in the installed package, works outside the checkout, ignores model environment settings, and exports every input plus the expected output and verified bundle. It maps `customer_id` to `customerId` and `name` to `displayName`.

PyPI installation is `python -m pip install open-mapping` **after a successful registry release**. A GitHub tag or wheel build alone does not establish that the package was published. Until the trusted publisher is configured and the published-install check passes, use the checkout installation above. See [release setup](docs/releasing.md).

## Choose your integration path

| Goal | Start here |
| --- | --- |
| Generate and review a mapping | [Build, review, and resume](docs/quick-start.md) |
| Embed transformations in a Python product | [Python SDK](docs/sdk.md) |
| Transform from another language or a workflow tool | [HTTP sidecar](docs/server.md), [TypeScript client](examples/typescript/README.md), or [JSONL workflows](docs/workflow-integration.md) |

## Add AI when evaluating mapping quality

Configure a supported model and its key in your process environment. Keys are not embedded in bundles or drafts. The host application can instead inject its own inference transport.

| Selection | Credential variable |
| --- | --- |
| `openai:<model-id>` | `OPENAI_API_KEY` |
| `anthropic:<model-id>` | `ANTHROPIC_API_KEY` |
| `google:<model-id>` | `GOOGLE_API_KEY` |

For example, after configuring `OPENAI_API_KEY`:

```text
open-mapping build example/source.json example/target.json --samples example/samples.jsonl --model openai:<model-id> --require-model --mapping-id customer --work-dir work/customer --out customer.omc --report-format json
```

A ready result contains the bundle path. A review-required result exits with code `8` and identifies the saved draft and decision file. Review the **original** proposal rather than running inference again:

```text
open-mapping review-draft work/customer/draft.json --interactive --out approved.review.yaml
open-mapping resume work/customer/draft.json --review approved.review.yaml --out customer.omc --report-format json
```

Resumption preserves the original suggestions, contracts, samples, and verification limits and makes zero model calls. The original input files and provider credentials are not required. Changing a contract requires a new build and review.

`--offline` explicitly disables model calls, including `OPEN_MAPPING_MODEL`. Explicit model selection otherwise overrides the environment. `--require-model` fails when no model is selected or inference fails. `--model-concurrency` is opt-in, bounded from `1` to `8`, and defaults to sequential execution.

Raw samples are excluded from provider context unless explicitly allowed. **Saved drafts contain the samples used for verification**, so apply your application's normal access controls and retention policy to them. The offline example demonstrates installation and execution, not general AI mapping accuracy.

## Embed the reusable runtime

After running the demo:

```python
from open_mapping import Mapper

mapper = Mapper.load("example/mapping.omc")
print(mapper.transform({"customer_id": "C-200", "name": "Grace"}))

for result in mapper.iter_results([
    {"customer_id": "C-201", "name": "Ada"},
    {"customer_id": 3, "name": "Invalid identifier"},
]):
    print(result.index, result.success, result.output, result.issues)
```

`iter_results` continues after per-record mapping errors. Existing `transform_many` and `iter_transform` retain fail-fast behavior. Source validation, target validation, invariants, and resource limits remain enabled.

Inspect changes before replacing an approved integration:

```text
open-mapping impact example/mapping.omc example/source.json example/target.json
```

The report identifies removed source paths, new required targets, affected rules, and static failures. It does not rewrite a bundle, automatically migrate it, or carry approvals to changed contracts.

## Understand the guarantees

**Structurally valid** means the mapping passed static checks. **Sample-verified** additionally means the supplied samples passed execution checks. Neither proves correct business meaning; billing and shipping fields can have identical types. A schema inferred from a few records is an observation, not an authoritative statement of future optionality.

Python `Mapper`, the CLI, and the HTTP sidecar enforce runtime source/target schemas and invariants. Generated TypeScript currently provides the expression evaluator and resource limits, **not equivalent runtime schema and invariant validation**. Use the sidecar client when those guarantees are required. See [bundle compatibility and conformance](docs/bundles.md).

## Evaluation and performance

The published Luna Max run achieved **100% on synthetic benchmark v1**: 105 target outcomes across seven small industry-shaped cases, including 63 direct mappings, seven ambiguities, and 35 no-match targets. The deterministic baseline scored 45.7% on that same corpus. These results are not a production-accuracy estimate, and a corpus used during development is no longer an untouched holdout. See the [original corpus and methodology](benchmarks/blind-multi-industry-v1/README.md).

Measure your own contracts with the benchmark tooling. `tools/benchmark_adoption.py` measures candidate generation and execution kernels separately, without provider calls or timing-based CI gates. Prepared rules, pointer tokens, private output construction, and cached field features remove repeated work without disabling validation.

[Apache License 2.0](LICENSE).
