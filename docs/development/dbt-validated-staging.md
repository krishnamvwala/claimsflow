# dbt validated staging

**Boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION, CLINICAL, OR BILLING USE

Phase 4A turns approved Phase 3 record envelopes into project-protected, typed,
source-conformed dbt views. It does not create facts, dimensions, metrics, priority scores, dashboards, or an
active publication. Landing, raw, quarantine, and rejected evidence cannot be dbt sources.

## Candidate isolation

Every invocation supplies:

- `claimsflow_publication_id`: a unique lowercase BigQuery-safe identifier, 3–48 characters.
- `claimsflow_validation_ids`: a non-empty allowlist of immutable Phase 3 validation IDs.

The publication ID and a deterministic fingerprint of the sorted validation allowlist become
part of every physical staging relation name. For example, model `stg_claims` under
publication `cfp_20260820_001` resolves to
`stg_claims__cfp_20260820_001__<selection-fingerprint>`. Reusing the publication ID with a
different input set therefore creates a different candidate instead of replacing the first
one. Failed or concurrent candidates remain isolated. The shared CI defaults are accepted
only for offline parsing; any non-CI run that does not replace the default publication ID
fails compilation.

The project-protected `stg_validated_records` model joins the allowlisted record envelopes to matching
quality-run evidence and requires all of the following:

- both rows are marked synthetic-only;
- the quality decision is `approved`;
- the Phase 3 publication gate is true;
- final disposition reconciliation is true;
- the record disposition is `accepted` or `accepted_with_warning`;
- validation and batch identifiers agree;
- dbt recomputes the SHA-256 of the exact canonical normalized-payload JSON string that its
  typed projections consume;
- every row's length-prefixed identity and payload-hash evidence recomputes to its Phase 3
  hash, including that normalized-payload checksum;
- the count and SHA-256 of the complete sorted record-evidence multiset match the immutable
  Phase 3 quality report.

## Required BigQuery source interface

`claimsflow_validated.records` contains immutable Phase 3 record envelopes. The loader
preserves the Phase 3 `validation_id`, `record_evidence_sha256`, nested `lineage`,
source/natural keys, evaluated payload hash, correction ID, disposition,
`normalized_payload_canonical_json`, `normalized_payload_sha256`, and synthetic marker. dbt
extracts every business field from that canonical string; it does not consume a separate,
unbound JSON object.

`claimsflow_audit.quality_runs` contains one immutable projection of the Phase 3 quality
report with its validation/batch IDs, decision and gate flags, reconciliation result, rule
version, report/configuration hashes, evaluation-window timestamp, and final disposition
counts. It also projects `validated_record_evidence_algorithm`,
`validated_record_set_algorithm`, `validated_record_count`, and
`validated_record_set_sha256` from the immutable report. The loader must verify the report
and `validated/records.jsonl` artifact hashes before appending either interface.

The relation names and datasets may be changed only through the documented environment
variables. Phase 4A defines and tests this interface but does not perform a live cloud load.

## Typed model inventory

- Operational sources: `stg_eligibility`, `stg_claims`, `stg_claim_lines`,
  `stg_remittances`, `stg_payments`, `stg_denials`, and `stg_appeals`.
- Effective-dated references: `stg_reference_payers`, `stg_reference_plans`,
  `stg_reference_providers`, `stg_reference_facilities`, `stg_reference_diagnoses`,
  `stg_reference_procedures`, and `stg_reference_denial_reasons`.

Every model retains candidate, candidate-selection, validation, batch, source-file, contract,
row, evaluated-payload, normalized-payload, record-evidence, record-set, correction,
disposition, quality-report, and
quality-configuration lineage. String lists are converted from the governed pipe-delimited
representation to ordered BigQuery string arrays.
All other source types use explicit casts defined by the source contracts.

## Commands

Offline validation requires no Google credentials:

```bash
make dbt-parse
```

A future explicitly approved synthetic dev/demo build uses a unique candidate and exact
validation allowlist:

```bash
uv run --locked --group dbt dbt build \
  --project-dir analytics/dbt \
  --profiles-dir config/dbt \
  --target dev_demo \
  --select tag:validated_staging \
  --vars '{"claimsflow_publication_id":"cfp_20260820_001","claimsflow_validation_ids":["quality-example"]}'
```

Do not run that command until the validated/audit interfaces exist in an isolated synthetic
GCP project and the live execution is explicitly approved.

## Tests and generated contracts

`scripts/render_dbt_staging_properties.py` deterministically projects the source YAML fields,
types, nullability, descriptions, grains, and contract IDs into dbt model contracts. CI runs
the generator in `--check` mode so manual drift fails closed.

dbt tests prove:

- every typed model has a non-null, unique validated-record identity;
- non-nullable source fields remain non-null after casting;
- only the configured source identity and publishable dispositions are present;
- the fourteen typed models exactly cover the validated boundary;
- staged counts equal approved Phase 3 accepted plus warned counts;
- every canonical normalized payload matches its Phase 3 checksum and the complete staged
  record set matches the Phase 3 record-evidence count and SHA-256;
- every requested validation ID resolves to exactly one approved quality-run record;
- every row remains inside the configured candidate and validation allowlist.

## Next milestone

Phase 4B.1 now builds publication-isolated curated dimensions, and Phase 4B.2 adds curated
facts with governed parent, dimension, date, and financial relationships. Candidate membership
deltas and active-manifest advancement follow in Phase 4B.3.
It must preserve this boundary and cannot advance an active publication until its own grain,
relationship, history, and reconciliation tests pass.
