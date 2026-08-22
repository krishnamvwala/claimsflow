# Singular tests

Phase 4A singular tests prove that the fourteen typed models exactly cover the validated
record allowlist, that their total rows reconcile to approved Phase 3 accepted plus warned
counts, that the exact canonical payload consumed by typed fields plus recomputed per-record
and complete record-set hashes match the immutable quality report, that every requested
validation has exactly one approved audit record, and that no
row escapes the configured candidate publication, selection fingerprint, or validation scope.
Model-local contract, not-null, accepted-value, and uniqueness tests remain beside their
owning staging models.

Phase 4B.1 tests govern dimension scope, history, reconciliation, relationships, and date
coverage. Phase 4B.2 tests govern fact scope, source row/amount reconciliation, parent and
effective-dimension relationships, exact date keys, ordered line-diagnosis conformance, and
financial integrity. Every Phase 4B.2 singular gate is tagged `curated_facts` and `phase4b2`
so the documented candidate selector cannot omit a release blocker.
