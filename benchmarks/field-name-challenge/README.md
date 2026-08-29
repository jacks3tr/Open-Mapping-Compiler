# Field-name challenge

This held-out benchmark gives Open Mapping Compiler exactly 20 source fields and 30 target fields. Eighteen target fields have type-compatible source matches under deliberately different names, including `part_no` to `materialMaster`. Twelve targets have no defensible source and should remain unmapped. No hints or raw sample values are sent to a model.

## Test with AI

Set the provider credential, then run the same compiler benchmark with a provider-neutral model selection:

```text
uv run open-mapping benchmark benchmarks/field-name-challenge --model openai:<model-id> --model-results-dir results/models
```

The report records model proposal validity, direct-match precision and recall, no-match abstention, completion, token usage, and latency. Replace `openai:` with `anthropic:` or `google:` as needed.

## Deterministic offline fallback

Run the deterministic mapper with no model or credentials:

```text
uv run open-mapping benchmark benchmarks/field-name-challenge --enforce-gates
```

The report separates precision from recall, so conservative abstention is not mistaken for accurate coverage. Review decisions are used only to verify that the ground-truth mapping compiles and runs across the interpreter, generated Python, and generated TypeScript.

The committed local result resolves all 18 differently named matches, abstains on all 12 unsupported targets, and records no direct-match false positive. This fixture is now a regression test rather than an untouched evaluation set; future quality claims need a new blind multi-domain corpus.
