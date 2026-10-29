.PHONY: help install all test lint sql-lint security impact clean

help:
	@echo "make install    install with dev tools"
	@echo "make all        generate data, ingest, dbt build, train, score, lineage"
	@echo "make test       full test suite (builds the platform in a temp dir)"
	@echo "make lint       ruff + sqlfluff"
	@echo "make security   checkov scan of the Terraform"
	@echo "make impact M=stg_claims   what a change to M would affect"

install:
	pip install -e ".[dev]"

all:
	claims all

test:
	pytest -q

lint:
	ruff check . && ruff format --check . && sqlfluff lint transform/models transform/tests

security:
	checkov -d infra/terraform --framework terraform --quiet --compact --skip-download

impact:
	python -m claims.lineage impact $(M)

clean:
	rm -rf data transform/target transform/logs
