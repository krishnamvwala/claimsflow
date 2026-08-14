---
adr_id: ADR-004
title: Python ingestion and validation boundary
status: accepted
decision_date: "2026-08-13"
owners:
  - ClaimsFlow Data Engineering
  - ClaimsFlow Data Quality
requirements: [FR-ING-001, FR-ING-002, FR-ING-003, FR-ING-004, FR-ING-005, FR-ING-006, FR-ING-007, FR-ING-008, FR-DQ-001, FR-DQ-002, FR-DQ-003, FR-DQ-004, FR-DQ-005, FR-DQ-006, FR-DQ-007, FR-DQ-008, FR-DQ-009, FR-DQ-010]
acceptance_criteria: [AC-ING-001, AC-ING-002, AC-ING-003, AC-ING-004, AC-ING-005, AC-ING-006, AC-ING-007, AC-ING-008, AC-DQ-001, AC-DQ-002, AC-DQ-003, AC-DQ-004, AC-DQ-005, AC-DQ-006, AC-DQ-007, AC-DQ-008, AC-DQ-009, AC-DQ-010]
supersedes: []
---

# ADR-004: Python ingestion and validation boundary

## Context

ClaimsFlow's source files have different schemas, identifiers, schedules, and row-level failure modes. File bytes and source-row positions must remain traceable, malformed or ambiguous records must be isolated, and identical delivery must not duplicate trusted amounts. At the same time, Python must not become an ungoverned second analytics engine.

## Decision

Use a small typed Python package and command-line interface for delivery registration, synthetic-provenance verification, streaming file inspection, source-contract validation, raw loading, row classification, and audit emission. Keep business transformation, governed metrics, and priority logic in dbt SQL.

## Decision details

- Organize the package by ports and adapters: contract loader, manifest/provenance verifier, delimited-file reader, Cloud Storage adapter, BigQuery adapter, validation engine, audit writer, and CLI entry points. Core classification functions remain deterministic and infrastructure-independent.
- The source-side `claimsflow ingest` command first validates an approved generator/fixture manifest, reserved synthetic identifiers, contract family, and whole-file SHA-256 before any upload. Unapproved input is never transmitted to a ClaimsFlow-managed bucket. The verified delivery is then uploaded and registered with source family/system, URI, object generation, file name, size, checksum, delivery timestamp, contract ID/version, provenance, and proposed batch ID.
- After upload, the cloud-side ingestion task rechecks object generation and checksum against the pre-ingress registration before parsing or raw loading. A mismatch blocks the batch and preserves only control-plane evidence.
- The duplicate-delivery decision uses source identity plus checksum and is persisted. An exact duplicate becomes a no-op with audit evidence; a reused name with changed content becomes a new batch or a blocking anomaly according to the source contract.
- Files are streamed in bounded chunks. Each raw row receives batch ID, source file, checksum, source row number or source record ID, contract version, ingestion time, raw payload hash, and processing status.
- The validator executes the machine-readable source rules and emits one result per evaluated rule/record. Results include stable rule ID, severity, disposition, affected field, original evidence, normalized value when permitted, plain-language reason, and UTC processing time.
- Only documented safe formatting rules may normalize values. Original and normalized values are both retained. Ambiguous identity, money, code, date, mapping, or deadline problems are quarantined or rejected; they are never guessed.
- Batch reconciliation proves `accepted + warned + quarantined + rejected = raw`, checks stable keys/hashes, and applies source-specific financial controls. Critical outcomes return a nonzero status to Airflow and block trusted publication.
- The CLI accepts explicit environment, source contract, manifest, batch, and bounded replay inputs. Configuration is validated at startup. Structured logs use identifiers and counts, not payload values.
- Dependencies are constrained and locked. Unit tests use generated fixtures and fakes; integration tests use isolated datasets. Type checking, linting, formatting, contract tests, and failure-path tests run in CI.

## Alternatives considered

### Use pandas dataframes for every file and transform

Rejected as the default because whole-file memory use conflicts with the scale boundary and dataframe business logic would overlap dbt. Small dataframes may be used only in tests or explicitly bounded utilities.

### Validate only after raw data reaches dbt

Rejected because file integrity, byte-level parsing, source-row evidence, encoding, duplicate delivery, and pre-storage synthetic provenance belong at the ingestion boundary.

### Silently coerce any invalid value to null

Rejected because it destroys evidence, can change financial meaning, and violates the explicit warning/quarantine/rejection policy.

## Consequences

### Positive

- Source evidence and validation decisions are deterministic and testable before trusted transformation.
- Streaming reads avoid requiring a developer workstation to hold the complete monthly dataset.
- A narrow boundary prevents Python/dbt logic drift.
- Ports and adapters allow unit tests without live cloud resources.

### Trade-offs

- Row-level Python validation may be slower than set-based SQL for some rules; batch-level and relational checks may therefore execute in BigQuery through the adapter.
- The package needs explicit error taxonomy, schemas, and dependency maintenance.
- Exactly-once business outcomes still require downstream merge keys and reconciliation, not only file deduplication.

## Security and privacy

The source-side provenance gate rejects unapproved input before ClaimsFlow-managed storage or processing, and the cloud-side gate re-verifies the uploaded object before raw loading. Safe non-sensitive canaries test both rejection paths. Logs contain hashes and identifiers but no raw row payloads. Local configuration uses environment variables or application-default credentials; CI uses federation; committed service-account keys and secrets are prohibited.

## Reliability and recovery

Registration and load writes are keyed by batch/file/row identity. A task may resume only after comparing durable audit state with its intended write set. Raw rows are append-only; corrected records point to prior evidence. Replay produces the same classification for the same bytes, contract version, and rules, then proves no duplicate or lost trusted keys or financial amounts.

## Validation evidence

- Unit and property tests for parsing, hashing, classification, normalization, and duplicate decisions.
- Contract fixtures for valid, late, duplicate, malformed, missing, boundary, and ambiguous records.
- Full batch disposition and financial reconciliation.
- Source-side ingress test that rejects a safe unapproved canary before upload, plus a cloud-side checksum-mismatch test that blocks raw loading.
- Replay comparison over business keys, row hashes, counts, and amounts.

## Revisit triggers

- A required source cannot be processed within the bounded batch performance target.
- A streaming/event ingestion requirement is approved.
- Validation volume makes the hybrid Python/BigQuery approach miss the service objective.
- A file format requires a dedicated managed ingestion service.
- Real regulated data is proposed.

## References

- [Google Cloud Storage Python client documentation](https://cloud.google.com/python/docs/reference/storage/latest)
- [Google Cloud BigQuery Python client documentation](https://cloud.google.com/python/docs/reference/bigquery/latest)
- [Python logging documentation](https://docs.python.org/3/library/logging.html)
