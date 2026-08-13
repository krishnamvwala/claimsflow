# Governed Metric Examples

All examples are synthetic. They demonstrate contract behavior; the YAML metric definitions remain authoritative.

## 1. Count-based claim rates

Assume a January original-submission cohort contains 10 claims with observed first responses:

- Nine were accepted into payer processing on the first pass; one was rejected.
- Of those nine, one was later denied and one required a replacement.
- Seven therefore meet the stricter clean-claim definition.

The governed results are:

| Metric | Components | Result |
| --- | --- | --- |
| First-pass acceptance rate | `9 / 10` | `90.00%` |
| Clean-claim rate | `7 / 10` | `70.00%` |

The later denial does not rewrite the first-pass response. It does prevent that claim from being clean. The replacement also removes its original from the clean numerator during the open restatement period.

For a separate adjudication cohort of 20 claim submissions, suppose 4 distinct complete claim-submission keys link to one or more trusted denials. Several denials are line-level and one claim has two denial events. The numerator remains 4 distinct claim submissions, so denial rate is `100 × 4 / 20 = 20.00%`.

## 2. Outstanding balance and days in A/R

At the end of August 13, the current claim-identity snapshot has eligible outstanding balances of `400.00`, `600.00`, and `8,000.00` USD. A fourth identity is currently voided and contributes nothing.

Outstanding balance is `400 + 600 + 8,000 = 9,000.00 USD`. Claim-line balances are not added again.

Eligible current claim identities originally submitted during the 90-date lookback carry `45,000.00 USD` in gross billed charges. Average daily gross charges are `45,000 / 90 = 500.00 USD`. Days in A/R is `9,000 / 500 = 18.0 days`.

A charge assigned to `as_of_date - 89 days` is included. A charge assigned to `as_of_date - 90 days` is excluded. If the eligible 90-day gross charges equal zero, days in A/R is null with `not_applicable` status, not zero days.

## 3. Net collection rate with a refund

A service-date cohort contains `10,000.00 USD` of gross billed charges. It has `2,000.00 USD` of contractual-adjustment credits and a `7,500.00 USD` mix of payer and patient payment credits. A linked `300.00 USD` refund debit reverses part of a payer payment.

- Net payments: `7,500 - 300 = 7,200.00 USD`
- Net collectible charges: `10,000 - 2,000 = 8,000.00 USD`
- Net collection rate: `100 × 7,200 / 8,000 = 90.00%`

A separate `250.00 USD` write-off does not reduce the denominator. An unlinked refund or reversal blocks the metric rather than being guessed into a bucket.

## 4. Appeals and recovered revenue

Four appeal events receive final outcomes in a reporting period: two overturned, one partially overturned, and one upheld. Appeal success rate is `100 × 3 / 4 = 75.00%`.

The three favorable appeal events have incremental recovered amounts of `1,500.00`, `1,250.00`, and `750.00 USD`. Recovered revenue is `3,500.00 USD`.

If a newer version corrects the third amount to `700.00 USD` inside the open restatement window, the result becomes `3,450.00 USD`; the old `750.00 USD` is replaced, not retained as another recovery. Total recovery for all appeal levels belonging to one denial may not exceed that denial's `denied_amount`.

## 5. Dimensional reconciliation

Suppose an unfiltered denial cohort has 4 denied claim submissions among 20 adjudicated submissions. Payer A components are `3 / 12`; Payer B components are `1 / 8`.

- Payer A denial rate: `25.00%`
- Payer B denial rate: `12.50%`
- Reconciled total components: `(3 + 1) / (12 + 8) = 20.00%`

Adding `25.00%` and `12.50%`, or taking their unweighted average, is invalid. Components reconcile before the governed rate is recomputed. A claim with several lines, diagnoses, or denial events is semi-joined and counted once at claim-submission grain.

## 6. Published metric evidence

Every material result retains evidence shaped like this:

```json
{
  "metric_id": "MET-DEN-001",
  "dictionary_version": "1.0.0",
  "period_start": "2026-07-01",
  "period_end": "2026-08-01",
  "calculation_cutoff_at": "2026-08-13T23:59:59Z",
  "filter_context": {"payer_id": "PAY-SYN-014"},
  "numerator": "3",
  "denominator": "12",
  "unrounded_value": "25.000000",
  "display_value": "25.00%",
  "status": "complete",
  "synthetic_only": true
}
```

Lineage from the result resolves to the metric definition version, semantic calculation, source batches, and complete source record keys. Every dependency row must satisfy `trusted_published_at <= calculation_cutoff_at`; a late-arriving historical business event appears only in later calculations or an audited restatement.
