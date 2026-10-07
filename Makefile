# Made with Claude (Claude Code, Anthropic)
# Shortcuts for the dev stack. Run `make help` to list them.
# Containers: docker if installed, otherwise podman (Fedora). Override: make DC_BIN="podman compose" up
DC_BIN ?= $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman compose")
DC = $(DC_BIN) -f infra/docker-compose.yml
# Local virtualenv (no containers for Python): needs only python3 with the venv module.
VENV = .venv
PY = $(VENV)/bin/python

.PHONY: help up down logs kuksa sim sim-up guardian adapter hw images venv sim-local test-local shell test

help:   ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

up:     ## start databroker + mosquitto in the background
	$(DC) up -d databroker mosquitto

down:   ## stop everything
	$(DC) --profile tools --profile todo down

logs:   ## follow databroker + mosquitto logs
	$(DC) --profile tools logs -f databroker mosquitto simulator adapter vss-uprotocol-client guardian

kuksa:  ## interactive kuksa-client shell in the foreground (starts databroker if needed)
	$(DC) run --rm kuksa-client

sim:    ## sine-wave temperature simulator into KUKSA (foreground; SIM_PERIOD_S=60 make sim)
	$(DC) run --rm simulator

sim-up: ## databroker + simulator in the background; then `make kuksa` in another terminal
	$(DC) --profile tools up -d databroker simulator

guardian: ## databroker + simulator + vss-uprotocol-client + guardian, follows guardian logs (Ctrl+C stops following)
	$(DC) --profile tools up -d --build databroker simulator vss-uprotocol-client guardian
	$(DC) --profile tools logs -f guardian

adapter: ## MQTT -> KUKSA adapter in the foreground (starts databroker + mosquitto; stop the simulator first)
	$(DC) --profile tools run --rm adapter

hw:     ## hardware run: AZ3166 -> mosquitto -> adapter -> databroker -> vss-uprotocol-client -> guardian (no simulator)
	$(DC) --profile tools stop simulator
	$(DC) --profile tools up -d --build databroker mosquitto adapter vss-uprotocol-client guardian
	$(DC) --profile tools logs -f adapter guardian

images: ## build the service images localhost/rom/<service>:dev (ready for podman / Ankaios)
	$(DC) --profile tools --profile todo build vss-uprotocol-client guardian fault-injector dfm opensovd evidence-collector

venv:   ## create .venv with every RoM package installed editable (reruns when requirements.txt changes)
$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m pip install -q --no-deps up-python==0.2.0.dev0
	touch $@
venv: $(VENV)/.installed

sim-local: venv ## databroker in a container, simulator in the local .venv (foreground, Ctrl+C stops)
	$(DC) up -d databroker
	KUKSA_HOST=127.0.0.1 $(VENV)/bin/rom-simulator

test-local: venv ## run pytest in the local .venv
	$(PY) -m pytest -q

shell:  ## bash in the python venv image
	$(DC) run --rm dev bash

test:   ## run pytest
	$(DC) run --rm dev pytest -q
