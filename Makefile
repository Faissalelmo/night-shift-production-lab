SHELL := bash
.DEFAULT_GOAL := help
SCENARIO ?=
JOB ?=

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

up:  ## build and start everything, wait until healthy
	docker compose up -d --build
	scripts/wait-healthy.sh

down:  ## stop and remove containers (data volumes are kept)
	docker compose down

clean:  ## remove containers AND volumes (database, metrics, logs)
	docker compose down -v

ps:  ## container status
	docker compose ps

inject:  ## break something: make inject SCENARIO=db_down
	scripts/inject.sh $(SCENARIO)

recover:  ## fix it: make recover SCENARIO=db_down
	scripts/recover.sh $(SCENARIO)

demo:  ## run the 5 scenarios in sequence, with pauses (for a video)
	scripts/demo.sh

verify:  ## inject + recover every scenario and assert alerts fire and clear
	scripts/verify.sh

alerts:  ## active alerts in Prometheus and Grafana
	docker compose exec -T jobs python -m lab.tools.alerts list

run:  ## run a batch job now: make run JOB=daily_extract
	docker compose exec -T jobs run-job $(JOB)

logs:  ## follow batch + generator logs
	docker compose logs -f --tail=20 jobs generator

outbox:  ## copy the outbox (tmpfs inside the jobs container) to ./outbox-copy
	docker compose cp jobs:/data/outbox ./outbox-copy

lint:  ## ruff
	ruff check . && ruff format --check .

.PHONY: help up down clean ps inject recover demo verify alerts run logs outbox lint
