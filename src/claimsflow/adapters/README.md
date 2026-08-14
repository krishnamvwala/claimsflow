# Adapter boundary

This directory will hold Cloud Storage, BigQuery, file-reader, and audit adapters. No external writes are implemented in Phase 1. Adapters must implement interfaces from `claimsflow.ports`, preserve the synthetic-only boundary, and keep metric or transformation logic in dbt.
