# Source Validation and Disposition Policy

**Policy version:** 1.0.0

This policy is authoritative for all source contracts. Contract-specific rules may be stricter but may not weaken these controls.

## 1. Evaluation order

1. Verify synthetic provenance before project-managed storage or processing.
2. Register source identity, file name, checksum, extract time, contract, and batch ID.
3. Detect duplicate delivery.
4. Validate file envelope, header, and schema.
5. Preserve the immutable source-shaped row and lineage envelope.
6. Apply approved deterministic normalizations with before/after audit evidence.
7. Evaluate identity, required-field, format, date, code, relationship, financial, freshness, duplicate, and reconciliation rules.
8. Assign exactly one record disposition.
9. Block dependent publication when any required batch gate fails.

## 2. Severity and disposition map

| Severity | Permitted disposition | Meaning |
| --- | --- | --- |
| `warning` | `accepted_with_warning` | Record is safe to publish, but the condition remains visible in quality evidence |
| `error` | `quarantined` | Ambiguous or unsafe record is isolated pending verified correction or disposition |
| `critical` | `rejected` | Structurally or semantically unusable record is retained as evidence but cannot enter trusted data |
| `critical` | `block_batch` | File or reconciliation failure blocks all dependent trusted publication |

A record with no failed rule is `accepted`. If multiple rules fail, precedence is `rejected`, `quarantined`, `accepted_with_warning`, then `accepted`. A `block_batch` result is recorded separately from record disposition and prevents publication even if some records are otherwise acceptable.

## 3. Common file and lineage rules

| Rule ID | Condition | Severity | Disposition |
| --- | --- | --- | --- |
| DQ-CMN-001 | Delivery lacks approved synthetic-provenance evidence | critical | block_batch |
| DQ-CMN-002 | Contract ID/version is absent, unknown, or incompatible | critical | block_batch |
| DQ-CMN-003 | Header, column order, encoding, delimiter, or file-name pattern differs from the declared contract | critical | block_batch |
| DQ-CMN-004 | Source identity plus SHA-256 checksum matches a previously accepted delivery | warning | accepted_with_warning; do not republish and record duplicate decision |
| DQ-CMN-005 | File is empty when a delivery is expected | error | quarantine delivery and raise freshness/volume evidence |
| DQ-CMN-006 | Declared row count or financial control total differs from parsed source content | critical | block_batch |
| DQ-CMN-007 | `source_record_id`, `source_row_number`, payload hash, or required lineage value cannot be generated uniquely | critical | rejected |
| DQ-CMN-008 | Delivery arrives after the contract's `late_after` interval | warning | accepted_with_warning and emit freshness evidence |
| DQ-CMN-009 | Undeclared column is present | critical | block_batch until a compatible contract version is approved |
| DQ-CMN-010 | Required column is absent | critical | block_batch |

## 4. Permitted automatic normalizations

Only the following deterministic rules may run automatically. Every application records the rule ID, original value, normalized value, processing time, and contract version.

| Rule ID | Input | Output |
| --- | --- | --- |
| NORM-CMN-001 | Leading or trailing ASCII whitespace in a non-identifier text field | Trimmed text |
| NORM-CMN-002 | Allowed code or enum with alphabetic case differences | Uppercase canonical value |
| NORM-CMN-003 | Valid ISO 8601 timestamp containing a numeric UTC offset | Equivalent UTC timestamp ending in `Z` |
| NORM-CMN-004 | Boolean value `TRUE`, `FALSE`, `1`, or `0` | `true` or `false` according to the documented mapping |
| NORM-CMN-005 | Monetary value with fewer than two fractional digits | Exact two-decimal representation without changing value |

Identifiers are never case-folded, truncated, padded, guessed, or cross-walked automatically. Invalid dates, unknown codes, missing relationships, inconsistent financial values, and missing deadlines are ambiguous and must follow their declared quarantine or rejection rule.

## 5. Boundary and financial conventions

- `minimum` and `maximum` are inclusive unless the rule text explicitly says otherwise.
- Date order checks use calendar dates; duration checks use UTC instants.
- Currency is USD in version 1. Cross-currency records are rejected.
- Payment and adjustment files store a positive `amount` and use `direction` to determine the sign: `credit` increases payment/adjustment applied to the account; `debit` reverses it.
- `payer_payment`, `patient_payment`, `contractual_adjustment`, and `write_off` require `credit`; `refund` and `reversal` require `debit`.
- A payment cannot exceed the eligible billed or outstanding amount under the current source state unless its type is an explicitly linked refund/reversal.
- Claim and claim-line amount equations use the exact fields and tolerance declared in their contracts.
- Empty nullable monetary fields are not treated as zero unless a downstream governed metric explicitly defines that behavior.

## 6. Correction and republication

A quarantined record may be corrected only from a verified synthetic source redelivery or an audited reviewer disposition. The correction creates a new version linked to the original raw row, actor/source, time, reason, and outcome. Publication occurs only after the corrected version passes all required validation, test, freshness, and reconciliation gates.
