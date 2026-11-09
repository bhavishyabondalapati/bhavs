# bhavs Makefile. AWS profile/region are fixed on purpose.
export AWS_PROFILE ?= sky
export AWS_REGION := us-east-2
export AWS_DEFAULT_REGION := us-east-2
TF := terraform
# State bucket name contains the account id, so it is computed (never committed).
STATE_BUCKET = bhavs-tfstate-$(shell aws sts get-caller-identity --query Account --output text)
export TF_VAR_state_bucket = $(STATE_BUCKET)
INIT = $(TF) init -input=false -backend-config="bucket=$(STATE_BUCKET)" >/dev/null

.PHONY: seed-titles help check-access bootstrap deploy-persistent deploy-app destroy-app destroy-persistent test lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'

check-access: ## Phase 0: verify the AWS account can use every service we need
	@./scripts/check_access.sh

bootstrap: ## One-time: create the Terraform state bucket
	cd infra/bootstrap && $(TF) init && $(TF) plan -out=tfplan && \
	  read -p "Apply bootstrap plan? [y/N] " a && [ "$$a" = y ] && $(TF) apply tfplan

deploy-persistent: ## Plan, then (after you confirm) apply the persistent stack
	cd infra/persistent && $(INIT) && $(TF) plan -out=tfplan && \
	  read -p "Apply persistent plan? [y/N] " a && [ "$$a" = y ] && $(TF) apply tfplan

deploy-app: ## Plan, then (after you confirm) apply the app stack
	cd infra/app && $(INIT) && $(TF) plan -out=tfplan && \
	  read -p "Apply app plan? [y/N] " a && [ "$$a" = y ] && $(TF) apply tfplan

destroy-app: ## Destroy the app stack (safe, recreatable)
	cd infra/app && $(INIT) && $(TF) destroy

destroy-persistent: ## Destroy buckets/tables/Cognito (DATA LOSS) - asks you to type a phrase
	@read -p "Type 'destroy bhavs persistent' to confirm: " a && [ "$$a" = "destroy bhavs persistent" ] || (echo Aborted; exit 1)
	cd infra/persistent && $(INIT) && $(TF) destroy

test: ## Run Python tests
	pytest -q

lint: ## Lint Python
	ruff check .

seed-titles: ## Load film metadata from films.yaml into the titles table (status stays PENDING)
	python scripts/seed_titles.py
