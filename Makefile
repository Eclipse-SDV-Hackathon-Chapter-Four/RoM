# Made with Claude (Claude Code, Anthropic)
# Shortcuts for the dev stack. Run `make help` to list them.
DC = docker compose -f infra/docker-compose.yml

.PHONY: help up down logs kuksa shell test

help:   ## list targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

up:     ## start databroker + mosquitto in the background
	$(DC) up -d databroker mosquitto

down:   ## stop everything
	$(DC) --profile tools down

logs:   ## follow databroker + mosquitto logs
	$(DC) logs -f databroker mosquitto

kuksa:  ## interactive kuksa-client shell in the foreground (starts databroker if needed)
	$(DC) run --rm kuksa-client

shell:  ## bash in the python venv image
	$(DC) run --rm dev bash

test:   ## run pytest
	$(DC) run --rm dev pytest -q common/
