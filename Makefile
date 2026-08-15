.PHONY: bootstrap doctor check check-phase0 check-python check-scaffold dbt-parse airflow-up airflow-down terraform-validate

bootstrap:
	uv sync --locked --all-groups

doctor:
	uv run --locked claimsflow doctor

check: check-scaffold check-phase0 check-python dbt-parse

check-scaffold:
	ruby scripts/validate_project_scaffolding.rb
	ruby scripts/test_project_scaffolding_validator.rb

check-phase0:
	ruby scripts/validate_source_contracts.rb
	ruby scripts/test_source_contract_validator.rb
	ruby scripts/validate_metric_dictionary.rb
	ruby scripts/test_metric_dictionary_validator.rb
	ruby scripts/validate_architecture_decisions.rb
	ruby scripts/test_architecture_decision_validator.rb

check-python:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked mypy
	uv run --locked pytest

dbt-parse:
	uv run --locked --group dbt dbt parse --project-dir analytics/dbt --profiles-dir config/dbt --target ci --no-partial-parse

airflow-up:
	docker compose up --build airflow

airflow-down:
	docker compose down --remove-orphans

terraform-validate:
	terraform fmt -check -recursive infra/terraform
	terraform -chdir=infra/terraform/environments/local init -backend=false
	terraform -chdir=infra/terraform/environments/local validate
	terraform -chdir=infra/terraform/environments/dev-demo init -backend=false
	terraform -chdir=infra/terraform/environments/dev-demo validate
