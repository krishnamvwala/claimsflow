#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "open3"
require "rbconfig"
require "tmpdir"
require "yaml"

SOURCE_ROOT = File.expand_path("..", __dir__)

def run_validator(root)
  Open3.capture3(RbConfig.ruby, File.join(root, "scripts", "validate_architecture_decisions.rb"))
end

def with_repository_copy
  Dir.mktmpdir("claimsflow-architecture-validator-") do |temporary_root|
    %w[README.md docs scripts .github].each do |entry|
      FileUtils.cp_r(File.join(SOURCE_ROOT, entry), temporary_root)
    end
    yield temporary_root
  end
end

def rewrite_adr(root, file_name)
  path = File.join(root, "docs", "architecture", "adr", file_name)
  content = File.read(path)
  match = content.match(/\A---\s*\n(.*?)\n---\s*\n(.*)\z/m)
  raise "Unable to parse test ADR #{file_name}" unless match

  metadata = YAML.safe_load(match[1], aliases: false)
  body = match[2]
  metadata, body = yield metadata, body
  yaml_body = YAML.dump(metadata).sub(/\A---\s*\n/, "")
  File.write(path, "---\n#{yaml_body}---\n#{body}")
end

def mutate_document(root, relative_path)
  path = File.join(root, relative_path)
  File.write(path, yield(File.read(path)))
end

def assert_failure(label, expected_message)
  with_repository_copy do |root|
    yield root
    stdout, stderr, status = run_validator(root)
    output = stdout + stderr
    if status.success?
      warn "FAIL #{label}: validator unexpectedly passed"
      return false
    end
    unless output.include?(expected_message)
      warn "FAIL #{label}: expected #{expected_message.inspect}, got:\n#{output}"
      return false
    end
    puts "PASS #{label}"
    true
  end
end

def assert_success(label)
  with_repository_copy do |root|
    yield root
    stdout, stderr, status = run_validator(root)
    unless status.success?
      warn "FAIL #{label}: validator unexpectedly failed:\n#{stdout}#{stderr}"
      return false
    end
    puts "PASS #{label}"
    true
  end
end

def add_valid_adr_008_successor(root)
  source_name = "ADR-007-environments-ci-cd-observability-and-cost.md"
  target_name = "ADR-008-environment-baseline-refresh.md"
  source_path = File.join(root, "docs", "architecture", "adr", source_name)
  target_path = File.join(root, "docs", "architecture", "adr", target_name)

  content = File.read(source_path)
  match = content.match(/\A---\s*\n(.*?)\n---\s*\n(.*)\z/m)
  metadata = YAML.safe_load(match[1], aliases: false)
  body = match[2]

  metadata["adr_id"] = "ADR-008"
  metadata["title"] = "Environment baseline refresh"
  metadata["decision_date"] = "2026-08-14"
  metadata["supersedes"] = ["ADR-007"]
  body = body.sub(/^# ADR-007:.*$/, "# ADR-008: Environment baseline refresh")
  yaml_body = YAML.dump(metadata).sub(/\A---\s*\n/, "")
  File.write(target_path, "---\n#{yaml_body}---\n#{body}")

  rewrite_adr(root, source_name) do |old_metadata, old_body|
    old_metadata["status"] = "superseded"
    [old_metadata, old_body]
  end

  mutate_document(root, "docs/architecture/README.md") do |text|
    old_row = "| [ADR-007](adr/#{source_name}) | Accepted | Environments, Terraform, CI/CD, observability, rollback, and cost governance |"
    replacement = "| [ADR-007](adr/#{source_name}) | Superseded | Environments, Terraform, CI/CD, observability, rollback, and cost governance |\n" \
                  "| [ADR-008](adr/#{target_name}) | Accepted | Environment baseline refresh |"
    text.sub(old_row, replacement)
  end
end

baseline_stdout, baseline_stderr, baseline_status = run_validator(SOURCE_ROOT)
unless baseline_status.success?
  warn "FAIL baseline validator:\n#{baseline_stdout}#{baseline_stderr}"
  exit 1
end
puts "PASS baseline architecture decisions"

results = []

results << assert_failure("missing baseline ADR", "Missing baseline ADR files") do |root|
  FileUtils.rm(File.join(root, "docs", "architecture", "adr", "ADR-007-environments-ci-cd-observability-and-cost.md"))
end

results << assert_failure("duplicate ADR ID", "Duplicate ADR ID ADR-001") do |root|
  rewrite_adr(root, "ADR-002-dbt-transformation-and-semantic-layer.md") do |metadata, body|
    metadata["adr_id"] = "ADR-001"
    [metadata, body]
  end
end

results << assert_failure("unsupported status", "status must be accepted or superseded") do |root|
  rewrite_adr(root, "ADR-003-airflow-orchestration-and-replay.md") do |metadata, body|
    metadata["status"] = "proposed"
    [metadata, body]
  end
end

results << assert_failure("invalid decision date", "decision_date must be an ISO-8601 date string") do |root|
  rewrite_adr(root, "ADR-004-python-ingestion-and-validation-boundary.md") do |metadata, body|
    metadata["decision_date"] = "not-a-date"
    [metadata, body]
  end
end

results << assert_failure("blank accountable owner", "owners must be a non-empty unique list of strings") do |root|
  rewrite_adr(root, "ADR-005-power-bi-connectivity-and-governed-reporting.md") do |metadata, body|
    metadata["owners"][1] = " "
    [metadata, body]
  end
end

results << assert_failure("incorrect acceptance mapping", "acceptance_criteria must exactly follow requirement mappings") do |root|
  rewrite_adr(root, "ADR-006-security-privacy-and-access-control.md") do |metadata, body|
    metadata["acceptance_criteria"].pop
    [metadata, body]
  end
end

results << assert_failure("unknown requirement", "references unknown requirement FR-FAKE-999") do |root|
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata["requirements"][0] = "FR-FAKE-999"
    metadata["acceptance_criteria"][0] = "AC-FAKE-999"
    [metadata, body]
  end
end

results << assert_failure("duplicate requirement ownership", "Requirement FR-BI-001 is assigned to active ADRs ADR-001 and ADR-005") do |root|
  rewrite_adr(root, "ADR-001-bigquery-data-layers.md") do |metadata, body|
    metadata["requirements"] << "FR-BI-001"
    metadata["acceptance_criteria"] << "AC-BI-001"
    [metadata, body]
  end
end

results << assert_failure("baseline ownership reassignment", "requirements must match the approved ADR-001 baseline assignment") do |root|
  rewrite_adr(root, "ADR-001-bigquery-data-layers.md") do |metadata, body|
    metadata["requirements"] << "FR-WH-004"
    metadata["acceptance_criteria"] << "AC-WH-004"
    [metadata, body]
  end
  rewrite_adr(root, "ADR-002-dbt-transformation-and-semantic-layer.md") do |metadata, body|
    metadata["requirements"].delete("FR-WH-004")
    metadata["acceptance_criteria"].delete("AC-WH-004")
    [metadata, body]
  end
end

results << assert_failure("missing baseline coverage", "Architecture ADRs missing baseline requirement coverage: FR-BI-004") do |root|
  rewrite_adr(root, "ADR-005-power-bi-connectivity-and-governed-reporting.md") do |metadata, body|
    metadata["requirements"].delete("FR-BI-004")
    metadata["acceptance_criteria"].delete("AC-BI-004")
    [metadata, body]
  end
end

results << assert_failure("missing required section", "must contain exactly one ## Reliability and recovery heading") do |root|
  rewrite_adr(root, "ADR-003-airflow-orchestration-and-replay.md") do |metadata, body|
    [metadata, body.sub("## Reliability and recovery", "## Recovery notes")]
  end
end

results << assert_failure("insufficient alternatives", "must document at least two alternatives") do |root|
  rewrite_adr(root, "ADR-002-dbt-transformation-and-semantic-layer.md") do |metadata, body|
    changed = body.sub("### Define metrics and priority logic in Power BI", "Define metrics and priority logic in Power BI")
    changed = changed.sub("### Start with a machine-learning recovery score", "Start with a machine-learning recovery score")
    [metadata, changed]
  end
end

results << assert_failure("unofficial reference", "reference must use an approved official host") do |root|
  rewrite_adr(root, "ADR-001-bigquery-data-layers.md") do |metadata, body|
    [metadata, body.sub("cloud.google.com/bigquery/docs/partitioned-tables", "example.com/partitioned-tables")]
  end
end

results << assert_failure("broken internal link", "has broken internal link adr/missing.md") do |root|
  mutate_document(root, "docs/architecture/README.md") do |text|
    text.sub("adr/ADR-001-bigquery-data-layers.md", "adr/missing.md")
  end
end

results << assert_failure("missing ADR registry link", "Architecture registry must contain exactly one row for ADR-006") do |root|
  mutate_document(root, "docs/architecture/README.md") do |text|
    text.sub("[ADR-006](adr/ADR-006-security-privacy-and-access-control.md)", "ADR-006")
  end
end

results << assert_failure("stale ADR registry status", "Architecture registry ADR-007 status must be Superseded") do |root|
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata["status"] = "superseded"
    [metadata, body]
  end
end

results << assert_failure("mismatched ADR registry title", "Architecture registry ADR-002 title must match ADR metadata") do |root|
  mutate_document(root, "docs/architecture/README.md") do |text|
    text.sub("dbt transformation, metric, history, and priority-engine ownership", "dbt architecture")
  end
end

results << assert_failure("missing technology boundary", "must document architecture boundary keyword \"Import mode\"") do |root|
  rewrite_adr(root, "ADR-005-power-bi-connectivity-and-governed-reporting.md") do |metadata, body|
    [metadata, body.gsub("Import mode", "cached storage mode")]
  end
end

results << assert_failure("missing supersedes metadata", "missing front matter keys: supersedes") do |root|
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata.delete("supersedes")
    [metadata, body]
  end
end

results << assert_failure("unknown supersedes target", "supersedes unknown ADR ADR-999") do |root|
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata["supersedes"] = ["ADR-999"]
    [metadata, body]
  end
end

results << assert_failure("supersedes newer decision", "may supersede only an older ADR") do |root|
  rewrite_adr(root, "ADR-001-bigquery-data-layers.md") do |metadata, body|
    metadata["supersedes"] = ["ADR-007"]
    [metadata, body]
  end
end

results << assert_failure("orphaned superseded decision", "is superseded but does not have exactly one successor") do |root|
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata["status"] = "superseded"
    [metadata, body]
  end
end

results << assert_failure("accepted target of successor", "must have status superseded when targeted by ADR-008") do |root|
  add_valid_adr_008_successor(root)
  rewrite_adr(root, "ADR-007-environments-ci-cd-observability-and-cost.md") do |metadata, body|
    metadata["status"] = "accepted"
    [metadata, body]
  end
end

results << assert_failure("trailing whitespace", "has trailing whitespace") do |root|
  rewrite_adr(root, "ADR-001-bigquery-data-layers.md") do |metadata, body|
    [metadata, body.sub("## Context\n", "## Context \n")]
  end
end

results << assert_failure("missing root architecture link", "Root README must link docs/architecture/README.md") do |root|
  mutate_document(root, "README.md") do |text|
    text.sub("docs/architecture/README.md", "docs/architecture-overview.md")
  end
end

results << assert_failure("incomplete workflow paths", "Architecture workflow must watch docs/architecture/**") do |root|
  mutate_document(root, ".github/workflows/architecture-decisions.yml") do |text|
    text.gsub("docs/architecture/**", "docs/architecture-files/**")
  end
end

results << assert_success("valid sequential supersession with later ISO date") do |root|
  add_valid_adr_008_successor(root)
end

unless results.all?
  warn "Architecture decision validator tests failed"
  exit 1
end

puts "Architecture decision validator tests passed: #{results.length} regression cases"
