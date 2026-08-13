#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "open3"
require "rbconfig"
require "tmpdir"
require "yaml"

SOURCE_ROOT = File.expand_path("..", __dir__)

def run_validator(root)
  Open3.capture3(RbConfig.ruby, File.join(root, "scripts", "validate_metric_dictionary.rb"))
end

def with_repository_copy
  Dir.mktmpdir("claimsflow-metric-validator-") do |temporary_root|
    %w[README.md contracts docs scripts].each do |entry|
      FileUtils.cp_r(File.join(SOURCE_ROOT, entry), temporary_root)
    end
    yield temporary_root
  end
end

def mutate_metric(root, file_name)
  path = File.join(root, "contracts", "metrics", file_name)
  metric = YAML.safe_load(File.read(path), aliases: false)
  yield metric
  File.write(path, YAML.dump(metric))
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

baseline_stdout, baseline_stderr, baseline_status = run_validator(SOURCE_ROOT)
unless baseline_status.success?
  warn "FAIL baseline validator:\n#{baseline_stdout}#{baseline_stderr}"
  exit 1
end
puts "PASS baseline metric dictionary"

results = []

results << assert_failure("missing governed metric", "Expected exactly") do |root|
  FileUtils.rm(File.join(root, "contracts", "metrics", "denial-rate.yml"))
end

results << assert_failure("duplicate metric id", "Duplicate metric_id") do |root|
  mutate_metric(root, "outstanding-balance.yml") { |metric| metric["metric_id"] = "MET-NCR-001" }
end

results << assert_failure("blank business owner", "business owner must be a non-empty string") do |root|
  mutate_metric(root, "clean-claim-rate.yml") { |metric| metric["business"]["owner"] = "  " }
end

results << assert_failure("incorrect acceptance mapping", "acceptance_criteria must exactly follow requirement mappings") do |root|
  mutate_metric(root, "appeal-success-rate.yml") { |metric| metric["acceptance_criteria"].pop }
end

results << assert_failure("unknown source field", "source dependency claims.imaginary_amount is not declared") do |root|
  mutate_metric(root, "outstanding-balance.yml") { |metric| metric["source_dependencies"]["claims"] << "imaginary_amount" }
end

results << assert_failure("missing trusted-publication status", "missing identity/version/knowledge fields: processing_status") do |root|
  mutate_metric(root, "outstanding-balance.yml") do |metric|
    metric["source_dependencies"]["claims"].delete("processing_status")
  end
end

results << assert_failure("missing knowledge timestamp", "missing identity/version/knowledge fields: trusted_published_at") do |root|
  mutate_metric(root, "outstanding-balance.yml") do |metric|
    metric["source_dependencies"]["claims"].delete("trusted_published_at")
  end
end

results << assert_failure("incomplete source natural key", "missing identity/version/knowledge fields: line_number") do |root|
  mutate_metric(root, "denial-rate.yml") do |metric|
    metric["source_dependencies"]["claim-lines"].delete("line_number")
  end
end

results << assert_failure("wrong period boundary", "time boundary must be start_inclusive_end_exclusive") do |root|
  mutate_metric(root, "denial-rate.yml") { |metric| metric["calculation"]["time"]["boundary"] = "inclusive" }
end

results << assert_failure("non-temporal event field", "must have DATE or TIMESTAMP type") do |root|
  mutate_metric(root, "denial-rate.yml") do |metric|
    metric["calculation"]["time"]["event_field"] = "claims.claim_status"
  end
end

results << assert_failure("undeclared component formula field", "component field reference claims.imaginary_amount is not declared") do |root|
  mutate_metric(root, "outstanding-balance.yml") do |metric|
    metric["calculation"]["numerator"]["field_references"] << "claims.imaginary_amount"
  end
end

results << assert_failure("removed required formula field", "numerator missing required semantic field references: claims.original_claim_id") do |root|
  mutate_metric(root, "clean-claim-rate.yml") do |metric|
    metric["calculation"]["numerator"]["field_references"].delete("claims.original_claim_id")
  end
end

results << assert_failure("missing ratio denominator", "ratio/duration denominator cannot be not_applicable") do |root|
  mutate_metric(root, "net-collection-rate.yml") do |metric|
    denominator = metric["calculation"]["denominator"]
    denominator["aggregation"] = "none"
    denominator["expression"] = "not_applicable"
    denominator["inclusions"] = []
  end
end

results << assert_failure("unsupported dimension", "uses unsupported dimension insurer_group") do |root|
  mutate_metric(root, "first-pass-acceptance-rate.yml") do |metric|
    metric["calculation"]["dimensions"][0]["name"] = "insurer_group"
  end
end

results << assert_failure("denial rate reason denominator", "must not expose denial_reason as an undefined denominator dimension") do |root|
  mutate_metric(root, "denial-rate.yml") do |metric|
    metric["calculation"]["dimensions"] << {"name" => "denial_reason", "source_field" => "denials.denial_reason_code"}
    metric["source_dependencies"]["denials"] << "denial_reason_code"
  end
end

results << assert_failure("missing denial line attribution", "procedure/diagnosis attribution requires complete denial line pointers") do |root|
  mutate_metric(root, "recovered-revenue.yml") do |metric|
    metric["source_dependencies"]["denials"].delete("claim_line_id")
  end
end

results << assert_failure("dimension missing from dependencies", "must appear in source_dependencies") do |root|
  mutate_metric(root, "recovered-revenue.yml") do |metric|
    metric["source_dependencies"]["denials"].delete("payer_id")
  end
end

results << assert_failure("missing null scenario", "scenarios must cover boundary null reversal and dimensional behavior") do |root|
  mutate_metric(root, "days-in-ar.yml") do |metric|
    scenario = metric["test_scenarios"].find { |item| item["category"] == "null" }
    scenario["category"] = "boundary"
  end
end

results << assert_failure("invalid rounding mode", "rounding_mode must be half_away_from_zero") do |root|
  mutate_metric(root, "appeal-success-rate.yml") do |metric|
    metric["calculation"]["precision"]["rounding_mode"] = "bankers"
  end
end

results << assert_failure("missing shared metric governance", "must cite FR-MET-001, FR-MET-002, FR-MET-004, FR-MET-005") do |root|
  mutate_metric(root, "outstanding-balance.yml") do |metric|
    metric["requirements"].delete("FR-MET-005")
    metric["acceptance_criteria"].delete("AC-MET-005")
  end
end

results << assert_failure("unknown definition key", "calculation has unsupported keys: formul") do |root|
  mutate_metric(root, "denial-rate.yml") do |metric|
    metric["calculation"]["formul"] = metric["calculation"]["formula"]
  end
end

results << assert_failure("missing dictionary documentation link", "Metric dictionary README must link denial-rate.yml") do |root|
  mutate_document(root, "docs/metric-dictionary/README.md") do |text|
    text.sub("../../contracts/metrics/denial-rate.yml", "../../contracts/metrics/clean-claim-rate.yml")
  end
end

unless results.all?
  warn "Metric dictionary validator tests failed"
  exit 1
end

puts "Metric dictionary validator tests passed: #{results.length} negative cases"
