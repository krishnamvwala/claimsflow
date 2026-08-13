#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "open3"
require "rbconfig"
require "tmpdir"
require "yaml"

SOURCE_ROOT = File.expand_path("..", __dir__)

def run_validator(root)
  Open3.capture3(RbConfig.ruby, File.join(root, "scripts", "validate_source_contracts.rb"))
end

def with_repository_copy
  Dir.mktmpdir("claimsflow-contract-validator-") do |temporary_root|
    %w[README.md contracts docs scripts].each do |entry|
      FileUtils.cp_r(File.join(SOURCE_ROOT, entry), temporary_root)
    end
    yield temporary_root
  end
end

def mutate_contract(root, file_name)
  path = File.join(root, "contracts", "source-data", file_name)
  contract = YAML.safe_load(File.read(path), aliases: false)
  yield contract
  File.write(path, YAML.dump(contract))
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
puts "PASS baseline contracts"

results = []
results << assert_failure("incomplete direct parent key", "exact_key must target the complete natural key") do |root|
  mutate_contract(root, "payments.yml") do |contract|
    contract["relationships"][0]["target"] = "claims.claim_id"
    contract["relationships"][0]["fields"] = ["claim_id"]
  end
end

results << assert_failure("incomplete effective business key", "effective_at must target the complete business key") do |root|
  mutate_contract(root, "claim-lines.yml") do |contract|
    contract["relationships"][1]["target"] = "reference-data.procedures.procedure_code"
    contract["relationships"][1]["fields"] = ["procedure_code"]
  end
end

results << assert_failure("missing acceptance traceability", "acceptance_criteria must exactly follow its requirement mappings") do |root|
  mutate_contract(root, "claims.yml") { |contract| contract["acceptance_criteria"].pop }
end

results << assert_failure("invalid relationship cardinality", "exact_key cardinality must be exactly_one") do |root|
  mutate_contract(root, "appeals.yml") { |contract| contract["relationships"][0]["cardinality"] = "many" }
end

results << assert_failure("blank grain", "grain must be a non-empty string") do |root|
  mutate_contract(root, "denials.yml") { |contract| contract["grain"] = "  " }
end

unless results.all?
  warn "Source contract validator tests failed"
  exit 1
end

puts "Source contract validator tests passed: #{results.length} negative cases"
