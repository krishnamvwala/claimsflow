# Synthetic source generator

**Boundary:** SYNTHETIC DATA ONLY — NOT FOR PRODUCTION, CLINICAL, OR BILLING USE

The first Phase 2 vertical slice produces deterministic CSV deliveries for claims, claim
lines, eligibility, remittances, payments, denials, appeals, and the seven reference
datasets. It performs no upload and does not connect to a healthcare system or cloud
environment.

## Generate a delivery

The output path must not exist. This fail-closed rule prevents a rerun from replacing
previous evidence.

```bash
uv run --locked claimsflow generate \
  --service-month 2026-07 \
  --claims 1000 \
  --seed 20260815 \
  --output data/generated/demo-2026-07
```

The command supports 1 through 100,000 claims. The same service month, count, seed, and
generator version produce byte-identical CSV files and an identical manifest regardless of
when the command runs.

## Delivery contents

Each delivery contains:

- `manifest.json`, validated by `config/synthetic-delivery-manifest.schema.json`
- a `files/` directory with 14 contract-aligned CSV files
- all eight governed source families and all seven reference datasets
- a contract ID and version, source system, row count, and SHA-256 checksum for every file
- generated-to-written row-count reconciliation without claiming ingestion dispositions

Every fictional identifier uses a reserved `SYN-` prefix. Human names, addresses, birth
dates, medical narratives, credentials, and customer data are never generated. Descriptions
are explicitly labeled synthetic or non-clinical.

## Current boundary and next slice

This generator creates structurally contract-aligned records with deterministic relationship
and financial controls. It does not yet apply contract freshness rules, inject the invalid
scenario fixtures, upload files, register a batch, or classify data-quality outcomes. The
next Phase 2 slice will independently recompute hashes, reject unapproved manifests, register
batches idempotently, preserve row lineage, and reconcile ingestion dispositions.
