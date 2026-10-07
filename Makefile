# Made with Claude (Claude Code, Anthropic)
# Shortcuts for the dev stack. Run `make help` to list them.
# Containers: docker if installed, otherwise podman (Fedora). Override: make DC_BIN="podman compose" up
DC_BIN ?= $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman compose")
DC = $(DC_BIN) -f infra/docker-compose.yml
# Local virtualenv (no containers for Python): needs only python3 with the venv module.
VENV = .venv
PY = $(VENV)/bin/python
# Host port of the compose mosquitto (the AZ3166 board publishes to 1883). Other port: MQTT_HOST_PORT=1884 make guardian
MQTT_HOST_PORT ?= 1883
export MQTT_HOST_PORT

.PHONY: mqtt-port help up down logs kuksa sim sim-up guardian adapter hw dfm-faults dfm-fixtures images venv sim-local test-local shell test

mqtt-port: # stop early when another broker (e.g. a host mosquitto service) already holds the port
	@[ -n "$$($(DC) ps -q mosquitto 2>/dev/null)" ] \
	  || ! python3 -c 'import socket, sys; sys.exit(socket.socket().connect_ex(("127.0.0.1", $(MQTT_HOST_PORT))) != 0)' \
	  || { echo "Port $(MQTT_HOST_PORT) is taken (host mosquitto? sudo systemctl stop mosquitto) - or: MQTT_HOST_PORT=1884 make $(MAKECMDGOALS)"; exit 1; }

help:   ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

up: mqtt-port ## start databroker + mosquitto in the background
	$(DC) up -d databroker mosquitto

down:   ## stop everything
	$(DC) --profile tools --profile todo down

logs:   ## follow databroker + mosquitto logs
	$(DC) --profile tools logs -f databroker mosquitto simulator adapter vss-uprotocol-client guardian dfm

kuksa:  ## interactive kuksa-client shell in the foreground (starts databroker if needed)
	$(DC) run --rm kuksa-client

sim:    ## sine-wave temperature simulator into KUKSA (foreground; SIM_PERIOD_S=60 make sim)
	$(DC) run --rm simulator

sim-up: ## databroker + simulator in the background; then `make kuksa` in another terminal
	$(DC) --profile tools up -d databroker simulator

guardian: mqtt-port ## databroker + simulator + vss-uprotocol-client + guardian + dfm, follows guardian logs (Ctrl+C stops following)
	$(DC) --profile tools up -d --build databroker mosquitto simulator vss-uprotocol-client guardian dfm
	$(DC) --profile tools logs -f guardian

adapter: mqtt-port ## MQTT -> KUKSA adapter in the foreground (starts databroker + mosquitto; stop the simulator first)
	$(DC) --profile tools run --rm adapter

hw: mqtt-port ## hardware run: AZ3166 -> mosquitto -> adapter -> databroker -> vss-uprotocol-client -> guardian + dfm (no simulator)
	$(DC) --profile tools stop simulator
	$(DC) --profile tools up -d --build databroker mosquitto adapter vss-uprotocol-client guardian dfm
	$(DC) --profile tools logs -f adapter guardian

dfm-faults: ## fault records in the running DFM (make guardian first)
	$(DC) --profile tools exec dfm rom-dfm query

dfm-fixtures: ## regenerate services/dfm/fixtures: guardian test scenario -> events -> real DFM -> query output
	$(DC) run --rm --no-deps -T dev python -m guardian.guardian --fault-events > services/dfm/fixtures/guardian_events.jsonl
	$(DC) --profile tools build dfm
	$(firstword $(DC_BIN)) run --rm localhost/rom/dfm:dev sh -c 'dfm_bin --catalog-dir /etc/rom/catalog --storage-dir /tmp/dfm >/dev/null 2>&1 & \
	  rom-dfm replay /etc/rom/fixtures/guardian_events.jsonl >/dev/null && rom-dfm query --stable' > services/dfm/fixtures/battery_guardian_faults.json

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
