<!-- Made with Claude (Claude Code, Anthropic) -->
# Final run under Eclipse Ankaios

One command, nothing by hand:

```bash
make final-run                                           # all bundled campaigns (~20 min), exit 1 on any FAIL
CAMPAIGNS="thermal_runaway sensor_stuck_cell3" make final-run
KEEP=1 make final-run                                    # leave the stack running (report :8082/ui/, SOVD :7690)
```

Needs `podman`, `jq`, `curl` and Ankaios ≥ 1.0 (`ank`, `ank-server`, `ank-agent`). No root, no systemd service:
[`scripts/final_run.sh`](../../scripts/final_run.sh) starts its own `ank-server` + `ank-agent` (`rom_hpc`) with the
config files here (not `/etc/ankaios`, which may hold a demo startup manifest) and stops them at the end.

## What happens

1. `podman build` of every service image `localhost/rom/<service>:dev` (+ `databroker` with the VSS overlay baked in)
2. podman network `rom` (containers find each other by `--network-alias`, same names as in compose) and fresh
   volumes: `rom-iceoryx2-shm` + `rom-iceoryx2` (tmpfs, shared by dfm and opensovd), `rom-dfm-storage`,
   `rom-evidence-data`, so DTCs and verdicts are only this run's
3. `ank apply` [`rom.yaml`](rom.yaml): mosquitto, databroker, simulator (with the cooling actuator),
   vss-uprotocol-client, dfm, guardian, opensovd, evidence-collector (start order by Ankaios `dependencies`,
   `restartPolicy: ALWAYS`); the script waits for SOVD and the collector's `/health`
4. workload `campaigns` (fault-injector, `restartPolicy: NEVER`, campaign events over uProtocol to the collector):
   every campaign one after the other, `SETTLE_S` (15 s) before the first and after each
5. the collector judges every run live ([`services/evidence-collector`](../../services/evidence-collector/README.md));
   the script waits for one record per `campaign_end`, then saves verdicts, summary and the evidence bundle
6. `ank logs` of every workload + the SOVD fault list, as a backup of the raw evidence
7. teardown: workloads deleted, server + agent stopped; exit code 1 if any verdict is FAIL

## Output

```
runs/<RUN_ID>/
  evidence.json          every evidence record (verdict, reasons, detection, mitigation, diagnostics, trace)
  summary.json           pass rate, coverage per safety goal, slowest detection
  evidence-bundle.zip    the collector's bundle: records, events.jsonl lines, safety case, report.html, SHA-256 manifest
  run.json               run id, campaigns workload state, Ankaios version, summary
  sovd_faults.json       GET /sovd/v1/apps/battery_guardian/faults after the last campaign
  logs/<workload>.log    ank logs of every workload
  ankaios/               generated campaigns manifest, server / agent logs
  build.log
```

## Limits

- Simulator only. Hardware (AZ3166 + adapter) under Ankaios needs an adapter image and mosquitto on host port 1883.
- One agent; the manifest is ready for more (`agent:` per workload) once there is a second machine.
