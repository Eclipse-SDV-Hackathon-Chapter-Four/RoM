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

.PHONY: evidence-ci help mqtt-restart up down logs kuksa sim sim-up guardian campaign campaigns campaigns-all evidence evidence-bundle adapter hw sovd sovd-faults dfm-faults dfm-fixtures images venv sim-local test-local shell test

help:   ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

mqtt-restart: ## recreate mosquitto (fresh broker, host port 1883 re-published); runs before up / guardian / adapter / hw
	$(DC) up -d --force-recreate mosquitto
	@# `up` already fails when another process holds port 1883. This only checks that the container really publishes it:
	@# ask compose, not the host (`ss` is not everywhere, Docker Desktop / rootless Podman publish ports elsewhere). Hint only.
	@for i in 1 2 3 4 5; do $(DC) port mosquitto 1883 >/dev/null 2>&1 && exit 0; sleep 1; done; \
	  echo "WARNING: could not confirm that mosquitto publishes port 1883 ($(DC_BIN) port mosquitto 1883 failed); continuing"

up:     mqtt-restart ## start databroker + mosquitto in the background (mosquitto always recreated)
	$(DC) up -d databroker mosquitto

down:   ## stop everything
	$(DC) --profile tools down

logs:   ## follow databroker + mosquitto logs
	$(DC) --profile tools logs -f databroker mosquitto simulator adapter vss-uprotocol-client guardian dfm opensovd evidence-collector

kuksa:  ## interactive kuksa-client shell in the foreground (starts databroker if needed)
	$(DC) run --rm kuksa-client

sim:    ## sine-wave temperature simulator into KUKSA (foreground; SIM_PERIOD_S=60 make sim)
	$(DC) run --rm simulator

sim-up: ## databroker + simulator in the background; then `make kuksa` in another terminal
	$(DC) --profile tools up -d databroker simulator

guardian: mqtt-restart ## databroker + simulator + vss-uprotocol-client + guardian + dfm + opensovd + evidence-collector, follows guardian logs (Ctrl+C stops following)
	$(DC) --profile tools up -d --build databroker simulator vss-uprotocol-client guardian dfm opensovd evidence-collector
	$(DC) --profile tools logs -f guardian

adapter: mqtt-restart ## MQTT -> KUKSA adapter in the foreground (starts databroker + mosquitto; stop the simulator first)
	$(DC) --profile tools run --rm adapter

hw:     mqtt-restart ## hardware run: AZ3166 = cell 1 -> mosquitto -> adapter -> databroker -> vss-uprotocol-client -> guardian + dfm + opensovd; simulator fills cells 2-4; guardian expects the chip + adapter heartbeats
	SIM_CELLS=2,3,4 REQUIRED_HEARTBEATS=uprotocol,databroker,adapter,chip $(DC) --profile tools up -d --build databroker mosquitto adapter simulator vss-uprotocol-client guardian dfm opensovd evidence-collector
	$(DC) --profile tools logs -f adapter guardian

campaigns: ## list the bundled fault campaigns
	$(DC) --profile tools run --rm fault-injector rom-fault-injector list

campaign: ## run a fault campaign against the running stack: make campaign C=thermal_runaway (after `make guardian`)
	@test -n "$(C)" || { echo "usage: make campaign C=<name>   (make campaigns lists them)"; exit 2; }
	$(DC) --profile tools run --rm fault-injector rom-fault-injector run $(C)

campaigns-all: ## run every bundled campaign one after another (the evidence collector judges each); ~15 min
	@for c in $$($(DC) --profile tools run --rm -T fault-injector rom-fault-injector list); do \
	  echo "== $$c"; $(DC) --profile tools run --rm -T fault-injector rom-fault-injector run $$c >/dev/null || echo "   $$c did not complete"; \
	  sleep 8; done   # let the guardian settle back to MONITORING (stale / stuck timers, heartbeats) before the next one
	@$(MAKE) --no-print-directory evidence

evidence: ## verdicts of the evidence collector (http://localhost:8082/ui/ for the report)
	@curl -sf http://localhost:8082/evidence/summary | python3 -m json.tool
	@curl -sf 'http://localhost:8082/evidence?limit=20' | python3 -c 'import json,sys; [print(r["verdict"].ljust(13), r["record_id"], "; ".join(x["text"] for x in r["reasons"])) for r in json.load(sys.stdin)]'

# Campaigns CI runs end to end: short ones, one per fault class (source, transport, signal) plus the thermal runaway.
CI_CAMPAIGNS ?= source_dropout transport_drop sensor_stuck_cell3 thermal_runaway

evidence-ci: ## CI: stack up, CI_CAMPAIGNS one by one, evidence-ci.zip verified offline; fails unless every run PASSes
	$(DC) --profile tools up -d --build databroker simulator vss-uprotocol-client guardian dfm opensovd evidence-collector
	@echo "waiting for the evidence collector and a MONITORING guardian ..."; \
	for i in $$(seq 90); do curl -sf localhost:8082/health | grep -q '"guardian_state":"MONITORING"' && exit 0; sleep 2; done; \
	curl -s localhost:8082/health; echo; $(DC) --profile tools logs --tail 30 guardian evidence-collector; exit 1
	@python3 -c 'import time; print(int(time.time() * 1000))' > .evidence-ci-start
	@for c in $(CI_CAMPAIGNS); do echo "== $$c"; \
	  $(DC) --profile tools run --rm -T fault-injector rom-fault-injector run $$c >/dev/null || exit 1; sleep 8; done
	@$(MAKE) --no-print-directory evidence
	curl -sf -o evidence-ci.zip "http://localhost:8082/evidence/bundle.zip?since=$$(cat .evidence-ci-start)"
	$(DC) run --rm --no-deps -T dev rom-evidence-collector verify /app/evidence-ci.zip
	@curl -sf 'http://localhost:8082/evidence?limit=1000' | python3 -c 'import json,sys; t0=int(open(".evidence-ci-start").read()); \
	  rs=[r for r in json.load(sys.stdin) if (r["started_at"] or 0) >= t0]; \
	  bad=[r["record_id"] for r in rs if r["verdict"] != "PASS"]; print(f"{len(rs)} runs, not PASS: {bad or None}"); \
	  sys.exit(1 if bad or len(rs) != len(sys.argv[1:]) else 0)' $(CI_CAMPAIGNS)

evidence-bundle: ## download the evidence bundle (ZIP with SHA-256 manifest): make evidence-bundle [RUN=thermal-runaway-01]
	curl -sfOJ 'http://localhost:8082/evidence/bundle.zip$(if $(RUN),?run_id=$(RUN))'

sovd:   ## DFM + Eclipse OpenSOVD server in the background (SOVD REST on http://localhost:7690/sovd)
	$(DC) --profile tools up -d --build dfm opensovd

sovd-faults: ## battery_guardian faults from the DFM over SOVD (GET /sovd/v1/apps/battery_guardian/faults)
	@curl -sf http://localhost:7690/sovd/v1/apps/battery_guardian/faults | python3 -m json.tool

dfm-faults: ## fault records in the running DFM (make guardian first)
	$(DC) --profile tools exec dfm rom-dfm query

dfm-fixtures: ## regenerate services/dfm/fixtures: guardian test scenario -> events -> real DFM -> query output
	$(DC) run --rm --no-deps -T dev sh -c 'python -m guardian.guardian --fault-events > /app/services/dfm/fixtures/guardian_events.jsonl'
	$(DC) --profile tools build dfm
	$(firstword $(DC_BIN)) run --rm localhost/rom/dfm:dev sh -c 'dfm_bin --catalog-dir /etc/rom/catalog --storage-dir /tmp/dfm >/dev/null 2>&1 & \
	  rom-dfm replay /etc/rom/fixtures/guardian_events.jsonl >/dev/null && rom-dfm query --stable' > services/dfm/fixtures/battery_guardian_faults.json

images: ## build the service images localhost/rom/<service>:dev (ready for podman / Ankaios)
	$(DC) --profile tools build vss-uprotocol-client guardian fault-injector dfm opensovd evidence-collector

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
