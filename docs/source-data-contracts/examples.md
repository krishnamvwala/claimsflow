# Source-Contract Examples

These examples demonstrate how the contracts connect. They are synthetic and illustrative; the YAML contracts remain authoritative.

## 1. Delivery manifest

```json
{
  "delivery_id": "95e7e180-b34d-4e70-946d-2cfb4031f522",
  "source_system": "synth_ehr_north",
  "contract_id": "SRC-CLM-001",
  "contract_version": "1.0.0",
  "dataset_name": "",
  "source_file_name": "synth_ehr_north_claims_20260813T140000Z_001.csv",
  "source_file_checksum_sha256": "8d3e9c50b5f91b64d3553a4f9bcf72e159977efe2286acc97f733a12a19b5c44",
  "source_extract_at": "2026-08-13T14:00:00Z",
  "delivered_at": "2026-08-13T14:04:00Z",
  "declared_record_count": 4167,
  "declared_control_totals": "{\"adjustment_amount\":\"860125.00\",\"billed_amount\":\"4521680.00\",\"outstanding_balance\":\"1834055.00\",\"paid_amount\":\"1827500.00\"}",
  "synthetic_generator_id": "claimsflow-synth",
  "synthetic_generator_version": "1.0.0",
  "synthetic_seed": 8132026,
  "sequence": 1
}
```

Before ingestion, ClaimsFlow verifies the approved generator, contract compatibility, file-name pattern, checksum, declared row count, and control-total keys. A repeated source/checksum pair is audited as a duplicate and is not republished.

## 2. Connected synthetic business scenario

| Contract | Example identity | Relationship demonstrated |
| --- | --- | --- |
| Reference data | Payer `PAY-SYN-014`, plan `PLAN-SYN-014-A`, provider `PRV-SYN-082`, facility `FAC-SYN-07` | Conformed identifiers are effective on the event dates |
| Eligibility | `ELG-SYN-90122` for patient `PAT-SYN-44091` | Plan belongs to payer and coverage spans the service date |
| Claim | `CLM-SYN-800120`, submission `1` | Patient, payer, plan, provider, and facility resolve |
| Claim line | `CLN-SYN-800120-01`, line `1` | Parent claim plus diagnosis and procedure references resolve |
| Remittance | `REM-SYN-5520` | Payer and payment control total resolve |
| Payment | `PMT-SYN-991102` | Payment connects the remittance to the claim and line |
| Denial | `DEN-SYN-8830` | Denial connects to the claim, payer, reason, exposure, and deadline |
| Appeal | `APL-SYN-2201` | Human-reviewed appeal connects to the denial and claim |

This chain is valid only when all event dates fall inside the applicable reference and coverage validity intervals and the financial rollups reconcile at `0.00` USD variance.

## 3. Validation outcome examples

| Input condition | Rule example | Required outcome |
| --- | --- | --- |
| Valid claim with all relationships and balanced amounts | No failed rule | `accepted` |
| Valid open denial within seven days of deadline | `DQ-DEN-009` | `accepted_with_warning` and deadline evidence |
| Claim references an unknown payer | `DQ-CLM-004` | `quarantined`; never infer a payer |
| Payment exceeds the eligible claim balance | `DQ-PAY-009` | `quarantined` pending verified correction |
| Claim file control total differs from parsed contents | `DQ-CMN-006` | `block_batch`; no dependent trusted publication |
| Delivery lacks approved synthetic provenance | `DQ-CMN-001` | Reject before project-managed storage or processing |

## 4. Safe correction example

A quarantined denial with an invalid reason code remains immutable in raw storage. A corrected synthetic redelivery receives a new batch and lineage envelope, links to the original evidence, and is published only after identity, code, deadline, financial, freshness, test, and reconciliation gates pass.
