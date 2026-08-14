# Benchmark account-segments

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 1 | 0 | 0 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 82 | 82 |
| direct_match_precision | 1 | 2 | 2 |
| direct_match_recall | 0.666666666667 | 2 | 3 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 1 | 0 | 0 |
| expected_no_match_detection | 1 | 0 | 0 |
| high_confidence_false_positive_rate | 0 | 0 | 2 |
| high_confidence_precision | 1 | 2 | 2 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 240 | 240 |
| low_confidence_precision | 0 | 0 | 0 |
| medium_confidence_precision | 0 | 0 | 0 |
| no_match_precision | 0 | 0 | 3 |
| no_match_recall | 1 | 0 | 0 |
| required_target_coverage | 1 | 5 | 5 |
| review_application_correctness | 1 | 0 | 0 |
| target_outcome_coverage | 1 | 5 | 5 |
| target_schema_pass_rate | 1 | 240 | 240 |
| transformation_exact_match_rate | 1 | 2 | 2 |

## Gates

| Metric | Value | Minimum | Maximum | Passed |
| --- | ---: | ---: | ---: | --- |
| cross_runtime_equivalence | 1 | 1.0 |  | true |
| duplicate_target_rejection | 1 | 1.0 |  | true |
| expected_ambiguity_detection | 1 | 1.0 |  | true |
| expected_no_match_detection | 1 | 1.0 |  | true |
| high_confidence_false_positive_rate | 0 |  | 0.02 | true |
| high_confidence_precision | 1 | 0.9 |  | true |
| invalid_source_path_rejection | 1 | 1.0 |  | true |
| review_application_correctness | 1 | 1.0 |  | true |
| target_outcome_coverage | 1 | 1.0 |  | true |

## Outcome counts

- Baseline confidence: `{"high": 2, "low": 0, "medium": 0, "none": 3}`
- Baseline disposition: `{"ambiguous": 0, "manual": 0, "no_match": 3, "review_required": 0, "suggested": 2}`
- Assisted confidence: `{"high": 0, "low": 0, "medium": 0, "none": 5}`
- Assisted disposition: `{"ambiguous": 0, "manual": 5, "no_match": 0, "review_required": 0, "suggested": 0}`

## Failures and warnings

- account-segments-missing-segment / interpreter: SOURCE_SCHEMA_VALIDATION: source sample violates required-property constraint at /segments/segment10
- account-segments-missing-segment / python: SOURCE_SCHEMA_VALIDATION: SOURCE_SCHEMA_VALIDATION
- account-segments-missing-segment / typescript: SOURCE_SCHEMA_VALIDATION: SOURCE_SCHEMA_VALIDATION
- account-segments-malformed-length / interpreter: SOURCE_SCHEMA_VALIDATION: source sample string violates a length constraint at /segments/segment01
- account-segments-malformed-length / python: SOURCE_SCHEMA_VALIDATION: SOURCE_SCHEMA_VALIDATION
- account-segments-malformed-length / typescript: SOURCE_SCHEMA_VALIDATION: SOURCE_SCHEMA_VALIDATION
- warning: INVALID_INPUT: metric 'low_confidence_precision' has no observed cases
- warning: INVALID_INPUT: metric 'medium_confidence_precision' has no observed cases
