#!/usr/bin/env ruby
# frozen_string_literal: true

require "date"
require "set"
require "uri"
require "yaml"

ROOT = File.expand_path("..", __dir__)
ARCHITECTURE_DIR = File.join(ROOT, "docs", "architecture")
ADR_DIR = File.join(ARCHITECTURE_DIR, "adr")
WORKFLOW_PATH = File.join(ROOT, ".github", "workflows", "architecture-decisions.yml")

BASELINE_FILES = {
  "ADR-001-bigquery-data-layers.md" => "ADR-001",
  "ADR-002-dbt-transformation-and-semantic-layer.md" => "ADR-002",
  "ADR-003-airflow-orchestration-and-replay.md" => "ADR-003",
  "ADR-004-python-ingestion-and-validation-boundary.md" => "ADR-004",
  "ADR-005-power-bi-connectivity-and-governed-reporting.md" => "ADR-005",
  "ADR-006-security-privacy-and-access-control.md" => "ADR-006",
  "ADR-007-environments-ci-cd-observability-and-cost.md" => "ADR-007"
}.freeze

BASELINE_REQUIREMENT_ASSIGNMENTS = {
  "ADR-001" => %w[FR-WH-001 FR-WH-002 FR-WH-003 FR-WH-008 NFR-PERF-001 NFR-PERF-002 NFR-PERF-003 NFR-PERF-004],
  "ADR-002" => %w[FR-WH-004 FR-WH-005 FR-WH-006 FR-WH-007 FR-MET-001 FR-MET-002 FR-MET-003 FR-MET-004 FR-MET-005 FR-PRI-001 FR-PRI-002 FR-PRI-003 FR-PRI-004 FR-PRI-005 FR-PRI-006 FR-PRI-007],
  "ADR-003" => %w[FR-ALT-001 FR-ALT-002 FR-ALT-003 FR-ALT-004 FR-ALT-005 FR-ALT-006 FR-ALT-007 FR-OPS-001 FR-OPS-002 FR-OPS-003 FR-OPS-004 FR-OPS-005 FR-OPS-006 NFR-REL-001 NFR-REL-002 NFR-REL-003 NFR-REL-004 NFR-REL-005],
  "ADR-004" => %w[FR-ING-001 FR-ING-002 FR-ING-003 FR-ING-004 FR-ING-005 FR-ING-006 FR-ING-007 FR-ING-008 FR-DQ-001 FR-DQ-002 FR-DQ-003 FR-DQ-004 FR-DQ-005 FR-DQ-006 FR-DQ-007 FR-DQ-008 FR-DQ-009 FR-DQ-010],
  "ADR-005" => %w[FR-BI-001 FR-BI-002 FR-BI-003 FR-BI-004],
  "ADR-006" => %w[NFR-SEC-001 NFR-SEC-002 NFR-SEC-003 NFR-SEC-004 NFR-SEC-005 NFR-SEC-006 NFR-AUD-001 NFR-AUD-002 NFR-AUD-003 NFR-AUD-004 NFR-AUD-005],
  "ADR-007" => %w[NFR-MNT-001 NFR-MNT-002 NFR-MNT-003 NFR-MNT-004 NFR-MNT-005]
}.freeze

ADR_FILE_PATTERN = /\A(ADR-[0-9]{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md\z/
ADR_ID_PATTERN = /\AADR-([0-9]{3})\z/
ALLOWED_STATUSES = Set.new(%w[accepted superseded]).freeze

REQUIRED_FRONT_MATTER = %w[
  adr_id title status decision_date owners requirements acceptance_criteria supersedes
].freeze

REQUIRED_HEADINGS = [
  "## Context",
  "## Decision",
  "## Decision details",
  "## Alternatives considered",
  "## Consequences",
  "### Positive",
  "### Trade-offs",
  "## Security and privacy",
  "## Reliability and recovery",
  "## Validation evidence",
  "## Revisit triggers",
  "## References"
].freeze

EXPECTED_KEYWORDS = {
  "ADR-001" => ["Cloud Storage", "BigQuery", "partition", "cluster", "publication manifest", "maximum bytes billed", "membership delta", "candidate merge"],
  "ADR-002" => ["dbt Core", "BigQuery adapter", "incremental", "snapshot", "metric_id", "priority engine", "candidate publication namespace"],
  "ADR-003" => ["Apache Airflow", "Docker", "backfill", "publication gate", "idempotency key", "verified registration"],
  "ADR-004" => ["typed Python", "stream", "source-contract", "quarantined", "dbt", "before any upload"],
  "ADR-005" => ["Google BigQuery connector", "Import mode", "incremental refresh", "DirectQuery", "stale", "full semantic-model refresh", "affected BI partition ranges", "unbounded historical impact"],
  "ADR-006" => ["synthetic-only", "Workload Identity Federation", "Secret Manager", "least privilege", "encryption", "retention", "400 days"],
  "ADR-007" => ["Terraform", "GitHub Actions", "local", "dev/demo", "release manifest", "structured JSON logs", "maximum bytes billed", "Rollback"]
}.freeze

OFFICIAL_REFERENCE_HOSTS = Set.new(%w[
  airflow.apache.org
  cloud.google.com
  developer.hashicorp.com
  docs.getdbt.com
  docs.python.org
  learn.microsoft.com
]).freeze

WORKFLOW_INPUTS = %w[
  README.md
  docs/requirements.md
  docs/acceptance-criteria.md
  docs/architecture/**
  scripts/validate_architecture_decisions.rb
  scripts/test_architecture_decision_validator.rb
  .github/workflows/architecture-decisions.yml
].freeze

def non_empty_string?(value)
  value.is_a?(String) && !value.strip.empty?
end

def validate_unique_string_list(value, context, errors, allow_empty: false, minimum: 1)
  valid = value.is_a?(Array)
  valid &&= value.length >= (allow_empty ? 0 : minimum)
  valid &&= value.all? { |item| non_empty_string?(item) }
  valid &&= value.uniq.length == value.length
  errors << "#{context} must be #{allow_empty ? 'a' : 'a non-empty'} unique list of strings" unless valid
  valid
end

def read_adr(path, errors)
  content = File.read(path)
  match = content.match(/\A---\s*\n(.*?)\n---\s*\n(.*)\z/m)
  unless match
    errors << "#{File.basename(path)} must contain YAML front matter"
    return [{}, content]
  end

  begin
    metadata = YAML.safe_load(match[1], aliases: false)
  rescue Psych::Exception => e
    errors << "#{File.basename(path)} front matter YAML syntax error: #{e.message.lines.first.strip}"
    return [{}, match[2]]
  end

  unless metadata.is_a?(Hash)
    errors << "#{File.basename(path)} front matter must be a mapping"
    metadata = {}
  end

  [metadata, match[2]]
end

def section(body, heading, next_heading_level: 2)
  heading_pattern = /^#{Regexp.escape(heading)}\s*$\n/
  match = body.match(heading_pattern)
  return "" unless match

  remainder = body[match.end(0)..]
  next_heading = remainder.match(/^#{'#' * next_heading_level}[^#].*$/)
  next_heading ? remainder[0...next_heading.begin(0)] : remainder
end

def validate_internal_links(path, errors)
  File.read(path).scan(/\[[^\]]+\]\(([^)]+)\)/).flatten.each do |raw_target|
    target = raw_target.split("#", 2).first
    next if target.empty? || target.start_with?("http://", "https://", "mailto:")

    resolved = File.expand_path(target, File.dirname(path))
    errors << "#{path.delete_prefix("#{ROOT}/")} has broken internal link #{raw_target}" unless File.file?(resolved)
  end
end

errors = []

requirements_path = File.join(ROOT, "docs", "requirements.md")
acceptance_path = File.join(ROOT, "docs", "acceptance-criteria.md")
requirements_text = File.read(requirements_path)
acceptance_text = File.read(acceptance_path)

known_requirements = requirements_text.scan(/\*\*((?:FR|NFR)-[A-Z]+-[0-9]{3}):\*\*/).flatten
errors << "Requirements baseline must contain exactly 80 unique identifiers" unless known_requirements.length == 80 && known_requirements.uniq.length == 80
known_requirements = known_requirements.to_set

acceptance_pairs = acceptance_text.scan(/^\| (AC-[A-Z]+-[0-9]{3}) \| ((?:FR|NFR)-[A-Z]+-[0-9]{3}) \|/)
criteria = acceptance_pairs.map(&:first)
mapped_requirements = acceptance_pairs.map(&:last)
errors << "Acceptance baseline must contain exactly 80 unique primary criteria" unless criteria.length == 80 && criteria.uniq.length == 80
errors << "Acceptance baseline must map every requirement exactly once" unless mapped_requirements.length == 80 && mapped_requirements.uniq.length == 80 && mapped_requirements.to_set == known_requirements
acceptance_by_requirement = acceptance_pairs.to_h { |criterion, requirement| [requirement, criterion] }

actual_files = Dir.glob(File.join(ADR_DIR, "*.md")).map { |path| File.basename(path) }.sort
missing_baseline_files = BASELINE_FILES.keys - actual_files
errors << "Missing baseline ADR files: #{missing_baseline_files.sort.join(', ')}" unless missing_baseline_files.empty?

seen_ids = Set.new
seen_titles = Set.new
adr_records = []

actual_files.each do |file_name|
  path = File.join(ADR_DIR, file_name)
  file_match = file_name.match(ADR_FILE_PATTERN)
  errors << "ADR filename must match ADR-NNN-lowercase-slug.md: #{file_name}" unless file_match
  expected_id = file_match&.[](1)

  metadata, body = read_adr(path, errors)
  context = file_name

  missing_keys = REQUIRED_FRONT_MATTER.reject { |key| metadata.key?(key) }
  errors << "#{context} missing front matter keys: #{missing_keys.join(', ')}" unless missing_keys.empty?
  unsupported_keys = metadata.keys - REQUIRED_FRONT_MATTER
  errors << "#{context} has unsupported front matter keys: #{unsupported_keys.sort.join(', ')}" unless unsupported_keys.empty?

  adr_id = metadata["adr_id"]
  title = metadata["title"]
  errors << "#{context} adr_id must match its filename ID #{expected_id}" unless adr_id == expected_id
  errors << "Duplicate ADR ID #{adr_id}" if adr_id && seen_ids.include?(adr_id)
  seen_ids << adr_id if adr_id
  errors << "#{context} title must be a non-empty string" unless non_empty_string?(title)
  errors << "Duplicate ADR title #{title}" if title && seen_titles.include?(title)
  seen_titles << title if title
  status = metadata["status"]
  errors << "#{context} status must be accepted or superseded" unless ALLOWED_STATUSES.include?(status)

  decision_date = metadata["decision_date"]
  begin
    Date.iso8601(decision_date)
  rescue ArgumentError, TypeError
    errors << "#{context} decision_date must be an ISO-8601 date string"
  end

  validate_unique_string_list(metadata["owners"], "#{context} owners", errors, minimum: 2)
  errors << "#{context} owners must contain at least two accountable groups" unless metadata["owners"].is_a?(Array) && metadata["owners"].length >= 2
  supersedes = metadata["supersedes"]
  supersedes_valid = validate_unique_string_list(supersedes, "#{context} supersedes", errors, allow_empty: true)
  if supersedes_valid
    supersedes.each do |target_id|
      errors << "#{context} supersedes target must be an ADR ID: #{target_id}" unless target_id.match?(ADR_ID_PATTERN)
    end
  end

  requirements = metadata["requirements"]
  requirements_valid = validate_unique_string_list(requirements, "#{context} requirements", errors)
  if requirements_valid
    requirements.each do |requirement|
      errors << "#{context} references unknown requirement #{requirement}" unless known_requirements.include?(requirement)
    end
    baseline_assignment = BASELINE_REQUIREMENT_ASSIGNMENTS[adr_id]
    errors << "#{context} requirements must match the approved #{adr_id} baseline assignment" if baseline_assignment && requirements != baseline_assignment
  end

  acceptance = metadata["acceptance_criteria"]
  acceptance_valid = validate_unique_string_list(acceptance, "#{context} acceptance_criteria", errors)
  if requirements_valid && acceptance_valid
    expected_acceptance = requirements.map { |requirement| acceptance_by_requirement[requirement] }
    errors << "#{context} acceptance_criteria must exactly follow requirement mappings" unless acceptance == expected_acceptance
  end

  expected_h1 = "# #{expected_id}: #{title}"
  errors << "#{context} H1 must be #{expected_h1.inspect}" unless body.lines.first&.strip == expected_h1

  REQUIRED_HEADINGS.each do |heading|
    count = body.scan(/^#{Regexp.escape(heading)}\s*$/).length
    errors << "#{context} must contain exactly one #{heading} heading" unless count == 1
  end

  decision_text = section(body, "## Decision")
  errors << "#{context} Decision section must state a substantive decision" unless decision_text.strip.length >= 80

  alternatives_text = section(body, "## Alternatives considered")
  alternative_count = alternatives_text.scan(/^### [^#].+$/).length
  errors << "#{context} must document at least two alternatives" unless alternative_count >= 2

  EXPECTED_KEYWORDS.fetch(expected_id, []).each do |keyword|
    errors << "#{context} must document architecture boundary keyword #{keyword.inspect}" unless body.downcase.include?(keyword.downcase)
  end

  references_text = section(body, "## References")
  reference_urls = references_text.scan(/\[[^\]]+\]\((https:\/\/[^)]+)\)/).flatten
  errors << "#{context} must cite at least two official references" unless reference_urls.length >= 2
  reference_urls.each do |url|
    host = URI.parse(url).host
    errors << "#{context} reference must use an approved official host: #{url}" unless OFFICIAL_REFERENCE_HOSTS.include?(host)
  rescue URI::InvalidURIError
    errors << "#{context} has invalid reference URL #{url}"
  end

  validate_internal_links(path, errors)

  adr_records << {
    id: adr_id,
    file_name: file_name,
    title: title,
    status: status,
    requirements: requirements_valid ? requirements : [],
    supersedes: supersedes_valid ? supersedes : []
  }
end

valid_id_numbers = seen_ids.each_with_object([]) do |adr_id, numbers|
  match = adr_id.to_s.match(ADR_ID_PATTERN)
  numbers << match[1].to_i if match
end.sort
unless valid_id_numbers.empty?
  expected_sequence = (1..valid_id_numbers.max).to_a
  errors << "ADR IDs must be sequential without gaps: expected #{expected_sequence.join(', ')}" unless valid_id_numbers == expected_sequence
end

records_by_id = adr_records.each_with_object({}) { |record, index| index[record[:id]] = record if record[:id] }
superseded_by = Hash.new { |hash, key| hash[key] = [] }
adr_records.each do |record|
  record[:supersedes].each do |target_id|
    target = records_by_id[target_id]
    unless target
      errors << "#{record[:file_name]} supersedes unknown ADR #{target_id}"
      next
    end

    source_number = record[:id].to_s.match(ADR_ID_PATTERN)&.[](1)&.to_i
    target_number = target_id.match(ADR_ID_PATTERN)&.[](1)&.to_i
    errors << "#{record[:file_name]} may supersede only an older ADR" unless source_number && target_number && target_number < source_number
    errors << "#{target[:file_name]} must have status superseded when targeted by #{record[:id]}" unless target[:status] == "superseded"
    superseded_by[target_id] << record[:id]
  end
end

adr_records.each do |record|
  successors = superseded_by[record[:id]]
  errors << "#{record[:file_name]} is superseded but does not have exactly one successor" if record[:status] == "superseded" && successors.length != 1
  errors << "#{record[:file_name]} has multiple successors: #{successors.join(', ')}" if successors.length > 1
end

requirement_owner = {}
adr_records.select { |record| record[:status] == "accepted" }.each do |record|
  record[:requirements].each do |requirement|
    if requirement_owner.key?(requirement)
      errors << "Requirement #{requirement} is assigned to active ADRs #{requirement_owner[requirement]} and #{record[:id]}"
    else
      requirement_owner[requirement] = record[:id]
    end
  end
end

missing_coverage = known_requirements - requirement_owner.keys.to_set
errors << "Architecture ADRs missing baseline requirement coverage: #{missing_coverage.to_a.sort.join(', ')}" unless missing_coverage.empty?
unknown_coverage = requirement_owner.keys.to_set - known_requirements
errors << "Architecture ADRs include unknown requirement coverage: #{unknown_coverage.to_a.sort.join(', ')}" unless unknown_coverage.empty?

architecture_readme = File.join(ARCHITECTURE_DIR, "README.md")
if File.file?(architecture_readme)
  readme_text = File.read(architecture_readme)
  registry_text = section(readme_text, "## Decision registry")
  registry_lines = registry_text.lines.map(&:chomp)
  header_index = registry_lines.index("| ADR | Status | Decision |")
  if header_index.nil? || registry_lines[header_index + 1] != "| --- | --- | --- |"
    errors << "Architecture registry must contain the exact three-column header"
    registry_rows = []
  else
    registry_rows = []
    row_index = header_index + 2
    while registry_lines[row_index]&.start_with?("|")
      registry_rows << registry_lines[row_index]
      row_index += 1
    end
  end

  parsed_registry = registry_rows.map do |line|
    match = line.match(/\A\| \[(ADR-[0-9]{3})\]\((adr\/[^)]+)\) \| (Accepted|Superseded) \| ([^|]+) \|\z/)
    errors << "Architecture registry has malformed row: #{line}" unless match
    {id: match[1], link: match[2], status: match[3], title: match[4].strip} if match
  end.compact

  duplicate_registry_ids = parsed_registry.group_by { |row| row[:id] }.select { |_id, rows| rows.length > 1 }.keys
  errors << "Architecture registry repeats ADR rows: #{duplicate_registry_ids.sort.join(', ')}" unless duplicate_registry_ids.empty?
  registry_by_id = parsed_registry.each_with_object({}) { |row, index| index[row[:id]] = row }
  adr_records.each do |record|
    row = registry_by_id[record[:id]]
    unless row
      errors << "Architecture registry must contain exactly one row for #{record[:id]}"
      next
    end

    expected_link = "adr/#{record[:file_name]}"
    expected_status = record[:status].to_s.capitalize
    errors << "Architecture registry #{record[:id]} link must be #{expected_link}" unless row[:link] == expected_link
    errors << "Architecture registry #{record[:id]} status must be #{expected_status}" unless row[:status] == expected_status
    errors << "Architecture registry #{record[:id]} title must match ADR metadata" unless row[:title] == record[:title]
  end
  extra_registry_ids = registry_by_id.keys.to_set - records_by_id.keys.to_set
  errors << "Architecture registry contains unknown ADRs: #{extra_registry_ids.to_a.sort.join(', ')}" unless extra_registry_ids.empty?
  errors << "Architecture registry row count must match ADR file count" unless parsed_registry.length == adr_records.length

  errors << "Architecture README must include a Mermaid system diagram" unless readme_text.include?("```mermaid")
  errors << "Architecture README must state that all 80 baseline requirements are covered" unless readme_text.include?("80 baseline requirements")
  validate_internal_links(architecture_readme, errors)
else
  errors << "Missing docs/architecture/README.md"
end

root_readme = File.join(ROOT, "README.md")
if File.file?(root_readme)
  errors << "Root README must link docs/architecture/README.md" unless File.read(root_readme).include?("docs/architecture/README.md")
  validate_internal_links(root_readme, errors)
else
  errors << "Missing README.md"
end

if File.file?(WORKFLOW_PATH)
  workflow_text = File.read(WORKFLOW_PATH)
  WORKFLOW_INPUTS.each do |input|
    errors << "Architecture workflow must watch #{input}" unless workflow_text.include?(input)
  end
  errors << "Architecture workflow must run the validator" unless workflow_text.include?("ruby scripts/validate_architecture_decisions.rb")
  errors << "Architecture workflow must run negative validator tests" unless workflow_text.include?("ruby scripts/test_architecture_decision_validator.rb")
else
  errors << "Missing .github/workflows/architecture-decisions.yml"
end

whitespace_paths = [
  File.join(ROOT, "README.md"),
  requirements_path,
  acceptance_path,
  architecture_readme,
  WORKFLOW_PATH,
  File.join(ROOT, "scripts", "validate_architecture_decisions.rb"),
  File.join(ROOT, "scripts", "test_architecture_decision_validator.rb"),
  *Dir.glob(File.join(ADR_DIR, "*.md"))
]
whitespace_paths.select { |path| File.file?(path) }.each do |path|
  File.readlines(path, chomp: false).each_with_index do |line, index|
    errors << "#{path.delete_prefix("#{ROOT}/")}:#{index + 1} has trailing whitespace" if line.match?(/[ \t]+(?:\r?\n)?\z/)
  end
end

if errors.empty?
  puts "Architecture decisions valid: #{actual_files.length} ADRs, #{known_requirements.length} requirements, #{criteria.length} acceptance criteria"
else
  warn "Architecture decision validation failed:"
  errors.each { |error| warn "- #{error}" }
  exit 1
end
