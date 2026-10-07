<!-- Made with Claude (Claude Code, Anthropic) -->
# Final run under Eclipse Ankaios

One command, nothing by hand:

```bash
make final-run                                           # all bundled campaigns (~20 min)
CAMPAIGNS="thermal_runaway sensor_stuck_cell3" make final-run
KEEP=1 make final-run                                    # leave the stack running afterwards (SOVD on :7690)
```

Needs `podman`, `jq`, `curl` and Ankaios ≥ 1.0 (`ank`, `ank-server`, `ank-agent`). No root, no systemd service:
[`scripts/final_run.sh`](../../scripts/final_run.sh) starts its own `ank-server` + `ank-agent` (`rom_hpc`) with the
config files here (not `/etc/ankaios`, which may hold a demo startup manifest) and stops them at the end.

## What happens

1. `podman build` of every service image `localhost/rom/<service>:dev` (+ `databroker` with the VSS overlay baked in)
2. podman network `rom` (containers find each other by `--network-alias`, same names as in compose) and fresh
   volumes: `rom-iceoryx2-shm` + `rom-iceoryx2` (tmpfs, shared by dfm and opensovd), `rom-dfm-storage`
3. `ank apply` [`rom.yaml`](rom.yaml): mosquitto, databroker, simulator, vss-uprotocol-client, dfm, guardian, opensovd
   (start order by Ankaios `dependencies`, `restartPolicy: ALWAYS`)
4. workload `campaigns` (fault-injector, `restartPolicy: NEVER`): every campaign one after the other, `SETTLE_S`
   (15 s) before the first and after each; exit code 1 if any campaign did not complete
5. evidence: `ank logs` of every workload + the SOVD fault list, into `runs/<RUN_ID>/`
6. workload `evidence-collector` with `runs/<RUN_ID>` mounted at `/evidence`
7. teardown: workloads deleted, server + agent stopped

## Evidence directory (input of the evidence collector)

```
runs/<RUN_ID>/                    mounted at /evidence      env: EVIDENCE_DIR=/evidence, RUN_ID, SOVD_URL
  run.json                        {"run_id", "campaigns_state", "ankaios"}
  sovd_faults.json                GET /sovd/v1/apps/battery_guardian/faults after the last campaign
  logs/campaigns.log              fault-injector: campaign_start (hazard, safety_goal, expected_*, max_detect_ms),
                                  fault_injected / fault_cleared, campaign_end, all with run_id
  logs/guardian.log               state_change, reason_change, fault_event (code, stage, msg_id, run_id)
  logs/dfm.log                    fault_record (code, stage, run_id, latency_ms) + dfm_bin text lines
  logs/<other workload>.log       simulator, vss-uprotocol-client, opensovd, databroker, mosquitto
  ankaios/                        generated manifests, server / agent logs
  build.log
```

Log files are JSON lines mixed with plain text lines (dfm_bin, databroker): parse line by line, skip what is not JSON.
The collector writes its report into the same directory (e.g. `report.json`, `report.md`); SOVD is still up while
it runs (`SOVD_URL=http://opensovd:7690/sovd`).

## Limits

- Simulator only. Hardware (AZ3166 + adapter) under Ankaios needs an adapter image and mosquitto on host port 1883.
- One agent; the manifest is ready for more (`agent:` per workload) once there is a second machine.
