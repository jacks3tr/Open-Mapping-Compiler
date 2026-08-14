# Security policy

## Supported versions

The current `0.1.x` release line receives security fixes. Older snapshots are unsupported; reproduce reports against the newest available `0.1.x` release when possible.

## Private reporting

Use GitHub's private vulnerability reporting for this repository. Open the Security tab, select "Report a vulnerability," and do not open a public issue. Include the affected version, operating system and Python version, a minimal synthetic reproducer, the observed impact, and any suggested mitigation. Remove credentials, customer data, provider transcripts, and other personal or proprietary information.

You should receive an acknowledgement within seven days. The maintainer will validate the report, coordinate a fix and disclosure timeline, and credit the reporter if requested. Please allow time for a patched release before public disclosure.

## Trust model

Schemas, mappings, hints, suggestion reports, review documents, benchmark manifests, samples, CLI paths, generated-code inputs, and provider responses are untrusted. Open Mapping Compiler never treats strings from those inputs as Python, JavaScript, shell, SQL, or template source.

Model mapping requests use the code-owned `mapping-agent-v1` instruction. The prompt builder serializes schema descriptions, samples, and business instructions as user payload data, separate from the instruction and response schema. The provider-neutral response contract has no fields for confidence, approval, review decisions, or verification claims.

The main safeguards are:

- safe YAML parsing rejects object-construction tags and duplicate keys;
- JSON rejects non-finite numbers, and numeric operations enforce JavaScript-safe integer semantics;
- remote and cyclic schema references are rejected;
- evaluation limits bound expression depth, array items, output nodes, and string length;
- typed provider responses are size-limited and cannot set confidence, review, or verification state;
- sample values stay local unless `--allow-raw-samples` is explicitly used with a provider;
- suggestion reports and reviews are hash-bound, coverage-checked, and duplicate-checked;
- generated source quotes mapping-controlled data and is verified before writing;
- output replacement is opt-in and atomic, with rollback on replacement failure.

These controls reduce risk but do not make an optional remote provider trustworthy. Review the provider's data-handling terms, use a dedicated least-privilege token environment variable, prefer HTTPS, and do not send data the provider is not authorized to process. Loopback HTTP is allowed for local development only.

## Model providers

Only an explicit `--model` selection can start a configured model call or incur a provider charge. Provider billing, retention, and regional processing rules are outside this project. Check those terms before selecting a model, and set any credential through the environment variable named in the configuration file.

Use `model-context` before a call when you need to inspect the sanitized context package. The package can include schema metadata, deterministic candidates, sample profiles, mapping hints, and optional instruction text. Raw sample values remain local unless `--allow-raw-samples` is passed. The model run report records bounded provenance, including configuration, context, and response hashes, without provider credentials or endpoint details.

Treat schema descriptions, sample values, hints, CLI instructions, and provider output as untrusted data. They can contain prompt-injection text. The compiler keeps them separate from its code-owned instruction and constrains model output to a typed response contract. Those boundaries reduce risk but do not make provider output safe to approve. Review every model draft and run deterministic verification before use.

## Safe operation

Run the compiler as an unprivileged user in a directory containing only intended inputs and outputs. Keep schemas and samples under normal source-control review. Treat generated programs as build artifacts and execute them in the same isolation used for other generated code. Keep dependencies locked, review dependency updates, and verify release archive provenance before installation.

Never place secrets or customer data in issues, benchmark packs, examples, test fixtures, command lines, logs, or committed output. If sensitive data may have been exposed, rotate the affected credential and follow the relevant incident-response process in addition to reporting the compiler issue.

## Out of scope

Reports that require intentionally disabling documented limits, modifying the installed package, or compromising an external provider without demonstrating an Open Mapping Compiler boundary failure are not vulnerabilities in this project. Denial of service that remains within the documented local resource bounds may still be reported if it has a practical security impact.
