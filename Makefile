# Made with Claude (Claude Code, Anthropic)
# Shortcuts for the dev stack. Run `make help` to list them.
DC = docker compose -f infra/docker-compose.yml

.PHONY: help up down logs kuksa sim sim-up shell test

help:   ## list targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

up:     ## start databroker + mosquitto in the background
	$(DC) up -d databroker mosquitto

down:   ## stop everything
	$(DC) --profile tools down

logs:   ## follow databroker + mosquitto logs
	$(DC) --profile tools logs -f databroker mosquitto simulator

kuksa:  ## interactive kuksa-client shell in the foreground (starts databroker if needed)
	$(DC) run --rm kuksa-client

sim:    ## sine-wave temperature simulator into KUKSA (foreground; SIM_PERIOD_S=60 make sim)
	$(DC) run --rm simulator

sim-up: ## databroker + simulator in the background; then `make kuksa` in another terminal
	$(DC) --profile tools up -d databroker simulator

shell:  ## bash in the python venv image
	$(DC) run --rm dev bash

test:   ## run pytest
	$(DC) run --rm dev pytest -q common/ simulator/
