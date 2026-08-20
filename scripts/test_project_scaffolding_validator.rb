#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "open3"
require "rbconfig"
require "tmpdir"

SOURCE_ROOT = File.expand_path("..", __dir__)
COPY_ENTRIES = %w[
  .dockerignore
  .env.example
  .github
  .gitignore
  .python-version
  Makefile
  README.md
  analytics
  compose.yaml
  config
  contracts
  docs
  infra
  orchestration
  pyproject.toml
  scripts
  src
  tests
  uv.lock
].freeze

def run_validator(root)
  Open3.capture3(RbConfig.ruby, File.join(root, "scripts", "validate_project_scaffolding.rb"))
end

def with_repository_copy
  Dir.mktmpdir("claimsflow-scaffold-validator-") do |root|
    COPY_ENTRIES.each do |entry|
      source = File.join(SOURCE_ROOT, entry)
      FileUtils.cp_r(source, root) if File.exist?(source)
    end
    yield root
  end
end

def mutate(root, relative_path)
  path = File.join(root, relative_path)
  File.write(path, yield(File.read(path)))
end

def assert_failure(label, expected)
  with_repository_copy do |root|
    yield root
    stdout, stderr, status = run_validator(root)
    output = stdout + stderr
    if status.success?
      warn "FAIL #{label}: validator unexpectedly passed"
      return false
    end
    unless output.include?(expected)
      warn "FAIL #{label}: expected #{expected.inspect}, got:\n#{output}"
      return false
    end
    puts "PASS #{label}"
    true
  end
end

stdout, stderr, status = run_validator(SOURCE_ROOT)
unless status.success?
  warn "FAIL baseline scaffold validator:\n#{stdout}#{stderr}"
  exit 1
end
puts "PASS baseline project scaffold"

results = []

results << assert_failure("missing lock", "Missing required scaffold file: uv.lock") do |root|
  FileUtils.rm(File.join(root, "uv.lock"))
end

results << assert_failure("wrong Python version", ".python-version must pin Python 3.12") do |root|
  File.write(File.join(root, ".python-version"), "3.13\n")
end

results << assert_failure("unlocked dependency", "dependency entries must use exact pins") do |root|
  mutate(root, "pyproject.toml") { |text| text.sub('"pytest==9.1.1"', '"pytest>=9.1.1"') }
end

results << assert_failure("real-data flag", ".env.example must contain") do |root|
  mutate(root, ".env.example") do |text|
    text.sub("CLAIMSFLOW_SYNTHETIC_ONLY=true", "CLAIMSFLOW_SYNTHETIC_ONLY=false")
  end
end

results << assert_failure("real-data quality policy", "must remain synthetic_only=true") do |root|
  mutate(root, "config/data-quality-policy.yml") do |text|
    text.sub("synthetic_only: true", "synthetic_only: false")
  end
end

results << assert_failure("blocking freshness policy", "non-blocking governed warning") do |root|
  mutate(root, "config/data-quality-policy.yml") do |text|
    text.sub("disposition: accepted_with_warning", "disposition: block_batch")
  end
end

results << assert_failure("missing hourly quality window", "governed hourly evaluation interval") do |root|
  mutate(root, "config/data-quality-policy.yml") do |text|
    text.sub("evaluation_interval: PT1H\n", "")
  end
end

results << assert_failure("missing quality batch gate", "fail-closed batch rule inventory") do |root|
  mutate(root, "config/data-quality-policy.yml") do |text|
    text.sub(/  critical_outcome:\n(?:    .*\n){4}/, "")
  end
end

results << assert_failure("unsafe logger field", "structured logger must not contain") do |root|
  mutate(root, "src/claimsflow/logging_config.py") do |text|
    text.sub('"code_version",', "\"claim_payload\",\n            \"code_version\",")
  end
end

results << assert_failure("mutable cloud landing upload", "create-only Cloud Storage uploads") do |root|
  mutate(root, "src/claimsflow/adapters/README.md") do |text|
    text.sub("`if_generation_match=0`", "an ordinary upload request")
  end
end

results << assert_failure("implicit cloud writes", "no implicit cloud writes") do |root|
  mutate(root, "src/claimsflow/adapters/README.md") do |text|
    text.sub(
      "imports, unit tests, and local ingestion perform no cloud write",
      "imports and local workflows may write to cloud services"
    )
  end
end

results << assert_failure("missing dbt layer", "dbt_project.yml must contain") do |root|
  mutate(root, "analytics/dbt/dbt_project.yml") do |text|
    text.sub("    semantic:\n", "    reporting:\n")
  end
end

results << assert_failure("missing dbt layer schema", "dbt_project.yml must contain") do |root|
  mutate(root, "analytics/dbt/dbt_project.yml") do |text|
    text.sub("      +schema: intermediate\n", "")
  end
end

results << assert_failure("dbt physical schema drift", "dbt dev/demo schema mapping must declare private staging physical dataset") do |root|
  mutate(root, "analytics/dbt/macros/generate_schema_name.sql") do |text|
    text.sub("'staging': 'claimsflow_curated'", "'staging': 'claimsflow_staging'")
  end
end

results << assert_failure("premature dbt model", "dbt Phase 1 publication boundary must prohibit SQL models") do |root|
  File.write(File.join(root, "analytics/dbt/models/curated/claim.sql"), "select 1 as claim_id\n")
end

results << assert_failure("dbt keyfile", "dbt profile must not contain") do |root|
  mutate(root, "config/dbt/profiles.yml") do |text|
    text.sub("      method: oauth", "      method: service-account\n      keyfile: secret.json")
  end
end

results << assert_failure("unpinned Airflow", "compose.yaml must contain") do |root|
  mutate(root, "compose.yaml") do |text|
    text.gsub(/apache\/airflow:3\.3\.1-python3\.12@sha256:[0-9a-f]{64}/, "apache/airflow:latest")
  end
end

results << assert_failure("missing publication task", "exactly the governed task IDs") do |root|
  mutate(root, "orchestration/airflow/dags/claimsflow_batch.py") do |text|
    text.gsub('task_id="advance_publication"', 'task_id="publish_unknown"')
  end
end

results << assert_failure("publication retry", "zero-retry publication policy") do |root|
  mutate(root, "orchestration/airflow/dags/claimsflow_batch.py") do |text|
    text.sub("        retries=0,", "        retries=2,")
  end
end


results << assert_failure("rewired publication chain", "exact fail-closed dependency chain") do |root|
  mutate(root, "orchestration/airflow/dags/claimsflow_batch.py") do |text|
    text.sub("        >> evaluate_publication_gates\n", "")
  end
end

results << assert_failure("fail-open Airflow trigger", "fail-closed trigger rule") do |root|
  mutate(root, "orchestration/airflow/dags/claimsflow_batch.py") do |text|
    text.sub('"trigger_rule": "all_success"', '"trigger_rule": "all_done"')
  end
end

results << assert_failure("unsafe local query cap", "Python configuration must contain") do |root|
  mutate(root, "src/claimsflow/config.py") do |text|
    text.sub('"local": 1_073_741_824', '"local": 10_737_418_240')
  end
end

results << assert_failure("destructive bucket", "non-destructive bucket") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("force_destroy               = false", "force_destroy               = true")
  end
end

results << assert_failure("short evidence retention", "400-day retention floor") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("retention_period = 34560000", "retention_period = 2592000")
  end
end

results << assert_failure("missing identity", "foundation workload identities must contain") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("    auditor        =", "    reviewer       =")
  end
end

results << assert_failure("missing BI query execution", "Terraform BigQuery job execution policy must contain") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub(', "bi"', "")
  end
end

results << assert_failure("missing orchestration audit access", "exact audit write access") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("    orchestration_audit = {", "    orchestration_metrics = {")
  end
end

results << assert_failure("optional budget", "budget must be mandatory") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("resource \"google_billing_budget\" \"dev_demo\" {", "resource \"google_billing_budget\" \"dev_demo\" {\n  count = 0")
  end
end

results << assert_failure("unbounded portfolio budget", "bounded budget validation") do |root|
  mutate(root, "infra/terraform/modules/foundation/variables.tf") do |text|
    text.sub("var.monthly_budget_usd <= 100", "var.monthly_budget_usd <= 100000")
  end
end

results << assert_failure("missing Billing Budget API", "Cloud Billing Budget API") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("    \"billingbudgets.googleapis.com\",\n", "")
  end
end

results << assert_failure("unrestricted federation", "branch-restricted federation") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub(" && assertion.ref == 'refs/heads/main'", "")
  end
end

results << assert_failure("unrestricted federation environment", "environment-restricted federation") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub(" && assertion.environment == '${var.github_environment}'", "")
  end
end

results << assert_failure("caller overrides invariant labels", "invariant labels must override caller labels") do |root|
  mutate(root, "infra/terraform/modules/foundation/main.tf") do |text|
    text.sub("    var.labels,\n    {", "    {\n").sub("    },\n  )", "    },\n    var.labels,\n  )")
  end
end

results << assert_failure("release version drift", "component versions must match") do |root|
  mutate(root, "config/release-manifest.example.json") do |text|
    text.sub('"airflow": "3.3.1"', '"airflow": "latest"')
  end
end

results << assert_failure("governed contract version drift", "contract_version must match every governed source contract") do |root|
  mutate(root, "contracts/source-data/claims.yml") do |text|
    text.sub("contract_version: 1.0.0", "contract_version: 2.0.0")
  end
end

results << assert_failure("missing release schema test", "Missing required scaffold file: tests/unit/test_release_manifest.py") do |root|
  FileUtils.rm(File.join(root, "tests/unit/test_release_manifest.py"))
end

results << assert_failure("CI path gap", "foundation workflow paths must contain") do |root|
  mutate(root, ".github/workflows/project-foundation.yml") do |text|
    text.gsub("      - \"src/**\"\n", "")
  end
end

results << assert_failure("CI dependency drift", "locked dependency installation") do |root|
  mutate(root, ".github/workflows/project-foundation.yml") do |text|
    text.sub("uv sync --locked --all-groups", "uv sync")
  end
end

results << assert_failure("mutable CI action", "must use immutable commit SHAs") do |root|
  mutate(root, ".github/workflows/project-foundation.yml") do |text|
    text.sub(
      "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
      "actions/checkout@v7.0.1"
    )
  end
end

results << assert_failure("Airflow database in Docker context", ".dockerignore must contain") do |root|
  mutate(root, ".dockerignore") do |text|
    text.sub("orchestration/airflow/db\n", "")
  end
end

results << assert_failure("Terraform variables in Docker context", ".dockerignore must contain") do |root|
  mutate(root, ".dockerignore") do |text|
    text.sub("**/*.auto.tfvars.json\n", "")
  end
end

results << assert_failure("Terraform variables tracked", ".gitignore Terraform variable policy must contain") do |root|
  mutate(root, ".gitignore") do |text|
    text.sub("*.auto.tfvars.json\n", "")
  end
end

results << assert_failure("private key material", "contains private key material") do |root|
  path = File.join(root, "src", "claimsflow", "bad_key.txt")
  File.write(path, "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n")
end

results << assert_failure("trailing whitespace", "has trailing whitespace") do |root|
  mutate(root, "docs/development/README.md") do |text|
    text.sub("# Local development", "# Local development ")
  end
end

results << assert_failure("quality identity-rule inventory drift", "131 source-identity/rule pairs") do |root|
  mutate(root, "docs/development/data-quality-quarantine.md") do |text|
    text.sub("131 source-identity/rule pairs", "130 source-identity/rule pairs")
  end
end

unless results.all?
  warn "Project scaffold validator tests failed."
  exit 1
end

puts "Project scaffold validator mutation tests passed (#{results.length} failure cases)."
