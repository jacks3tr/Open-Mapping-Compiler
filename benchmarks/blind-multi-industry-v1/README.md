# Blind Multi-Industry Corpus v1

This corpus measures first-pass field correspondence and safe abstention across seven unrelated industries. It contains 105 target decisions: 63 unambiguous direct mappings, 7 deliberately ambiguous targets, and 35 targets with no source counterpart. Every case has ten source fields, fifteen target fields, and three synthetic records.

The gold contracts were written and hash-locked before any model or matcher was scored. Matcher output, review files, and result reports are excluded from the gold lock. Do not change matcher code or vocabulary in response to this corpus and continue calling the current files blind; once inspected or used for tuning, they become a regression set. A future score requires a new version with newly researched cases.

## AI

Run the same provider-neutral model path used by the product:

```powershell
open-mapping benchmark benchmarks/blind-multi-industry-v1 --model <configured-alias> --model-results-dir results/blind-multi-industry-v1/model
```

The model receives schemas, types, constraints, descriptions, structural context, bounded candidate evidence, and no raw samples. Expected mappings, ambiguity labels, no-match labels, review decisions, and provenance commentary are not part of model context.

Luna Max completed all seven cases with the compiler's normal sanitized context and strict response contract:

| Measure | Result |
| --- | ---: |
| Direct mapping precision | 63/63 (100%) |
| Direct mapping recall | 63/63 (100%) |
| Ambiguities left for review | 7/7 (100%) |
| Missing source fields left unmapped | 35/35 (100%) |
| Target decisions returned | 105/105 (100%) |
| Static-valid direct proposals | 63/63 (100%) |
| Complete industry cases | 7/7 (100%) |

## Deterministic offline fallback

Run the deterministic baseline without a model:

```powershell
open-mapping benchmark benchmarks/blind-multi-industry-v1
```

The local score is evidence, not a release threshold. Execution gates validate the frozen reviewed truth; they do not require the untuned matcher to achieve a chosen precision or recall.

The first untuned local run selected 26 of 63 direct mappings (41.3% recall, 72.2% precision), correctly rejected 19 of 35 no-match targets (54.3% recall, 52.8% precision), and detected 3 of 7 ambiguous targets. The reviewed gold mapping executed all 105 outcomes without an execution-gate failure. These values are recorded in `results/blind-multi-industry-v1/baseline-summary.json`; they are a baseline to improve against, not a reason to rewrite this frozen corpus.

## Composition

| Industry | Case | Research anchor | Direct | Ambiguous | No match |
| --- | --- | --- | ---: | ---: | ---: |
| healthcare | `healthcare-observation` | HL7 FHIR R5 Observation | 9 | 1 | 5 |
| financial-services | `payments-credit-transfer` | ISO 20022 pacs.008 | 9 | 1 | 5 |
| retail-supply-chain | `supply-chain-event` | GS1 EPCIS 2.0 | 9 | 1 | 5 |
| software-observability | `observability-http` | OpenTelemetry Semantic Conventions 1.44 | 9 | 1 | 5 |
| geospatial | `geospatial-feature` | OGC API Features 1.0.1 | 9 | 1 | 5 |
| energy-utilities | `energy-interval` | Green Button ESPI | 9 | 1 | 5 |
| air-cargo | `air-cargo-shipment` | IATA ONE Record cargo ontology 3.3 | 9 | 1 | 5 |

The cases intentionally cover abbreviations, different naming styles, semantic near-neighbors, dates versus timestamps, identifiers, ISO-style codes, enums, booleans, integers, numbers, formats, patterns, and same-type distractors. Each ambiguous target represents a distinction that genuinely needs workflow context, such as FHIR effective versus issued time or EPCIS read point versus business location.

## Research anchors

- [HL7 FHIR R5 Observation](https://hl7.org/fhir/R5/observation-definitions.html)
- [ISO 20022 pacs.008 catalogue](https://www.iso20022.org/iso-20022-message-definitions?search=Pacs.008)
- [GS1 EPCIS 2.0](https://ref.gs1.org/standards/epcis/2.0.0/)
- [OpenTelemetry HTTP semantic conventions](https://opentelemetry.io/docs/specs/semconv/http/http-spans/)
- [OGC API Features 1.0.1](https://docs.ogc.org/is/17-069r4/17-069r4.html)
- [US Department of Energy Green Button](https://www.energy.gov/data/green-button)
- [IATA ONE Record cargo ontology](https://onerecord.iata.org/ns/cargo/index-en.html)

## Blindness and provenance

`corpus.lock.json` signs the manifests, source schemas, target schemas, samples, and expected mappings. `provenance.json` records the authoritative standard and concepts used for each case. All records and contracts are synthetic adaptations; they are not copied standard schemas or real operational data.
